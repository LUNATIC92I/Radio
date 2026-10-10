"""Point d'entrée : interface graphique par défaut, sous-commandes en ligne de commande."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import APP_NAME, __version__, paths


def _db():
    from .storage.database import Database

    return Database(paths.database_path())


def cmd_devices(args: argparse.Namespace) -> int:
    from .drivers.registry import backend_status, discover_devices

    print("Pilotes :", ", ".join(f"{k}={'oui' if v else 'non'}" for k, v in backend_status().items()))
    for d in discover_devices(include_simulation=True, allow_network=args.network):
        print(f"- {d.label} [{d.backend}] — {d.status_text}")
        print(f"    fabricant : {d.manufacturer} ; modèle : {d.model} ; série : {d.serial or '—'}")
        print(f"    plage : {d.frequency_summary()} ; gain : {d.gain_range_db[0]:.0f}–{d.gain_range_db[1]:.0f} dB")
        if d.tx_declared:
            print("    capacité d'émission déclarée par le matériel : NON UTILISÉE (réception seule)")
        for n in d.notes:
            print(f"    note : {n}")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    from .selftest import run_selftests

    db = _db()
    ok = True
    for r in run_selftests():
        db.add_test_result(r)
        ok &= r.passed
        print(f"[{'OK ' if r.passed else 'ÉCHEC'}] {r.name} — {json.dumps(r.details, ensure_ascii=False, default=str)}")
    return 0 if ok else 1


def run_simulation(scenario: str, seconds: float, center_hz: float, sample_rate: float, db, fft_size: int = 4096,
                   import_pmr446: bool = True):
    """Exécute un scénario du mode laboratoire en accéléré (pas d'attente temps réel)."""
    from .channels import ChannelManager
    from .dsp.activity import ActivityParams
    from .dsp.synth import preset_scenarios
    from .drivers.simulated import SimulatedReceiver
    from .engine import AcquisitionEngine
    from .models import ReceiverConfig
    from .security.access import AccessController

    presets = preset_scenarios()
    if scenario not in presets:
        raise SystemExit(f"Scénario inconnu : {scenario} ({', '.join(presets)})")
    access = AccessController(db)
    chm = ChannelManager(db, access)
    windows = chm.windows()
    if import_pmr446 and not windows:
        # canaux de démonstration : l'import PMR446 exige un déverrouillage administrateur temporaire
        with access.elevated("CLI : import du plan PMR446 de démonstration"):
            chm.import_pmr446()
        windows = chm.windows()
    rx = SimulatedReceiver(presets[scenario], realtime=False)
    rx.open()
    rx.configure(ReceiverConfig(center_hz, sample_rate, 30.0))
    eng = AcquisitionEngine(rx, db, fft_size, ActivityParams(channels=windows), scenario_name=presets[scenario].name)
    eng.begin_session()
    n_blocks = int(seconds * sample_rate / eng.block_size)
    for _ in range(max(1, n_blocks)):
        eng.process_block(rx.read(eng.block_size))
    eng.end_session()
    rx.close()
    return eng


def cmd_simulate(args: argparse.Namespace) -> int:
    from .reports import build_report, write_pdf_report, write_report_csv

    db = _db()
    t0 = time.time()
    eng = run_simulation(args.scenario, args.seconds, args.center * 1e6, args.rate * 1e3, db)
    print(f"Simulation « {args.scenario} » : {eng.frames} trames, {eng.events_total} événements (DONNÉES SIMULÉES)")
    if args.report:
        data = build_report(db, since=t0 - 1, spectrum=eng.max_hold, spectrum_is_max_hold=True, title=f"Rapport — scénario {args.scenario}")
        pdf = write_pdf_report(data, args.report)
        ev, meta = write_report_csv(data, Path(args.report).with_suffix(".csv"))
        print(f"Rapport : {pdf}\nCSV : {ev}\nMétadonnées : {meta}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .reports import build_report, write_pdf_report, write_report_csv

    db = _db()
    since = time.time() - args.hours * 3600 if args.hours else None
    data = build_report(db, since=since, include_simulated=not args.real_only)
    out = Path(args.output)
    write_pdf_report(data, out)
    write_report_csv(data, out.with_suffix(".csv"))
    print(f"Rapport écrit : {out}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui.app import run_gui

    return run_gui(sys.argv[:1])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="lunatic-radio-lab", description=f"{APP_NAME} {__version__} — réception seule")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="Interface graphique (par défaut)")
    d = sub.add_parser("devices", help="Lister les récepteurs détectés")
    d.add_argument("--network", action="store_true", help="Inclure les récepteurs réseau (désactivé par défaut)")
    sub.add_parser("selftest", help="Autotests de la chaîne de mesure")
    s = sub.add_parser("simulate", help="Exécuter un scénario du mode laboratoire (accéléré)")
    s.add_argument("--scenario", default="intermittent")
    s.add_argument("--seconds", type=float, default=20.0)
    s.add_argument("--center", type=float, default=446.1, help="Fréquence centrale (MHz)")
    s.add_argument("--rate", type=float, default=250.0, help="Échantillonnage (kS/s)")
    s.add_argument("--report", help="Chemin du rapport PDF à produire")
    r = sub.add_parser("report", help="Générer un rapport PDF + CSV depuis l'historique")
    r.add_argument("output")
    r.add_argument("--hours", type=float, default=None)
    r.add_argument("--real-only", action="store_true", help="Exclure les données simulées")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers = {"devices": cmd_devices, "selftest": cmd_selftest, "simulate": cmd_simulate, "report": cmd_report,
                "gui": cmd_gui, None: cmd_gui}
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
