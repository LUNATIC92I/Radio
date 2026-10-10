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
