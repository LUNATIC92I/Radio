"""Traitement audio de laboratoire (enregistrements légaux / transmissions de test autorisées).

Lecture/écriture WAV (PCM 16/24/32 bits, flottant), conversion d'autres formats via
FFmpeg (optionnel), mesures de niveau, réduction de bruit, normalisation, découpage.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import signal as sps
from scipy.io import wavfile

FFMPEG_FORMATS = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac"}


@dataclass
class AudioClip:
    samples: np.ndarray  # float32 mono, plage nominale [-1, 1]
    sample_rate: int
    source: str = ""
    simulated: bool = False

    @property
    def duration_s(self) -> float:
        return len(self.samples) / float(self.sample_rate) if self.sample_rate else 0.0

    def copy(self, samples: np.ndarray | None = None) -> AudioClip:
        return AudioClip(
            (self.samples if samples is None else samples).astype(np.float32),
            self.sample_rate, self.source, self.simulated,
        )


@dataclass
class AudioLevels:
    peak_dbfs: float
    rms_dbfs: float
    crest_factor_db: float
    dc_offset: float
    clipped_ratio: float
    noise_floor_dbfs: float  # RMS du 10e centile des fenêtres de 50 ms

    def as_rows(self) -> list[tuple[str, str]]:
        return [
            ("Niveau crête", f"{self.peak_dbfs:.1f} dBFS"),
            ("Niveau efficace (RMS)", f"{self.rms_dbfs:.1f} dBFS"),
            ("Facteur de crête", f"{self.crest_factor_db:.1f} dB"),
            ("Composante continue", f"{self.dc_offset:+.4f}"),
            ("Échantillons écrêtés", f"{self.clipped_ratio:.3%}"),
            ("Bruit de fond estimé", f"{self.noise_floor_dbfs:.1f} dBFS"),
        ]


def _to_float(data: np.ndarray) -> np.ndarray:
    if data.dtype == np.uint8:
        x = (data.astype(np.float32) - 128.0) / 128.0
    elif data.dtype == np.int16:
        x = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        x = data.astype(np.float32) / 2147483648.0
    else:
        x = data.astype(np.float32)
    if x.ndim == 2:
        x = x.mean(axis=1)
    return x


def load_wav(path: str | Path) -> AudioClip:
    sr, data = wavfile.read(str(path))
    return AudioClip(_to_float(data), int(sr), str(path))


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def load_audio(path: str | Path, timeout_s: float = 60.0) -> AudioClip:
    """Charge un fichier audio. Les formats non-WAV passent par FFmpeg (sans shell)."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".wav":
        return load_wav(path)
    if ext in FFMPEG_FORMATS:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("FFmpeg est requis pour lire ce format (installez ffmpeg) ; utilisez un fichier WAV.")
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "conv.wav"
            subprocess.run(
                [exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(path), "-ac", "1",
                 "-c:a", "pcm_s16le", str(out)],
                check=True, timeout=timeout_s, capture_output=True,
            )
            clip = load_wav(out)
            clip.source = str(path)
            return clip
    raise ValueError(f"Format audio non pris en charge : {ext}")


def save_wav(clip: AudioClip, path: str | Path, bits: int = 16) -> Path:
    path = Path(path)
    x = np.clip(clip.samples, -1.0, 1.0)
    if bits == 16:
        data = (x * 32767.0).astype(np.int16)
    elif bits == 32:
        data = x.astype(np.float32)
    else:
        raise ValueError("bits doit valoir 16 ou 32 (flottant)")
    wavfile.write(str(path), int(clip.sample_rate), data)
    return path


def measure_levels(clip: AudioClip) -> AudioLevels:
    x = clip.samples.astype(np.float64)
    if len(x) == 0:
        return AudioLevels(-np.inf, -np.inf, 0.0, 0.0, 0.0, -np.inf)
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x**2)))
    db = lambda v: float(20 * np.log10(max(v, 1e-12)))  # noqa: E731
    win = max(1, int(0.05 * clip.sample_rate))
    nb = len(x) // win
    if nb >= 4:
        r = np.sqrt((x[: nb * win].reshape(nb, win) ** 2).mean(axis=1))
        nf = float(np.percentile(r, 10))
    else:
        nf = rms
    return AudioLevels(
        peak_dbfs=db(peak), rms_dbfs=db(rms), crest_factor_db=db(peak) - db(rms),
        dc_offset=float(np.mean(x)), clipped_ratio=float(np.mean(np.abs(x) >= 0.999)), noise_floor_dbfs=db(nf),
    )


def normalize(clip: AudioClip, target_dbfs: float = -1.0, mode: str = "peak") -> AudioClip:
    """Normalisation crête ou RMS ; la crête résultante est limitée à 0 dBFS."""
    x = clip.samples.astype(np.float64) - np.mean(clip.samples)
    ref = np.max(np.abs(x)) if mode == "peak" else np.sqrt(np.mean(x**2))
    if ref <= 0:
        return clip.copy()
    g = 10 ** (target_dbfs / 20) / ref
    pk = np.max(np.abs(x)) * g
    if pk > 1.0:
        g /= pk
    return clip.copy(x * g)


def bandpass(clip: AudioClip, low_hz: float = 300.0, high_hz: float = 3_400.0, order: int = 6) -> AudioClip:
    """Filtre passe-bande (ex. bande vocale ; supprime la tonalité CTCSS sous 300 Hz)."""
    nyq = clip.sample_rate / 2
    high_hz = min(high_hz, 0.95 * nyq)
    sos = sps.butter(order, [low_hz, high_hz], btype="bandpass", fs=clip.sample_rate, output="sos")
    return clip.copy(sps.sosfiltfilt(sos, clip.samples))


def reduce_noise(clip: AudioClip, reduction_db: float = 12.0, noise_percentile: float = 15.0,
                 n_fft: int = 1024) -> AudioClip:
    """Réduction de bruit par soustraction spectrale (porte spectrale douce).

    Le profil de bruit est estimé, pour chaque fréquence, sur les trames les plus
    calmes (centile). Convient aux enregistrements de test ; peut introduire des
    artefacts (« bruit musical ») si la réduction est trop forte.
    """
    x = clip.samples.astype(np.float64)
    if len(x) < n_fft * 2:
        return clip.copy()
    f, t, Z = sps.stft(x, fs=clip.sample_rate, nperseg=n_fft, noverlap=3 * n_fft // 4)
    mag = np.abs(Z)
    noise = np.percentile(mag, noise_percentile, axis=1, keepdims=True)
    floor = 10 ** (-reduction_db / 20)
    gain = np.maximum(1.0 - (noise * 1.5) / np.maximum(mag, 1e-12), floor)
    gain = sps.medfilt2d(gain, kernel_size=(1, 5))  # lissage temporel du gain
    _, y = sps.istft(Z * gain, fs=clip.sample_rate, nperseg=n_fft, noverlap=3 * n_fft // 4)
    return clip.copy(y[: len(x)])


def trim(clip: AudioClip, start_s: float, end_s: float | None = None) -> AudioClip:
    n0 = max(0, int(round(start_s * clip.sample_rate)))
    n1 = len(clip.samples) if end_s is None else min(len(clip.samples), int(round(end_s * clip.sample_rate)))
    if n1 <= n0:
        raise ValueError("Intervalle de découpage vide")
    return clip.copy(clip.samples[n0:n1])


def auto_trim_silence(clip: AudioClip, threshold_db: float = -45.0, pad_s: float = 0.1) -> AudioClip:
    win = max(1, int(0.02 * clip.sample_rate))
    x = clip.samples
    nb = len(x) // win
    if nb == 0:
        return clip.copy()
    r = 20 * np.log10(np.sqrt((x[: nb * win].reshape(nb, win) ** 2).mean(axis=1)) + 1e-12)
    on = np.flatnonzero(r > threshold_db)
    if len(on) == 0:
        return clip.copy()
    s = max(0.0, on[0] * win / clip.sample_rate - pad_s)
    e = min(clip.duration_s, (on[-1] + 1) * win / clip.sample_rate + pad_s)
    return trim(clip, s, e)


def spectrogram(clip: AudioClip, n_fft: int = 512) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(fréquences Hz, temps s, puissance dBFS[f, t])."""
    f, t, S = sps.spectrogram(clip.samples, fs=clip.sample_rate, nperseg=n_fft, noverlap=n_fft // 2,
                              window="hann", scaling="spectrum")
    return f, t, 10 * np.log10(S + 1e-14)


def waveform_envelope(clip: AudioClip, points: int = 4000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Enveloppe min/max décimée pour l'affichage de la forme d'onde."""
    x = clip.samples
    if len(x) <= points:
        t = np.arange(len(x)) / clip.sample_rate
        return t, x, x
    step = len(x) // points
    nb = len(x) // step
    blk = x[: nb * step].reshape(nb, step)
    t = (np.arange(nb) * step + step / 2) / clip.sample_rate
    return t, blk.min(axis=1), blk.max(axis=1)


def synthetic_test_clip(duration_s: float = 3.0, sample_rate: int = 16_000, tone_hz: float = 1_000.0,
                        noise_dbfs: float = -35.0, seed: int = 7) -> AudioClip:
    """Clip de test synthétique : tonalité 1 kHz hachée + bruit (marqué « simulé »)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(duration_s * sample_rate)) / sample_rate
    gate = ((t % 1.0) < 0.6).astype(float)
    x = 0.5 * np.sin(2 * np.pi * tone_hz * t) * gate
    x += 10 ** (noise_dbfs / 20) * rng.standard_normal(len(t))
    return AudioClip(x.astype(np.float32), sample_rate, "synthétique", simulated=True)
