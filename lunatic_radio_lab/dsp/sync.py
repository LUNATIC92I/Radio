"""Recherche des motifs de synchronisation publics des systèmes 4FSK (diagnostic).

Les motifs de synchronisation sont des séquences FIXES et PUBLIQUES définies par les
normes ; ils ne transportent aucune information. Les repérer permet d'étayer une
hypothèse de protocole sans décoder le moindre contenu : aucune trame n'est
interprétée, aucune donnée utile n'est extraite, aucun chiffrement n'est touché.

Correspondance dibit → symbole (commune à DMR et P25 C4FM) :
    01 → +3, 00 → +1, 10 → −1, 11 → −3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

import numpy as np
from scipy import signal as sps

# Motifs de 48 bits (24 symboles)
SYNC_PATTERNS_HEX: dict[str, tuple[str, int]] = {
    # nom : (motif hexadécimal, profil associé)
    "DMR BS voix": ("755FD7DF75F7", "dmr"),
    "DMR BS données": ("DFF57D75DF5D", "dmr"),
    "DMR MS voix": ("7F7D5DD57DFD", "dmr"),
    "DMR MS données": ("D5D7F77FD757", "dmr"),
    "P25 Phase 1 FS": ("5575F5FF77FF", "p25_p1"),
}
SYNC_REFERENCES = {"dmr": "ETSI TS 102 361-1, § 9.1.1", "p25_p1": "TIA-102.BAAA, synchronisation de trame"}

_DIBIT_TO_SYMBOL = {0b01: 3, 0b00: 1, 0b10: -1, 0b11: -3}


def pattern_symbols(hex_pattern: str) -> np.ndarray:
    v = int(hex_pattern, 16)
    nbits = 4 * len(hex_pattern)
    dibits = [(v >> (nbits - 2 - 2 * i)) & 0b11 for i in range(nbits // 2)]
    return np.array([_DIBIT_TO_SYMBOL[d] for d in dibits], dtype=np.int8)


PATTERNS: dict[str, tuple[np.ndarray, str]] = {k: (pattern_symbols(h), p) for k, (h, p) in SYNC_PATTERNS_HEX.items()}


@dataclass
class SyncResult:
    symbols_examined: int = 0
    matches: dict[str, int] = field(default_factory=dict)  # motif -> occurrences
    profile_hits: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        if not self.matches:
            return f"Aucun motif de synchronisation reconnu sur {self.symbols_examined} symboles"
        parts = ", ".join(f"{k} ×{n}" for k, n in self.matches.items())
        return f"Motifs de synchronisation : {parts}"


def symbol_center_samples(inst_freq: np.ndarray, fs: float, symbol_rate: float, sps_target: int = 10) -> np.ndarray:
    """Valeurs de fréquence instantanée au centre des symboles, normalisées (niveaux nominaux ±1, ±3).

    Récupération d'horloge simple : choix de la phase d'échantillonnage qui maximise
    l'ouverture de l'œil (distance moyenne minimale aux niveaux nominaux).
    """
    if len(inst_freq) < 4 * fs / symbol_rate:
        return np.zeros(0)
    fr = Fraction(sps_target * symbol_rate / fs).limit_denominator(2000)
    x = sps.resample_poly(inst_freq - np.median(inst_freq), fr.numerator, fr.denominator)
    outer = np.percentile(np.abs(x), 90)
    if outer <= 0:
        return np.zeros(0)
    x = x / outer * 3.0
    best, best_score = 0, -np.inf
    for ph in range(sps_target):
        smp = x[ph::sps_target]
        score = -np.mean(np.min(np.abs(smp[:, None] - np.array([-3.0, -1.0, 1.0, 3.0])[None, :]), axis=1))
        if score > best_score:
            best, best_score = ph, score
    return x[best::sps_target]


def recover_symbols(inst_freq: np.ndarray, fs: float, symbol_rate: float, sps_target: int = 10) -> np.ndarray:
    """Décision ±1/±3 sur les échantillons au centre des symboles."""
    s = symbol_center_samples(inst_freq, fs, symbol_rate, sps_target)
    return np.where(s >= 2, 3, np.where(s >= 0, 1, np.where(s >= -2, -1, -3))).astype(np.int8)


def find_sync(symbols: np.ndarray, max_errors: int = 2) -> SyncResult:
    res = SyncResult(symbols_examined=int(len(symbols)))
    if len(symbols) < 24:
        return res
    win = np.lib.stride_tricks.sliding_window_view(symbols, 24)
    # Pas de recherche en polarité inversée : en DMR, les motifs « données » sont l'opposé
    # exact des motifs « voix » ; une inversion de spectre fait donc lire voix <-> données,
    # sans changer la famille identifiée.
    for name, (pat, prof) in PATTERNS.items():
        errs = np.count_nonzero(win != pat, axis=1)
        n = int(np.count_nonzero(errs <= max_errors))
        if n:
            res.matches[name] = n
            res.profile_hits[prof] = res.profile_hits.get(prof, 0) + n
    return res


def search_sync(inst_freq: np.ndarray, segments: list[tuple[int, int]], fs: float, symbol_rate: float) -> SyncResult:
    """Recherche par segment (chaque rafale TDMA a sa propre phase d'horloge)."""
    total = SyncResult()
    for s, e in segments:
        sym = recover_symbols(inst_freq[s:e], fs, symbol_rate)
        r = find_sync(sym)
        total.symbols_examined += r.symbols_examined
        for k, v in r.matches.items():
            total.matches[k] = total.matches.get(k, 0) + v
        for k, v in r.profile_hits.items():
            total.profile_hits[k] = total.profile_hits.get(k, 0) + v
    return total
