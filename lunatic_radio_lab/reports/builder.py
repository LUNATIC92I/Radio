"""Collecte des données d'un rapport d'analyse (indépendant du format de sortie)."""

from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .. import APP_NAME, __version__
from ..dsp.spectrum import dynamic_range_db
from ..models import ActivityEvent, SpectrumFrame, TestResult
from ..storage.database import Database

GENERAL_LIMITATIONS = [
    "Les puissances sont exprimées en dBFS (relatif à la pleine échelle de l'ADC) : elles dépendent du gain, "
    "de l'antenne et du câblage, et ne sont pas des puissances absolues (dBm) sans étalonnage.",
    "La puissance par case FFT dépend de la résolution (RBW) ; la puissance de canal est intégrée et corrigée "
    "de la largeur de bande équivalente de bruit de la fenêtre.",
    "Le plancher de bruit est estimé par la médiane du spectre (biais possible d'environ -1,6 dB avec peu de moyennage).",
    "La largeur de bande occupée (99 %) n'est pas mesurable en dessous d'environ 2 RBW ; elle est alors indiquée « n/m ».",
    "Un événement signale qu'une émission a dépassé le seuil ; il ne constitue pas l'identification d'un équipement.",
    "Les hypothèses de protocole reposent sur des propriétés physiques observées ; aucune trame n'est décodée. "
    "Leur niveau de confiance est plafonné en conséquence.",
    "La précision en fréquence dépend de l'oscillateur du récepteur (typiquement ±1 à ±50 ppm sans correction).",
    "Une saturation de l'ADC fausse toutes les mesures de la trame concernée (produits d'intermodulation, raies parasites).",
]


def fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def fmt_freq(hz: float | None) -> str:
    return "—" if hz is None else f"{hz / 1e6:.5f} MHz"


@dataclass
class SpectrumSnapshot:
    freqs_hz: list[float]
    power_dbfs: list[float]
    noise_floor_dbfs: float
    rbw_hz: float
    center_freq_hz: float
    sample_rate_hz: float
    simulated: bool
    saturated: bool
    timestamp: float
    max_hold: bool = False

    @classmethod
    def from_frame(cls, fr: SpectrumFrame, max_points: int = 1024, max_hold: bool = False) -> SpectrumSnapshot:
        f, p = np.asarray(fr.freqs_hz), np.asarray(fr.power_dbfs)
        if len(f) > max_points:
            step = len(f) // max_points
            n = (len(f) // step) * step
            f = f[:n].reshape(-1, step).mean(axis=1)
            p = p[:n].reshape(-1, step).max(axis=1)  # détection crête par paquet
        return cls(f.tolist(), p.tolist(), fr.noise_floor_dbfs, fr.rbw_hz, fr.center_freq_hz, fr.sample_rate_hz,
                   fr.simulated, fr.saturated, fr.timestamp, max_hold)


@dataclass
class ReportData:
    title: str
    generated_ts: float
    operator: str
    jurisdiction: str
    period: tuple[float | None, float | None]
    sessions: list[dict[str, Any]]
    devices: list[dict[str, Any]]
    ranges: list[dict[str, Any]]
    events_real: list[ActivityEvent]
    events_simulated: list[ActivityEvent]
    tests: list[TestResult]
    errors: list[dict[str, Any]]
    limitations: list[str]
    spectrum: SpectrumSnapshot | None = None
    calibration_offset_db: float | None = None
    notes: list[str] = field(default_factory=list)
    software: str = f"{APP_NAME} {__version__}"

    @property
    def contains_simulated(self) -> bool:
        return bool(self.events_simulated) or any(s["simulated"] for s in self.sessions) or (
            self.spectrum is not None and self.spectrum.simulated)

    @property
    def contains_real(self) -> bool:
        return bool(self.events_real) or any(not s["simulated"] for s in self.sessions)

    def summary_rows(self) -> list[tuple[str, str]]:
        all_ev = self.events_real + self.events_simulated
        rows = [
            ("Logiciel", self.software),
            ("Généré le", fmt_ts(self.generated_ts)),
            ("Opérateur", self.operator or "—"),
            ("Juridiction déclarée", self.jurisdiction or "non renseignée"),
            ("Période analysée", f"{fmt_ts(self.period[0])} → {fmt_ts(self.period[1])}"),
            ("Sessions de mesure", str(len(self.sessions))),
            ("Événements — mesures réelles", str(len(self.events_real))),
            ("Événements — données SIMULÉES", str(len(self.events_simulated))),
            ("Tests réussis / exécutés", f"{sum(t.passed for t in self.tests)} / {len(self.tests)}"),
            ("Erreurs enregistrées", str(len(self.errors))),
        ]
        if all_ev:
            rows.append(("Durée cumulée d'activité", f"{sum(e.duration_s for e in all_ev):.1f} s"))
        rows.append(("Unité de puissance", "dBm (étalonné, décalage {:+.1f} dB)".format(self.calibration_offset_db)
                     if self.calibration_offset_db is not None else "dBFS (relatif, non étalonné)"))
        return rows


def build_report(
    db: Database,
    since: float | None = None,
    until: float | None = None,
    include_simulated: bool = True,
    include_real: bool = True,
    spectrum: SpectrumFrame | None = None,
    spectrum_is_max_hold: bool = False,
    title: str = "Rapport d'analyse radio",
    operator: str = "",
    extra_limitations: list[str] | None = None,
) -> ReportData:
    # Sans borne supérieure explicite, tout l'historique est pris (l'horodatage des données simulées
    # en mode accéléré peut dépasser l'heure courante).
    events = db.query_events(since=since, until=until, limit=100_000)
    until_eff = until if until is not None else max([time.time()] + [e.end_ts for e in events])
    events.sort(key=lambda e: e.start_ts)
    sessions = db.list_sessions(since, until)
    if not include_simulated:
        sessions = [s for s in sessions if not s["simulated"]]
    if not include_real:
        sessions = [s for s in sessions if s["simulated"]]
    devices: dict[str, dict] = {}
    ranges = []
    lim = list(GENERAL_LIMITATIONS)
    for s in sessions:
        dev = s.get("device") or {}
        devices.setdefault(s["receiver_id"], {
            "id": s["receiver_id"], "label": s["receiver_label"], "simulated": s["simulated"],
            "manufacturer": dev.get("manufacturer", "—"), "model": dev.get("model", "—"),
            "serial": dev.get("serial", ""), "backend": dev.get("backend", "—"),
            "freq_ranges_hz": dev.get("freq_ranges_hz", []), "adc_bits": dev.get("adc_bits"),
        })
        cfg = s["config"]
        fc, fs = cfg.get("center_freq_hz", 0.0), cfg.get("sample_rate_hz", 0.0)
        ranges.append({"session": s["id"], "low_hz": fc - fs / 2, "high_hz": fc + fs / 2, "center_hz": fc,
                       "sample_rate_hz": fs, "gain_db": cfg.get("gain_db"), "simulated": s["simulated"],
                       "detection": s["detection"]})
        dr = dynamic_range_db(dev.get("adc_bits"))
        if dr:
            txt = (f"{s['receiver_label']} : ADC {dev.get('adc_bits')} bits, dynamique théorique ≈ {dr:.0f} dB "
                   "(hors gain de traitement FFT).")
            if txt not in lim:
                lim.append(txt)
    calib = db.get_setting("calibration_offset_db")
    jur = db.get_setting("jurisdiction", "")
    tests = [t for t in db.list_test_results(since) if until is None or t.timestamp <= until]
    if not include_simulated:
        tests = [t for t in tests if not t.simulated]
    return ReportData(
        title=title,
        generated_ts=time.time(),
        operator=operator or db.get_setting("operator_name", ""),
        jurisdiction=jur,
        period=(since if since is not None else (sessions[0]["start_ts"] if sessions else None), until_eff),
        sessions=sessions,
        devices=list(devices.values()),
        ranges=ranges,
        events_real=[e for e in events if not e.simulated] if include_real else [],
        events_simulated=[e for e in events if e.simulated] if include_simulated else [],
        tests=tests,
        errors=db.list_errors(since),
        limitations=lim + (extra_limitations or []),
        spectrum=SpectrumSnapshot.from_frame(spectrum, max_hold=spectrum_is_max_hold) if spectrum is not None else None,
        calibration_offset_db=calib,
    )


def fmt_classification(e: ActivityEvent, with_confidence: bool = True) -> str:
    """Caractérisation affichable d'un événement (avec confiance et alerte de superposition)."""
    txt = e.classification or "—"
    if with_confidence and e.classification and e.classification_confidence is not None:
        txt = f"{e.classification} ({e.classification_confidence:.0%})"
    if e.overlap_suspected:
        txt += " ⚠ superposition suspectée"
    return txt
