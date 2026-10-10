"""Caractérisation technique des signaux : hypothèses avec niveau de confiance.

Principe : chaque profil documenté (``protocols.profiles``) est confronté aux
caractéristiques observées. Chaque critère vérifié/contredit est listé comme
observation justificative. La confiance est plafonnée par profil (aucune
vérification de trame n'est faite) et réduite si le SNR est faible ou si des
mesures manquent. En dessous de 50 %, le résultat est « Non identifié ».
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from ..protocols.profiles import ProtocolProfile, all_profiles
from .features import SignalFeatures, extract_features

DECISION_THRESHOLD = 0.5


@dataclass
class Hypothesis:
    profile_id: str
    name: str
    confidence: float
    supporting: list[str] = field(default_factory=list)
    contradicting: list[str] = field(default_factory=list)
    not_measured: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Classification:
    features: SignalFeatures
    hypotheses: list[Hypothesis]
    observations: list[str]
    absolute_freq_hz: float | None
    simulated: bool

    @property
    def best(self) -> Hypothesis | None:
        return self.hypotheses[0] if self.hypotheses else None

    @property
    def verdict(self) -> str:
        b = self.best
        if b is None or b.confidence < DECISION_THRESHOLD:
            return "Non identifié (éléments techniques insuffisants)"
        return f"Compatible avec : {b.name} (confiance {b.confidence:.0%})"

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "absolute_freq_hz": self.absolute_freq_hz,
            "simulated": self.simulated,
            "observations": self.observations,
            "features": self.features.to_dict(),
            "hypotheses": [asdict(h) for h in self.hypotheses],
        }


def _fmt(v: float | None, unit: str, nd: int = 0) -> str:
    return "n/m" if v is None else f"{v:.{nd}f} {unit}"


def describe_observations(f: SignalFeatures, absolute_freq_hz: float | None) -> list[str]:
    obs = []
    if absolute_freq_hz:
        obs.append(f"Fréquence centrale mesurée : {absolute_freq_hz / 1e6:.5f} MHz")
    obs.append(f"Durée analysée : {f.duration_s:.2f} s")
    obs.append(f"Largeur de bande occupée (99 %) : {_fmt(f.obw_hz, 'Hz')}")
    obs.append(f"Rapport signal/bruit : {_fmt(f.snr_db, 'dB', 1)}")
    if f.envelope_cv is not None:
        kind = "constante" if f.envelope_cv < 0.3 else "variable"
        obs.append(f"Enveloppe {kind} (coefficient de variation {f.envelope_cv:.2f})")
    if f.amplitude_variation_db is not None:
        obs.append(f"Variation d'amplitude (fenêtres 10 ms) : {f.amplitude_variation_db:.1f} dB")
    if f.burst_count > 1:
        obs.append(
            f"Émission en rafales : {f.burst_count} rafales, durée médiane {_fmt(f.burst_mean_ms, 'ms', 1)}, "
            f"période {_fmt(f.burst_period_ms, 'ms', 1)}, rapport cyclique {f.duty_cycle:.0%}"
        )
    else:
        obs.append(f"Émission continue sur la capture (rapport cyclique {(f.duty_cycle or 0):.0%})")
    if f.freq_offset_hz is not None:
        obs.append(f"Décalage de fréquence moyen : {f.freq_offset_hz:+.0f} Hz")
    if f.freq_drift_hz_s is not None:
        obs.append(f"Dérive de fréquence : {f.freq_drift_hz_s:+.1f} Hz/s ; stabilité (écart-type 50 ms) "
                   f"{_fmt(f.freq_stability_hz, 'Hz', 1)}")
    if f.deviation_peak_hz is not None:
        obs.append(f"Excursion de fréquence : {f.deviation_rms_hz:.0f} Hz eff., {f.deviation_peak_hz:.0f} Hz crête (99e c.)")
    if f.symbol_rate_hz is not None and (f.symbol_rate_strength_db or 0) >= 12:
        obs.append(f"Raie de débit symbole à {f.symbol_rate_hz:.0f} Hz ({f.symbol_rate_strength_db:.1f} dB)")
    if f.fsk_levels:
        obs.append(f"Nombre de niveaux de fréquence observés : {f.fsk_levels}")
    if f.ctcss_hz:
        obs.append(f"Tonalité subaudible CTCSS détectée : {f.ctcss_hz:.1f} Hz (marge {f.ctcss_margin_db:.0f} dB)")
    if f.tone_hz is not None and (f.tone_purity or 0) > 0.6:
        obs.append(f"Audio démodulé dominé par une tonalité à {f.tone_hz:.0f} Hz (pureté {f.tone_purity:.0%})")
    obs.extend(f"Avertissement : {w}" for w in f.warnings)
    return obs


def _in(v: float | None, rng: tuple[float, float] | None) -> bool | None:
    if v is None or rng is None:
        return None
    return rng[0] <= v <= rng[1]


def score_profile(p: ProtocolProfile, f: SignalFeatures, absolute_freq_hz: float | None) -> Hypothesis:
    h = Hypothesis(p.id, p.name, 0.0, notes=list(p.notes))
    total = 0.0
    got = 0.0
    missing_w = 0.0
    essential_failed = False

    def crit(ok: bool | None, weight: float, label_ok: str, label_ko: str, label_missing: str,
             essential: bool = False) -> None:
        nonlocal total, got, missing_w, essential_failed
        if ok is None:
            h.not_measured.append(label_missing)
            missing_w += weight
            return
        total += weight
        if ok:
            got += weight
            h.supporting.append(label_ok)
        else:
            h.contradicting.append(label_ko + (" [critère essentiel]" if essential else ""))
            essential_failed = essential_failed or essential

    strong_sym = f.symbol_rate_strength_db is not None and f.symbol_rate_strength_db >= 12.0
    obw = f.obw_hz
    crit(_in(obw, p.obw_range_hz), 1.5,
         f"Largeur de bande {obw or 0:.0f} Hz dans la plage attendue {p.obw_range_hz[0]:.0f}–{p.obw_range_hz[1]:.0f} Hz",
         f"Largeur de bande {obw or 0:.0f} Hz hors plage {p.obw_range_hz[0]:.0f}–{p.obw_range_hz[1]:.0f} Hz",
         "largeur de bande")
    const_env = None if f.envelope_cv is None else f.envelope_cv < 0.3
    if p.modulation in ("cw", "fm", "4fsk"):
        crit(const_env, 1.5, "Enveloppe constante (modulation angulaire)", "Enveloppe variable (non attendue)",
             "enveloppe", essential=True)

    if p.modulation == "cw":
        crit(None if f.deviation_rms_hz is None else f.deviation_rms_hz < 100.0, 3.0,
             "Pas de modulation de fréquence mesurable", "Modulation de fréquence présente", "excursion",
             essential=True)
    else:
        crit(_in(f.deviation_peak_hz, p.deviation_peak_range_hz), 1.5,
             f"Excursion crête {f.deviation_peak_hz or 0:.0f} Hz compatible",
             f"Excursion crête {f.deviation_peak_hz or 0:.0f} Hz incompatible "
             f"(attendu {p.deviation_peak_range_hz[0]:.0f}–{p.deviation_peak_range_hz[1]:.0f} Hz)"
             if p.deviation_peak_range_hz else "Excursion incompatible",
             "excursion")

    if p.modulation == "fm":
        is_fsk = None if f.fsk_levels is None else (f.fsk_levels == 4 and strong_sym)
        crit(None if is_fsk is None else not is_fsk, 2.0,
             "Pas de structure de symboles numériques (pas de 4 niveaux + raie de débit)",
             "Structure numérique 4FSK observée (incompatible avec la FM analogique)", "niveaux de fréquence",
             essential=True)
        if p.test_tone_hz:
            ok = None if f.tone_purity is None else (
                f.tone_purity > 0.8 and abs((f.tone_hz or 0) - p.test_tone_hz) < 30.0)
            crit(ok, 3.0, f"Tonalité d'essai pure à {f.tone_hz or 0:.0f} Hz",
                 "Pas de tonalité d'essai pure à 1 kHz", "audio démodulé")
        else:
            ok = None if f.tone_purity is None else f.tone_purity < 0.8
            crit(ok, 0.5, "Contenu audio non réduit à une tonalité unique",
                 "Audio réduit à une tonalité unique (plutôt un signal d'essai)", "audio démodulé")
        if f.ctcss_hz:
            h.supporting.append(f"CTCSS {f.ctcss_hz:.1f} Hz (usage courant en FM analogique)")
            got += 0.5
            total += 0.5
    elif p.modulation == "4fsk":
        crit(None if f.fsk_levels is None else f.fsk_levels == 4, 2.5,
             "Quatre niveaux de fréquence distincts (4FSK)",
             f"{f.fsk_levels} niveau(x) de fréquence observé(s), 4 attendus", "niveaux de fréquence",
             essential=True)
        sr_ok = None
        if f.symbol_rate_hz is not None and p.symbol_rate_hz:
            sr_ok = strong_sym and abs(f.symbol_rate_hz - p.symbol_rate_hz) / p.symbol_rate_hz < 0.02
        crit(sr_ok, 3.0, f"Débit symbole {f.symbol_rate_hz or 0:.0f} Bd ≈ {p.symbol_rate_hz:.0f} Bd attendu",
             f"Débit symbole {f.symbol_rate_hz or 0:.0f} Bd (raie {f.symbol_rate_strength_db or 0:.0f} dB) "
             f"≠ {p.symbol_rate_hz:.0f} Bd attendu", "débit symbole", essential=True)
        if p.access == "TDMA":
            ok = None
            if f.burst_count > 1 and f.burst_period_ms:
                ok = abs(f.burst_period_ms - (p.burst_period_ms or 0)) < 5 and abs(
                    (f.burst_mean_ms or 0) - (p.burst_length_ms or 0)) < 5
            elif f.duty_cycle is not None and f.duty_cycle > 0.9:
                ok = False
            crit(ok, 2.0, f"Rafales TDMA {f.burst_mean_ms or 0:.1f} ms / {f.burst_period_ms or 0:.0f} ms",
                 "Pas de structure TDMA 30/60 ms (émission continue ou autre rythme)", "structure temporelle")
        elif p.access == "FDMA":
            ok = None if f.duty_cycle is None else (f.duty_cycle > 0.9 or f.burst_count <= 1)
            crit(ok, 1.0, "Émission continue (accès FDMA)", "Émission en rafales (non attendue en FDMA)",
                 "structure temporelle")

    if p.bands and absolute_freq_hz:
        inside = [b for b in p.bands if b.contains(absolute_freq_hz)]
        if inside:
            h.supporting.append(f"Fréquence dans une bande où cette famille est utilisée ({inside[0].jurisdiction}) "
                                "— indice faible")
            got += 0.5
            total += 0.5
        else:
            h.notes.append("Fréquence hors des bandes documentées pour ce profil (peut exister ailleurs sous licence).")
    if total <= 0:
        return h
    coverage = total / (total + missing_w)
    snr_factor = 1.0
    if f.snr_db is None:
        snr_factor = 0.6
    elif f.snr_db < 6:
        snr_factor = 0.4
    elif f.snr_db < 12:
        snr_factor = 0.75
    dur_factor = 1.0 if f.duration_s >= 0.5 else 0.7
    raw = got / total
    # une contradiction forte est éliminatoire
    if essential_failed:
        raw *= 0.4
    elif h.contradicting and raw < 0.75:
        raw *= 0.5
    h.confidence = float(np.clip(raw * coverage * snr_factor * dur_factor * p.confidence_cap, 0.0, 1.0))
    return h


def classify_features(f: SignalFeatures, absolute_freq_hz: float | None = None, simulated: bool = False) -> Classification:
    hyps = [score_profile(p, f, absolute_freq_hz) for p in all_profiles()]
    hyps.sort(key=lambda h: h.confidence, reverse=True)
    obs = describe_observations(f, absolute_freq_hz)
    if simulated:
        obs.insert(0, "DONNÉES SIMULÉES — résultat issu du mode laboratoire")
    best = hyps[0] if hyps else None
    if best and best.confidence >= DECISION_THRESHOLD:
        close = [h for h in hyps[1:] if best.confidence - h.confidence < 0.1 and h.confidence >= 0.3]
        if close:
            obs.append("Ambiguïté : hypothèses proches — " + ", ".join(f"{h.name} ({h.confidence:.0%})" for h in close))
    return Classification(f, hyps, obs, absolute_freq_hz, simulated)


def classify_iq(
    iq: np.ndarray,
    sample_rate: float,
    offset_hz: float,
    center_freq_hz: float | None = None,
    analysis_bw_hz: float = 12_500.0,
    simulated: bool = False,
) -> Classification:
    f = extract_features(iq, sample_rate, offset_hz, analysis_bw_hz)
    absf = center_freq_hz + offset_hz if center_freq_hz is not None else None
    return classify_features(f, absf, simulated)
