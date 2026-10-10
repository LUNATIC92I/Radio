"""Extraction de caractéristiques physiques observables d'une émission.

Chaque mesure est accompagnée, si nécessaire, d'une indication de validité : une
grandeur non mesurable (durée trop courte, SNR insuffisant…) vaut ``None``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from scipy import signal as sps

from .demod import channelize, instantaneous_frequency, resample
from .detection import occupied_bandwidth
from .sync import search_sync, symbol_center_samples
from .spectrum import estimate_noise_floor_db, freq_axis, from_db, to_db, welch_psd

# Tonalités CTCSS normalisées (EIA/TIA-603), en Hz
CTCSS_TONES = [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8, 97.4, 100.0, 103.5, 107.2,
    110.9, 114.8, 118.8, 123.0, 127.3, 131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2,
    165.5, 167.9, 171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5, 203.5,
    206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1,
]


@dataclass
class SignalFeatures:
    duration_s: float
    analysis_rate_hz: float
    center_offset_hz: float
    snr_db: float | None = None
    obw_hz: float | None = None
    envelope_cv: float | None = None
    amplitude_variation_db: float | None = None
    duty_cycle: float | None = None
    burst_count: int = 0
    burst_mean_ms: float | None = None
    burst_period_ms: float | None = None
    freq_offset_hz: float | None = None
    freq_drift_hz_s: float | None = None
    freq_stability_hz: float | None = None
    deviation_rms_hz: float | None = None
    deviation_peak_hz: float | None = None
    symbol_rate_hz: float | None = None
    symbol_rate_strength_db: float | None = None
    fsk_levels: int | None = None
    ctcss_hz: float | None = None
    ctcss_margin_db: float | None = None
    tone_hz: float | None = None
    tone_purity: float | None = None
    voice_band_ratio: float | None = None
    overlap_fraction: float | None = None  # part des fenêtres de 20 ms à enveloppe perturbée
    overlap_suspected: bool = False
    sync_symbols: int = 0
    sync_matches: dict[str, int] = field(default_factory=dict)
    sync_profile_hits: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    if n <= 1 or len(x) < n:
        return x
    return np.convolve(x, np.ones(n) / n, mode="same")


def _on_mask(env: np.ndarray, fs: float) -> tuple[np.ndarray, bool]:
    """Masque « émission présente » à partir de l'enveloppe ; (masque, est_en_rafales)."""
    e_db = 20 * np.log10(np.maximum(_smooth(env, max(1, int(fs * 0.001))), 1e-12))
    hi, lo = np.percentile(e_db, 95), np.percentile(e_db, 5)
    if hi - lo < 10.0:
        return np.ones(len(env), dtype=bool), False
    thr = lo + 0.5 * (hi - lo)
    return e_db > thr, True


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    m = np.concatenate([[0], mask.astype(np.int8), [0]])
    d = np.diff(m)
    return list(zip(np.flatnonzero(d == 1).tolist(), np.flatnonzero(d == -1).tolist()))


def _count_levels(values: np.ndarray) -> int | None:
    if len(values) < 500:
        return None
    lim = np.percentile(np.abs(values), 99.5) * 1.25
    if lim <= 0:
        return None
    hist, _ = np.histogram(values, bins=64, range=(-lim, lim))
    h = _smooth(hist.astype(float), 3)
    peaks, _ = sps.find_peaks(h, height=0.2 * h.max(), prominence=0.12 * h.max(), distance=4)
    return int(len(peaks))


def _symbol_rate(inst: np.ndarray, segments: list[tuple[int, int]], fs: float) -> tuple[float | None, float | None]:
    """Débit symbole : raie spectrale de |d f/dt|² entre 1 et 10 kBd."""
    nper = 512
    acc = None
    count = 0
    for s, e in segments:
        seg = inst[s:e]
        if len(seg) < nper + 2:
            continue
        x = np.diff(seg) ** 2
        f, p = sps.welch(x - x.mean(), fs=fs, nperseg=nper, noverlap=nper // 2)
        acc = p if acc is None else acc + p
        count += 1
    if acc is None:
        return None, None
    sel = (f >= 1_000) & (f <= min(10_000, 0.45 * fs))
    if not sel.any():
        return None, None
    ps, fsel = acc[sel], f[sel]
    k = int(np.argmax(ps))
    strength = float(10 * np.log10(ps[k] / max(np.median(ps), 1e-30)))
    # interpolation parabolique de la raie
    rate = float(fsel[k])
    if 0 < k < len(ps) - 1:
        a, b, c = np.log(ps[k - 1] + 1e-30), np.log(ps[k] + 1e-30), np.log(ps[k + 1] + 1e-30)
        den = a - 2 * b + c
        if den != 0:
            rate += 0.5 * (a - c) / den * (fsel[1] - fsel[0])
    return rate, strength


def _goertzel_power(x: np.ndarray, fs: float, freqs: list[float]) -> np.ndarray:
    n = np.arange(len(x))
    w = np.hanning(len(x))
    return np.array([np.abs(np.sum(x * w * np.exp(-2j * np.pi * f * n / fs))) ** 2 for f in freqs])


def extract_features(
    iq: np.ndarray,
    sample_rate: float,
    offset_hz: float = 0.0,
    analysis_bw_hz: float = 12_500.0,
) -> SignalFeatures:
    """Analyse l'émission située à `offset_hz` du centre de la capture IQ."""
    iq = np.asarray(iq).astype(np.complex64)
    feats = SignalFeatures(duration_s=len(iq) / sample_rate, analysis_rate_hz=0.0, center_offset_hz=offset_hz)
    if feats.duration_s < 0.05:
        feats.warnings.append("Capture trop courte (< 50 ms) : caractérisation impossible.")
        return feats

    # --- SNR et largeur de bande sur la capture complète
    nfft = 4096 if sample_rate >= 100_000 else 1024
    p_lin, _, wi = welch_psd(iq, nfft)
    fr = freq_axis(nfft, sample_rate)
    p_db = to_db(p_lin)
    floor_db = estimate_noise_floor_db(p_db)
    sel = np.abs(fr - offset_hz) <= analysis_bw_hz / 2
    noise_lin = float(from_db(floor_db))
    sig = np.maximum(p_lin[sel] - noise_lin, 0.0)
    if sig.sum() > 0:
        obw, _, _ = occupied_bandwidth(sig, sample_rate / nfft, 0.99)
        feats.obw_hz = float(obw)
    # --- canalisation
    x, fs = channelize(iq, sample_rate, offset_hz, analysis_bw_hz, min_rate=24_000.0)
    feats.analysis_rate_hz = fs
    env = np.abs(x)
    mask, bursty = _on_mask(env, fs)
    duty = float(mask.mean())
    feats.duty_cycle = duty
    segs = [(s, e) for s, e in _runs(mask) if (e - s) / fs >= 0.005]
    feats.burst_count = len(segs) if bursty else (1 if duty > 0 else 0)
    if bursty and segs:
        lens = np.array([(e - s) / fs for s, e in segs])
        feats.burst_mean_ms = float(np.median(lens) * 1000)
        if len(segs) >= 3:
            starts = np.array([s for s, _ in segs]) / fs
            feats.burst_period_ms = float(np.median(np.diff(starts)) * 1000)
    if sig.sum() > 0:
        band_sig = float(sig.sum())
        band_noise = noise_lin * int(sel.sum())
        snr = 10 * np.log10(max(band_sig, 1e-30) / max(band_noise, 1e-30))
        if bursty and duty > 0:
            snr -= 10 * np.log10(duty)  # SNR pendant les rafales
        feats.snr_db = float(snr)
        if bursty and duty > 0:
            feats.warnings.append("SNR estimé pendant les rafales (corrigé du rapport cyclique).")

    on = env[mask]
    if len(on) > 10 and on.mean() > 0:
        feats.envelope_cv = float(on.std() / on.mean())
        win = max(1, int(0.010 * fs))
        nblk = len(on) // win
        if nblk >= 3:
            b = 20 * np.log10(on[: nblk * win].reshape(nblk, win).mean(axis=1) + 1e-12)
            feats.amplitude_variation_db = float(b.max() - b.min())

    if feats.snr_db is not None and feats.snr_db < 6.0:
        feats.warnings.append("SNR < 6 dB : mesures de modulation peu fiables.")

    # --- fréquence instantanée
    inst = instantaneous_frequency(x, fs)
    m_stat = mask.copy()
    if bursty:
        # on écarte 1,5 ms aux bords des rafales (transitoires de montée/descente)
        g = int(0.0015 * fs)
        m_stat[:] = False
        for s, e in segs:
            if e - s > 2 * g + 4:
                m_stat[s + g : e - g] = True
    m_inst = m_stat[1:]

    # --- superposition d'émissions : enveloppe localement perturbée alors qu'elle est
    # constante ailleurs (une modulation angulaire seule a une enveloppe constante)
    on_c = env[m_stat]
    w20 = int(0.020 * fs)
    nw = len(on_c) // w20 if w20 else 0
    if nw >= 5 and feats.snr_db is not None:
        blk = on_c[: nw * w20].reshape(nw, w20)
        cv = blk.std(axis=1) / np.maximum(blk.mean(axis=1), 1e-12)
        feats.overlap_fraction = float(np.mean(cv > 0.25))
        if feats.snr_db >= 15.0 and feats.overlap_fraction >= 0.1 and float(np.min(cv)) < 0.12:
            feats.overlap_suspected = True
            feats.warnings.append(
                f"Enveloppe perturbée sur {feats.overlap_fraction:.0%} de la capture alors qu'elle est constante "
                "ailleurs : superposition probable de plusieurs émissions (collision) ou trajets multiples.")
    lp = sps.butter(4, min(3_000.0, 0.45 * fs), fs=fs, output="sos")
    inst_lp = sps.sosfiltfilt(lp, inst) if len(inst) > 30 else inst
    vals = inst_lp[m_inst]
    if len(vals) > 100:
        mean_f = float(np.mean(vals))
        feats.freq_offset_hz = mean_f
        t = np.flatnonzero(m_inst) / fs
        if t[-1] - t[0] > 0.2:
            slope = np.polyfit(t, vals, 1)[0]
            feats.freq_drift_hz_s = float(slope)
            w = int(0.05 * fs)
            means = [float(np.mean(vals[i : i + w])) for i in range(0, len(vals) - w, w)]
            if len(means) >= 3:
                feats.freq_stability_hz = float(np.std(means))
        dev = vals - mean_f
        feats.deviation_rms_hz = float(np.sqrt(np.mean(dev**2)))
        feats.deviation_peak_hz = float(np.percentile(np.abs(dev), 99))
        feats.fsk_levels = _count_levels(dev)

    # débit symbole
    seg_inst = [(s, min(e, len(inst))) for s, e in (segs if bursty else [(0, len(inst))])]
    inst_sr = sps.sosfiltfilt(sps.butter(4, min(8_000.0, 0.45 * fs), fs=fs, output="sos"), inst) if len(inst) > 30 else inst
    rate, strength = _symbol_rate(inst_sr, seg_inst, fs)
    feats.symbol_rate_hz = float(rate) if rate is not None else None
    feats.symbol_rate_strength_db = float(strength) if strength is not None else None

    # Niveaux comptés au centre des symboles quand une raie de débit symbole existe
    # (plus robuste que l'histogramme brut, faussé par les suites de symboles identiques).
    if rate is not None and (strength or 0) >= 12.0 and len(vals) > 100:
        g = int(0.0015 * fs)
        centers = [symbol_center_samples(inst_lp[s + g : min(e, len(inst_lp)) - g], fs, rate)
                   for s, e in seg_inst if e - s > 2 * g + 50]
        centers = [c for c in centers if len(c)]
        if centers:
            lv = _count_levels(np.concatenate(centers))
            if lv is not None:
                feats.fsk_levels = lv

    # --- motifs de synchronisation publics (4FSK 4800 Bd uniquement ; aucun décodage)
    if (feats.fsk_levels == 4 and rate is not None and (strength or 0) >= 12.0
            and abs(rate - 4_800.0) / 4_800.0 < 0.02):
        g = int(0.0015 * fs)
        sync_segs = [(s + g, min(e, len(inst_lp)) - g) for s, e in seg_inst if e - s > 2 * g + 50]
        sr = search_sync(inst_lp, sync_segs, fs, rate)
        feats.sync_symbols = sr.symbols_examined
        feats.sync_matches = sr.matches
        feats.sync_profile_hits = sr.profile_hits

    # --- analyse audio (après démodulation FM)
    if len(vals) > 100:
        audio_fs = 8_000.0
        demod = np.where(m_inst, inst - (feats.freq_offset_hz or 0.0), 0.0)
        audio = resample(demod, fs, audio_fs)
        if len(audio) >= int(0.4 * audio_fs):
            # CTCSS : passe-bas 300 Hz puis décimation à 1 kHz
            sos = sps.butter(6, 280.0, fs=audio_fs, output="sos")
            sub = sps.sosfiltfilt(sos, audio)[:: 8]
            sub_fs = audio_fs / 8
            pw = _goertzel_power(sub - sub.mean(), sub_fs, CTCSS_TONES)
            k = int(np.argmax(pw))
            others = np.delete(pw, [i for i in range(max(0, k - 1), min(len(pw), k + 2))])
            margin = float(10 * np.log10(pw[k] / max(np.median(others), 1e-30)))
            if margin >= 15.0 and feats.duration_s >= 0.4:
                feats.ctcss_hz, feats.ctcss_margin_db = CTCSS_TONES[k], margin
            # tonalité / voix dans 300–3400 Hz
            sos_b = sps.butter(4, [300.0, 3_400.0], btype="bandpass", fs=audio_fs, output="sos")
            ab = sps.sosfiltfilt(sos_b, audio)
            f_a, p_a = sps.welch(ab, fs=audio_fs, nperseg=min(2048, len(ab)))
            tot = float(p_a.sum())
            if tot > 0:
                ka = int(np.argmax(p_a))
                df = f_a[1] - f_a[0]
                around = (np.abs(f_a - f_a[ka]) <= max(25.0, 2 * df))
                feats.tone_hz = float(f_a[ka])
                feats.tone_purity = float(p_a[around].sum() / tot)
                full = float(np.sum(sps.welch(audio, fs=audio_fs, nperseg=min(2048, len(audio)))[1]))
                feats.voice_band_ratio = float(tot / full) if full > 0 else None
    return feats
