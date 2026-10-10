"""Exports CSV (UTF-8 avec BOM pour une ouverture correcte dans les tableurs, séparateur « ; »)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..models import ActivityEvent
from .builder import ReportData, fmt_ts

EVENT_COLUMNS = [
    "id", "nature_donnees", "recepteur", "frequence_configuree_hz", "frequence_accordee_hz", "frequence_emission_hz",
    "canal", "debut", "fin", "debut_epoch", "duree_s", "puissance_crete_dbfs", "puissance_moyenne_dbfs", "snr_db",
    "largeur_bande_hz", "ecart_type_frequence_hz", "trames", "caracterisation", "confiance", "type",
    "parametres_detection",
]


def event_row(e: ActivityEvent) -> list:
    return [
        e.id, "SIMULATION" if e.simulated else "MESURE RÉELLE", e.receiver_id, f"{e.configured_freq_hz:.1f}",
        f"{e.tuned_freq_hz:.1f}", f"{e.emission_freq_hz:.1f}", e.channel_name or "", fmt_ts(e.start_ts), fmt_ts(e.end_ts),
        f"{e.start_ts:.3f}", f"{e.duration_s:.3f}", f"{e.peak_power_dbfs:.2f}", f"{e.mean_power_dbfs:.2f}",
        f"{e.snr_db:.1f}", "" if e.bandwidth_hz is None else f"{e.bandwidth_hz:.0f}", f"{e.freq_std_hz:.1f}", e.frames,
        e.classification or "", "" if e.classification_confidence is None else f"{e.classification_confidence:.2f}",
        e.kind, json.dumps(e.detection_params, ensure_ascii=False),
    ]


def write_events_csv(events: list[ActivityEvent], path: str | Path) -> Path:
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(EVENT_COLUMNS)
        for e in events:
            w.writerow(event_row(e))
    return path


def write_report_csv(data: ReportData, path: str | Path) -> tuple[Path, Path]:
    """Écrit `<nom>.csv` (événements) et `<nom>_metadonnees.csv` (section;clé;valeur)."""
    path = Path(path)
    ev_path = write_events_csv(sorted(data.events_real + data.events_simulated, key=lambda e: e.start_ts), path)
    meta_path = path.with_name(path.stem + "_metadonnees.csv")
    with open(meta_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["section", "cle", "valeur"])
        w.writerow(["rapport", "titre", data.title])
        for k, v in data.summary_rows():
            w.writerow(["resume", k, v])
        w.writerow(["resume", "contient_donnees_simulees", "oui" if data.contains_simulated else "non"])
        for d in data.devices:
            w.writerow(["equipement", d["id"], json.dumps(d, ensure_ascii=False, default=str)])
        for r in data.ranges:
            w.writerow(["plage_analysee", f"session {r['session']}",
                        f"{r['low_hz']:.0f}–{r['high_hz']:.0f} Hz ; gain {r['gain_db']} ; "
                        f"{'SIMULATION' if r['simulated'] else 'RÉEL'}"])
            w.writerow(["parametres_mesure", f"session {r['session']}", json.dumps(r["detection"], ensure_ascii=False)])
        for t in data.tests:
            w.writerow(["test", t.name, f"{'RÉUSSI' if t.passed else 'ÉCHEC'} ; {fmt_ts(t.timestamp)} ; "
                        f"{'SIMULATION' if t.simulated else 'RÉEL'} ; {json.dumps(t.details, ensure_ascii=False, default=str)}"])
        for e in data.errors:
            w.writerow(["erreur", fmt_ts(e["ts"]), f"{e['source']} : {e['message']}"])
        for i, lim in enumerate(data.limitations, 1):
            w.writerow(["limite_technique", str(i), lim])
    return ev_path, meta_path
