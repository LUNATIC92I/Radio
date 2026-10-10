"""Canalisation et démodulation FM analogique.

Uniquement la FM analogique en clair. Aucun décodage de protocole numérique ni
traitement de flux chiffrés n'est implémenté (choix de conception volontaire).
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
from scipy import signal as sps


def frequency_shift(iq: np.ndarray, offset_hz: float, sample_rate: float) -> np.ndarray:
    """Translate le signal de -offset_hz (amène `offset_hz` en bande de base)."""
    n = np.arange(len(iq))
    return (iq * np.exp(-2j * np.pi * offset_hz * n / sample_rate)).astype(np.complex64)


def channelize(
    iq: np.ndarray, sample_rate: float, offset_hz: float, bandwidth_hz: float, min_rate: float | None = None
) -> tuple[np.ndarray, float]:
    """Isole un canal : translation, filtre passe-bas, décimation entière.

    Retourne (iq_canal, nouvelle_fréquence_d'échantillonnage).
    """
    if bandwidth_hz <= 0:
        raise ValueError("Largeur de bande invalide")
    x = frequency_shift(np.asarray(iq), offset_hz, sample_rate)
    target = max(min_rate or 0.0, 2.5 * bandwidth_hz)
    dec = max(1, int(sample_rate // target))
    cutoff = min(0.45 * sample_rate / dec, bandwidth_hz / 2)
    taps = sps.firwin(129, cutoff, fs=sample_rate)
    y = sps.lfilter(taps, 1.0, x)[64:]  # compense le retard de groupe
    y = y[::dec]
    return y.astype(np.complex64), sample_rate / dec


def instantaneous_frequency(iq: np.ndarray, sample_rate: float) -> np.ndarray:
    """Fréquence instantanée (Hz) par discriminateur en quadrature."""
    if len(iq) < 2:
        return np.zeros(0)
    d = iq[1:] * np.conj(iq[:-1])
    return np.angle(d) * sample_rate / (2 * np.pi)


def resample(x: np.ndarray, fs_in: float, fs_out: float) -> np.ndarray:
    if abs(fs_in - fs_out) < 1e-6:
        return x
    fr = Fraction(fs_out / fs_in).limit_denominator(1000)
    return sps.resample_poly(x, fr.numerator, fr.denominator)


def deemphasis(audio: np.ndarray, fs: float, tau_us: float) -> np.ndarray:
    """Désaccentuation du 1er ordre (constante de temps en µs)."""
    if tau_us <= 0:
        return audio
    a = math.exp(-1.0 / (fs * tau_us * 1e-6))
    return sps.lfilter([1 - a], [1, -a], audio)


def fm_demodulate(
    iq: np.ndarray,
    sample_rate: float,
    audio_rate: float = 16_000.0,
    deviation_hz: float = 2_500.0,
    deemphasis_us: float = 0.0,
    audio_band: tuple[float, float] | None = (300.0, 3_400.0),
    squelch_db: float | None = None,
) -> np.ndarray:
    """Démodule une FM bande étroite déjà centrée (bande de base).

    Sortie : audio float32 normalisé (excursion nominale ≈ ±1).
    """
    inst = instantaneous_frequency(np.asarray(iq), sample_rate)
    audio = inst / max(deviation_hz, 1.0)
    audio = resample(audio, sample_rate, audio_rate)
    if deemphasis_us:
        audio = deemphasis(audio, audio_rate, deemphasis_us)
    if audio_band is not None:
        lo, hi = audio_band
        hi = min(hi, 0.45 * audio_rate)
        sos = sps.butter(4, [lo, hi], btype="bandpass", fs=audio_rate, output="sos")
        audio = sps.sosfiltfilt(sos, audio) if len(audio) > 30 else audio
    if squelch_db is not None and len(iq):
        env = np.abs(iq)
        lvl = 20 * np.log10(np.maximum(env, 1e-12))
        gate = resample((lvl > squelch_db).astype(float), sample_rate, audio_rate)[: len(audio)] > 0.5
        audio = audio[: len(gate)] * gate
    return np.clip(audio, -1.5, 1.5).astype(np.float32)


class StreamingFMDemodulator:
    """Démodulateur FM en flux pour l'écoute temps réel d'un canal autorisé.

    Tous les états (oscillateur, filtres, décimation, discriminateur, rééchantillonnage)
    sont conservés entre les blocs : pas de discontinuité aux jointures. Squelch basé
    sur la puissance du canal relativement à une référence de bruit glissante.
    """

    def __init__(self, sample_rate: float, offset_hz: float, bandwidth_hz: float = 12_500.0,
                 audio_rate: float = 16_000.0, deviation_hz: float = 2_500.0, squelch_db: float | None = 8.0,
                 deemphasis_us: float = 0.0):
        self.fs = float(sample_rate)
        self.offset = float(offset_hz)
        self.audio_rate = float(audio_rate)
        self.deviation = float(deviation_hz)
        self.squelch_db = squelch_db
        self.dec = max(1, int(self.fs // max(2.5 * bandwidth_hz, 2.2 * audio_rate / 2 * 2)))
        self.ch_rate = self.fs / self.dec
        self.taps = sps.firwin(129, min(bandwidth_hz / 2, 0.45 * self.ch_rate), fs=self.fs)
        self._zi = np.zeros(len(self.taps) - 1, dtype=complex)
        self._n = 0  # compteur d'échantillons (phase de l'oscillateur)
        self._dec_phase = 0
        self._last = 1.0 + 0j
        self._rs_pos = 0.0  # position fractionnaire du rééchantillonneur
        self._rs_prev = 0.0
        self._step = self.ch_rate / self.audio_rate
        hi = min(3_400.0, 0.45 * audio_rate)
        self._sos = sps.butter(4, [300.0, hi], btype="bandpass", fs=audio_rate, output="sos")
        self._sos_zi = np.zeros((self._sos.shape[0], 2))
        self._deemph = math.exp(-1.0 / (audio_rate * deemphasis_us * 1e-6)) if deemphasis_us > 0 else None
        self._de_zi = np.zeros(1)
        self._noise_hist: list[float] = []
        self.bandwidth = float(bandwidth_hz)
        self.noise_ref_db: float | None = None  # bruit attendu dans le canal (fourni par l'analyseur)
        self.squelch_open = False
        self.last_power_db = -200.0

    def set_noise_floor(self, floor_dbfs_per_bin: float, rbw_hz: float) -> None:
        """Référence de bruit issue du spectre : bruit du canal = plancher/case + 10·log(B/RBW)."""
        self.noise_ref_db = floor_dbfs_per_bin + 10 * math.log10(self.bandwidth / max(rbw_hz, 1e-9))

    def process(self, iq: np.ndarray) -> np.ndarray:
        n = np.arange(self._n, self._n + len(iq))
        self._n += len(iq)
        x = np.asarray(iq) * np.exp(-2j * np.pi * self.offset * n / self.fs)
        y, self._zi = sps.lfilter(self.taps, 1.0, x, zi=self._zi)
        y = y[self._dec_phase :: self.dec]
        self._dec_phase = (self._dec_phase - len(x)) % self.dec
        if len(y) == 0:
            return np.zeros(0, np.float32)
        # squelch
        p = float(10 * np.log10(np.mean(np.abs(y) ** 2) + 1e-20))
        self.last_power_db = p
        self._noise_hist.append(p)
        self._noise_hist = self._noise_hist[-200:]
        if self.squelch_db is None:
            self.squelch_open = True
        else:
            margin = self.squelch_db if not self.squelch_open else self.squelch_db - 3.0  # hystérésis
            if self.noise_ref_db is not None:
                self.squelch_open = p > self.noise_ref_db + margin
            else:  # repli : référence glissante (10e centile des blocs récents)
                ref = float(np.percentile(self._noise_hist, 10))
                self.squelch_open = len(self._noise_hist) >= 3 and p > ref + margin
        # discriminateur
        prev = np.concatenate([[self._last], y[:-1]])
        self._last = y[-1]
        inst = np.angle(y * np.conj(prev)) * self.ch_rate / (2 * np.pi) / self.deviation
        # rééchantillonnage linéaire à pas fractionnaire (état conservé)
        src = np.concatenate([[self._rs_prev], inst])
        pos = np.arange(self._rs_pos, len(inst), self._step)
        audio = np.interp(pos, np.arange(len(src)), src)
        self._rs_pos = (pos[-1] + self._step - len(inst)) if len(pos) else self._rs_pos - len(inst)
        self._rs_prev = inst[-1]
        if self._deemph is not None:
            a = self._deemph
            audio, self._de_zi = sps.lfilter([1 - a], [1, -a], audio, zi=self._de_zi)
        audio, self._sos_zi = sps.sosfilt(self._sos, audio, zi=self._sos_zi)
        if not self.squelch_open:
            audio = np.zeros_like(audio)
        return np.clip(audio, -1.0, 1.0).astype(np.float32)
