"""Détection d'émissions dans une trame de spectre et mesure de largeur de bande.

Méthode : seuil = plancher de bruit + marge (dB) ; regroupement des cases contiguës
au-dessus du seuil ; élargissement jusqu'à retomber près du plancher ; mesure de la
largeur de bande occupée (99 % de la puissance, méthode UIT-R SM.328) dans la zone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from ..models import Detection, SpectrumFrame
from .spectrum import from_db, to_db


@dataclass
class DetectionParams:
    threshold_db: float = 10.0  # marge au-dessus du plancher pour déclencher
    merge_gap_hz: float = 2_000.0  # trous plus petits fusionnés (ex. porteuse + bandes latérales)
    min_width_bins: int = 1
    edge_margin_db: float = 3.0  # extension des bords jusqu'à plancher + marge
    obw_fraction: float = 0.99  # largeur de bande occupée (fraction de puissance)
    dc_exclude_hz: float = 0.0  # ignorer la raie DC (récepteurs à conversion directe)
    min_bandwidth_hz: float = 0.0
    max_bandwidth_hz: float = float("inf")
    smooth_hz: float = 1_000.0  # lissage fréquentiel avant seuillage (réduit la variance du bruit)

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["max_bandwidth_hz"] == float("inf"):
            d["max_bandwidth_hz"] = None
        return d


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Intervalles [début, fin) des suites de True."""
    if not mask.any():
        return []
    m = np.concatenate([[False], mask, [False]]).astype(np.int8)
    d = np.diff(m)
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    return list(zip(starts.tolist(), ends.tolist()))


def occupied_bandwidth(p_lin: np.ndarray, bin_hz: float, fraction: float = 0.99) -> tuple[float, int, int]:
    """Largeur de bande contenant `fraction` de la puissance (exclut (1-f)/2 de chaque côté)."""
    total = float(p_lin.sum())
    if total <= 0 or len(p_lin) == 0:
        return 0.0, 0, 0
    c = np.cumsum(p_lin) / total
    tail = (1.0 - fraction) / 2.0
    lo = int(np.searchsorted(c, tail))
    hi = int(np.searchsorted(c, 1.0 - tail))
    hi = min(hi, len(p_lin) - 1)
    return (hi - lo + 1) * bin_hz, lo, hi


def detect_emissions(frame: SpectrumFrame, params: DetectionParams | None = None) -> list[Detection]:
    params = params or DetectionParams()
    p_db = np.asarray(frame.power_dbfs, dtype=np.float64)
    n = len(p_db)
    bin_hz = frame.sample_rate_hz / frame.fft_size
    floor = frame.noise_floor_dbfs
    k_s = max(1, int(round(params.smooth_hz / bin_hz)))
    if k_s > 1:
        p_s = to_db(np.convolve(from_db(p_db), np.ones(k_s) / k_s, mode="same"))
        floor_s = float(to_db(np.median(from_db(p_s))))
    else:
        p_s, floor_s = p_db, floor
    above = p_s > floor_s + params.threshold_db

    if params.dc_exclude_hz > 0:
        k = int(np.ceil(params.dc_exclude_hz / bin_hz))
        mid = n // 2
        above[max(0, mid - k) : min(n, mid + k + 1)] = False

    # Fusion des petits trous
    gap = int(round(params.merge_gap_hz / bin_hz))
    runs = _runs(above)
    merged: list[list[int]] = []
    for s, e in runs:
        if merged and s - merged[-1][1] <= gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])

    p_lin = from_db(p_db)
    out: list[Detection] = []
    for s, e in merged:
        if e - s < params.min_width_bins:
            continue
        # élargissement vers le plancher
        edge_s = floor_s + params.edge_margin_db
        while s > 0 and p_s[s - 1] > edge_s:
            s -= 1
        while e < n and p_s[e] > edge_s:
            e += 1
        seg = p_lin[s:e]
        # soustraction du bruit pour la puissance et la largeur de bande
        noise_lin = float(from_db(floor))
        seg_sig = np.maximum(seg - noise_lin, 0.0)
        if seg_sig.sum() <= 0:
            seg_sig = seg
        peak = float(p_db[s:e].max())
        centroid_idx = s + float(np.sum(np.arange(len(seg_sig)) * seg_sig) / np.sum(seg_sig))
        center = float(np.interp(centroid_idx, np.arange(n), frame.freqs_hz))
        ch_pow = float(to_db(seg_sig.sum() / frame.enbw_bins))
        noise_in_band = noise_lin * (e - s) / frame.enbw_bins
        snr = float(to_db(seg_sig.sum() / frame.enbw_bins) - to_db(noise_in_band))
        obw, lo, hi = occupied_bandwidth(seg_sig, bin_hz, params.obw_fraction)
        # Résolution : en dessous d'environ 2 RBW, la largeur n'est pas mesurable.
        bw: float | None = obw if obw > 2.0 * frame.rbw_hz else None
        if bw is not None and not (params.min_bandwidth_hz <= bw <= params.max_bandwidth_hz):
            continue
        if bw is None and params.min_bandwidth_hz > 2.0 * frame.rbw_hz:
            continue
        out.append(
            Detection(
                center_freq_hz=center,
                bandwidth_hz=bw,
                peak_dbfs=peak,
                channel_power_dbfs=ch_pow,
                snr_db=snr,
                low_hz=float(frame.freqs_hz[s + lo]) - bin_hz / 2,
                high_hz=float(frame.freqs_hz[s + hi]) + bin_hz / 2,
                timestamp=frame.timestamp,
                excess_db=float(p_s[s:e].max() - floor_s),
            )
        )
    return out


def channel_power(frame: SpectrumFrame, center_hz: float, bandwidth_hz: float) -> tuple[float, float]:
    """Puissance de canal (dBFS) et SNR (dB) dans [centre ± bw/2]."""
    f = frame.freqs_hz
    sel = (f >= center_hz - bandwidth_hz / 2) & (f <= center_hz + bandwidth_hz / 2)
    if not sel.any():
        return float("nan"), float("nan")
    p = from_db(np.asarray(frame.power_dbfs, dtype=np.float64)[sel])
    pw = float(p.sum() / frame.enbw_bins)
    noise = float(from_db(frame.noise_floor_dbfs)) * int(sel.sum()) / frame.enbw_bins
    sig = max(pw - noise, 1e-20)
    return float(to_db(pw)), float(to_db(sig) - to_db(noise))
