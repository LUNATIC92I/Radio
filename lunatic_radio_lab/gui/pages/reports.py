"""Rapports et exportations (PDF + CSV)."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QDateTime, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QDateTimeEdit, QFormLayout, QGroupBox, QHBoxLayout, QLineEdit, QListWidget, QProgressBar, QVBoxLayout,
)

from ... import paths
from ...reports import build_report, write_pdf_report, write_report_csv
from ...reports.builder import fmt_ts
from ..widgets import Page, button, error_box, fill_table, make_table
from .devices import run_in_thread


class ReportsPage(Page):
    title = "Rapports et exportations"
    subtitle = ("Rapports PDF et CSV : équipements, paramètres, plages, événements horodatés, puissances, "
                "graphiques, tests, erreurs et limites techniques. Mesures réelles et données simulées séparées.")

    def __init__(self, ctx):
        super().__init__(ctx)
        top = QHBoxLayout()
        g = QGroupBox("Contenu du rapport")
        f = QFormLayout(g)
        self.title_edit = QLineEdit("Rapport d'analyse radio")
        self.since = QDateTimeEdit(QDateTime.currentDateTime().addDays(-1))
        self.until = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        for w in (self.since, self.until):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.real = QCheckBox("Inclure les mesures réelles")
        self.real.setChecked(True)
        self.sim = QCheckBox("Inclure les données simulées")
        self.sim.setChecked(True)
        self.spec = QCheckBox("Joindre le spectre de la session (max-hold) s'il est disponible")
        self.spec.setChecked(True)
        f.addRow("Titre", self.title_edit)
        f.addRow("Du", self.since)
        f.addRow("Au", self.until)
        f.addRow("", self.real)
        f.addRow("", self.sim)
        f.addRow("", self.spec)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        f.addRow(self.bar)
        row = QHBoxLayout()
        row.addWidget(button("Générer PDF + CSV", self.generate, "primary"))
        row.addWidget(button("Ouvrir le dossier", self.open_dir))
        f.addRow(row)
        top.addWidget(g, 1)
        g2 = QGroupBox("Rapports générés")
        l2 = QVBoxLayout(g2)
        self.files = QListWidget()
        self.files.itemDoubleClicked.connect(lambda it: QDesktopServices.openUrl(QUrl.fromLocalFile(it.text())))
        l2.addWidget(self.files)
        top.addWidget(g2, 1)
        self.root.addLayout(top)
        g3 = QGroupBox("Résultats des tests enregistrés")
        l3 = QVBoxLayout(g3)
        self.tests = make_table(["Date", "Test", "Résultat", "Nature", "Récepteur"])
        l3.addWidget(self.tests)
        self.root.addWidget(g3, 1)
        self._th = None
        self._list()

    def on_show(self) -> None:
        self.until.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        self._list()

    def _list(self) -> None:
        self.files.clear()
        for p in sorted(paths.reports_dir().glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
            self.files.addItem(str(p))
        tests = self.ctx.db.list_test_results()[-200:]
        fill_table(self.tests, [(fmt_ts(t.timestamp), t.name, "RÉUSSI" if t.passed else "ÉCHEC",
                                 "SIMULATION" if t.simulated else "RÉEL", t.receiver_id) for t in reversed(tests)])

    def open_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.reports_dir())))

    def generate(self) -> None:
        if not (self.real.isChecked() or self.sim.isChecked()):
            error_box(self, "Rapport", "Sélectionnez au moins une nature de données.")
            return
        spectrum = None
        if self.spec.isChecked() and self.ctx.engine is not None:
            spectrum = self.ctx.engine.max_hold or self.ctx.engine.last_frame
        since = self.since.dateTime().toSecsSinceEpoch()
        until = self.until.dateTime().toSecsSinceEpoch()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        out = paths.reports_dir() / f"rapport_{stamp}.pdf"
        title = self.title_edit.text() or "Rapport d'analyse radio"
        db = self.ctx.db
        incl_sim, incl_real = self.sim.isChecked(), self.real.isChecked()
        is_mh = spectrum is not None and self.ctx.engine is not None and spectrum is self.ctx.engine.max_hold

        def work() -> tuple[Path, Path, Path]:
            data = build_report(db, since, until, include_simulated=incl_sim, include_real=incl_real,
                                spectrum=spectrum, spectrum_is_max_hold=is_mh, title=title)
            pdf = write_pdf_report(data, out)
            ev, meta = write_report_csv(data, out.with_suffix(".csv"))
            return pdf, ev, meta

        self.bar.setRange(0, 0)
        self._th = run_in_thread(self, work, self._done)

    def _done(self, res) -> None:  # noqa: ANN001
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        if isinstance(res, Exception):
            self.ctx.db.log_error("rapport", str(res))
            error_box(self, "Échec de la génération du rapport", res)
            return
        pdf, ev, meta = res
        self.ctx.db.audit(self.ctx.access.actor, "report.generate", {"pdf": str(pdf), "csv": str(ev)})
        self.ctx.notify.emit(f"Rapport généré : {pdf.name} (+ CSV)", "ok")
        self._list()
