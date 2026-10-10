"""Génère l'exemple de rapport d'analyse (docs/examples/) à partir d'une session simulée."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LRL_HOME"] = tempfile.mkdtemp(prefix="lrl_example_")

from lunatic_radio_lab.cli import run_simulation  # noqa: E402
from lunatic_radio_lab.reports import build_report, write_pdf_report, write_report_csv  # noqa: E402
from lunatic_radio_lab.selftest import run_selftests  # noqa: E402
from lunatic_radio_lab.storage.database import Database  # noqa: E402


def main() -> None:
    out = ROOT / "docs" / "examples"
    out.mkdir(parents=True, exist_ok=True)
    db = Database(":memory:")
    db.set_setting("operator_name", "Technicien de démonstration")
    db.set_setting("jurisdiction", "France (exemple)")
    t0 = time.time()
    for r in run_selftests():
        db.add_test_result(r)
    eng = run_simulation("canaux_occupes", 8.0, 446.1e6, 250e3, db)
    run_simulation("intermittent", 15.0, 446.1e6, 250e3, db, import_pmr446=False)
    data = build_report(db, since=t0 - 1, spectrum=eng.max_hold, spectrum_is_max_hold=True,
                        title="Exemple de rapport d'analyse — mode laboratoire")
    pdf = write_pdf_report(data, out / "exemple_rapport.pdf")
    ev, meta = write_report_csv(data, out / "exemple_rapport.csv")
    print(pdf, ev, meta, sep="\n")


if __name__ == "__main__":
    main()
