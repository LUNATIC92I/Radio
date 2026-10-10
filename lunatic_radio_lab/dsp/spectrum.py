"""Estimation spectrale (périodogramme moyenné de Welch) et mesures associées.

Convention d'échelle : une sinusoïde complexe d'amplitude 1 (pleine échelle) centrée
sur une case FFT donne 0 dBFS sur cette case. La densité de bruit affichée dépend de
la résolution (RBW) ; la puissance de canal est obtenue en intégrant les cases et en
corrigeant de la largeur de bande équivalente de bruit (ENBW) de la fenêtre.

Les puissances sont RELATIVES (dBFS) tant que l'utilisateur n'a pas fourni
d'étalonnage : elles dépendent du gain, du câblage et de l'antenne.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from scipy import signal as sps

from ..models import SpectrumFrame

WINDOWS = ("blackmanharris", "hann", "hamming", "flattop", "boxcar")
_EPS = 1e-20


@dataclass(frozen=True)
class WindowInfo:
    window: np.ndarray
    coherent_gain: float  # somme(w)
    power_sum: float  # somme(w²)
    enbw_bins: float  # N·Σw²/(Σw)²


_window_cache: dict[tuple[str, int], WindowInfo] = {}


def window_info(name: str, n: int) -> WindowInfo:
    key = (name, n)
    if key not in _window_cache:
        if name not in WINDOWS:
            raise ValueError(f"Fenêtre inconnue : {name}")
        w = sps.get_window(name, n, fftbins=True).astype(np.float64)
        cg = float(w.sum())
        ps = float((w * w).sum())
        _window_cache[key] = WindowInfo(w, cg, ps, n * ps / (cg * cg))
    return _window_cache[key]


def welch_psd(
    iq: np.ndarray,
    fft_size: int = 2048,
    window: str = "blackmanharris",
    overlap: float = 0.5,
    max_segments: int | None = None,
) -> tuple[np.ndarray, int, WindowInfo]:
    """Retourne (puissance linéaire normalisée « sinusoïde » par case, nb de segments, fenêtre).

    Les cases sont ordonnées des fréquences négatives aux positives (fftshift).
    """
    iq = np.asarray(iq)
    if iq.ndim != 1:
        raise ValueError("IQ doit être un vecteur 1-D")
    if fft_size < 16 or fft_size & (fft_size - 1):
        raise ValueError("fft_size doit être une puissance de 2 ≥ 16")
    if not 0.0 <= overlap < 1.0:
        raise ValueError("overlap doit être dans [0, 1[")
    wi = window_info(window, fft_size)
    if len(iq) < fft_size:
        iq = np.concatenate([iq, np.zeros(fft_size - len(iq), dtype=iq.dtype)])
    step = max(1, int(fft_size * (1.0 - overlap)))
    n_seg = 1 + (len(iq) - fft_size) // step
    if max_segments:
        n_seg = min(n_seg, max_segments)
    idx = np.arange(fft_size)[None, :] + step * np.arange(n_seg)[:, None]
    segs = iq[idx] * wi.window[None, :]
    spec = np.fft.fft(segs, axis=1)
    p = (np.abs(spec) ** 2).mean(axis=0) / (wi.coherent_gain**2)
    return np.fft.fftshift(p), n_seg, wi


def freq_axis(fft_size: int, sample_rate: float, center_freq: float = 0.0) -> np.ndarray:
    return np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / sample_rate)) + center_freq


def to_db(p_lin: np.ndarray | float) -> np.ndarray | float:
    return 10.0 * np.log10(np.maximum(p_lin, _EPS))


def from_db(p_db: np.ndarray | float) -> np.ndarray | float:
    return 10.0 ** (np.asarray(p_db) / 10.0)


def estimate_noise_floor_db(power_db: np.ndarray, exclude_dc_bins: int = 0) -> float:
    """Plancher de bruit par case (dBFS) : médiane robuste, insensible aux émissions étroites.

    Biais connu : pour un périodogramme peu moyenné, la médiane sous-estime la moyenne
    du bruit d'environ 1,6 dB (loi exponentielle). Le biais diminue avec le moyennage.
    """
    p = np.asarray(power_db)
    if exclude_dc_bins > 0:
        mid = len(p) // 2
        p = np.concatenate([p[: mid - exclude_dc_bins], p[mid + exclude_dc_bins + 1 :]])
    lin = from_db(p)
    return float(to_db(np.median(lin)))


def band_power_db(power_db: np.ndarray, enbw_bins: float, sl: slice | np.ndarray | None = None) -> float:
    """Puissance intégrée (dBFS) sur un ensemble de cases (corrigée de l'ENBW)."""
    p = from_db(power_db if sl is None else power_db[sl])
    return float(to_db(np.sum(p) / enbw_bins))


def saturation_ratio(iq: np.ndarray, full_scale: float = 1.0, level: float = 0.98) -> float:
    """Fraction d'échantillons dont |I| ou |Q| atteint la pleine échelle (écrêtage ADC)."""
    if len(iq) == 0:
        return 0.0
    lim = level * full_scale
    clipped = (np.abs(iq.real) >= lim) | (np.abs(iq.imag) >= lim)
    return float(np.count_nonzero(clipped)) / len(iq)


def dynamic_range_db(adc_bits: int | None) -> float | None:
    """Dynamique théorique d'un ADC idéal (6,02·N + 1,76 dB), hors gain de traitement FFT."""
    if not adc_bits:
        return None
    return 6.02 * adc_bits + 1.76


class SpectrumAnalyzer:
    """Transforme des blocs IQ en trames de spectre (avec indicateurs de qualité)."""

    def __init__(
        self,
        fft_size: int = 2048,
        window: str = "blackmanharris",
        overlap: float = 0.5,
        saturation_threshold: float = 1e-3,
        dc_exclude_bins: int = 0,
        video_avg: float = 0.0,
    ) -> None:
        self.fft_size = fft_size
        self.window = window
        self.overlap = overlap
        self.saturation_threshold = saturation_threshold
        self.dc_exclude_bins = dc_exclude_bins
        self.video_avg = video_avg  # lissage exponentiel entre trames (0 = désactivé)
        self._prev: np.ndarray | None = None

    def reset(self) -> None:
        self._prev = None

    def process(
        self,
        iq: np.ndarray,
        center_freq_hz: float,
        sample_rate_hz: float,
        receiver_id: str = "",
        simulated: bool = False,
        gain_db: float | None = None,
        timestamp: float | None = None,
    ) -> SpectrumFrame:
        p_lin, n_seg, wi = welch_psd(iq, self.fft_size, self.window, self.overlap)
        if self.video_avg > 0 and self._prev is not None and self._prev.shape == p_lin.shape:
            p_lin = self.video_avg * self._prev + (1.0 - self.video_avg) * p_lin
        self._prev = p_lin
        p_db = to_db(p_lin)
        sat = saturation_ratio(iq)
        return SpectrumFrame(
            freqs_hz=freq_axis(self.fft_size, sample_rate_hz, center_freq_hz),
            power_dbfs=p_db.astype(np.float32),
            timestamp=time.time() if timestamp is None else timestamp,
            center_freq_hz=float(center_freq_hz),
            sample_rate_hz=float(sample_rate_hz),
            fft_size=self.fft_size,
            averages=n_seg,
            rbw_hz=wi.enbw_bins * sample_rate_hz / self.fft_size,
            enbw_bins=wi.enbw_bins,
            noise_floor_dbfs=estimate_noise_floor_db(p_db, self.dc_exclude_bins),
            saturation_ratio=sat,
            saturated=sat >= self.saturation_threshold,
            simulated=simulated,
            receiver_id=receiver_id,
            gain_db=gain_db,
        )
