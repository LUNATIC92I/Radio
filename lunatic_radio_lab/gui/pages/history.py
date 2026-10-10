"""Historique des événements (base locale) avec filtres et export."""

from __future__ import annotations

import time

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import QComboBox, QDateTimeEdit, QFileDialog, QGridLayout, QGroupBox, QLabel, QMessageBox

from ... import paths
from ...reports.builder import fmt_classification, fmt_freq, fmt_ts
from ...reports.csv_export import write_events_csv
from ..widgets import Page, button, fill_table, guarded, make_table, mhz_spin, spin


class HistoryPage(Page):
    title = "Historique des événements"
    subtitle = "Toutes les détections enregistrées localement. Les données simulées sont clairement distinguées."

    def __init__(self, ctx):
        super().__init__(ctx)
        g = QGroupBox("Filtres")
        gl = QGridLayout(g)
        self.since = QDateTimeEdit(QDateTime.currentDateTime().addDays(-7))
        self.until = QDateTimeEdit(QDateTime.currentDateTime().addDays(1))
        for w in (self.since, self.until):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.fmin = mhz_spin(0.009e6)
        self.fmax = mhz_spin(300_000e6)
        self.pmin = spin(-200, -200, 50, "dBFS", 1, 5)
        self.dmin = spin(0, 0, 3600, "s", 2, 0.5)
        self.nature = QComboBox()
        self.nature.addItem("Réelles et simulées", None)
        self.nature.addItem("Mesures réelles uniquement", False)
        self.nature.addItem("Données simulées uniquement", True)
        self.channel = QComboBox()
        gl.addWidget(QLabel("Du"), 0, 0)
        gl.addWidget(self.since, 0, 1)
        gl.addWidget(QLabel("au"), 0, 2)
        gl.addWidget(self.until, 0, 3)
        gl.addWidget(QLabel("Nature"), 0, 4)
        gl.addWidget(self.nature, 0, 5)
        gl.addWidget(QLabel("Fréq. min"), 1, 0)
        gl.addWidget(self.fmin, 1, 1)
        gl.addWidget(QLabel("Fréq. max"), 1, 2)
        gl.addWidget(self.fmax, 1, 3)
        gl.addWidget(QLabel("Canal"), 1, 4)
        gl.addWidget(self.channel, 1, 5)
        gl.addWidget(QLabel("Puissance min"), 2, 0)
        gl.addWidget(self.pmin, 2, 1)
        gl.addWidget(QLabel("Durée min"), 2, 2)
        gl.addWidget(self.dmin, 2, 3)
        gl.addWidget(button("Rechercher", self.refresh, "primary"), 2, 5)
        self.root.addWidget(g)
        self.count = QLabel("—")
        self.count.setObjectName("hint")
        self.root.addWidget(self.count)
        self.table = make_table(["#", "Nature", "Début", "Fin", "Durée (s)", "Fréq. configurée", "Fréq. émission",
                                 "Canal", "Crête", "Moyenne", "SNR (dB)", "Largeur (Hz)", "Écart-type f (Hz)",
                                 "Caractérisation", "Confiance", "Récepteur"])
        self.root.addWidget(self.table, 1)
        bar = self.header_right_lay
        bar.addWidget(button("Exporter CSV…", self.export))
        bar.addWidget(button("Purger…", self.purge, "danger", "Action protégée (administrateur)"))
        ctx.history_changed.connect(self._maybe_refresh)
        ctx.channels_changed.connect(self._channels)
        self._channels()
        self.events = []

    def on_show(self) -> None:
        self.until.setDateTime(QDateTime.currentDateTime().addDays(1))
        self.refresh()

    def _maybe_refresh(self) -> None:
        if self.isVisible():
            self.refresh()

    def _channels(self) -> None:
        cur = self.channel.currentData()
        self.channel.clear()
        self.channel.addItem("Tous", None)
        for c in self.ctx.channels.list():
            self.channel.addItem(c.name, c.name)
        i = self.channel.findData(cur)
        self.channel.setCurrentIndex(max(0, i))

    def refresh(self) -> None:
        self.events = self.ctx.db.query_events(
            since=self.since.dateTime().toSecsSinceEpoch(), until=self.until.dateTime().toSecsSinceEpoch(),
            simulated=self.nature.currentData(), min_freq=self.fmin.value() * 1e6, max_freq=self.fmax.value() * 1e6,
            min_power=self.pmin.value() if self.pmin.value() > -200 else None, channel=self.channel.currentData(),
            min_duration=self.dmin.value() or None,
        )
        c = self.ctx
        fill_table(self.table, [
            (e.id, "SIMULÉ" if e.simulated else "RÉEL", fmt_ts(e.start_ts), fmt_ts(e.end_ts), round(e.duration_s, 3),
             fmt_freq(e.configured_freq_hz), fmt_freq(e.emission_freq_hz), e.channel_name or "—",
             round(c.to_display_power(e.peak_power_dbfs), 1), round(c.to_display_power(e.mean_power_dbfs), 1),
             round(e.snr_db, 1), "n/m" if e.bandwidth_hz is None else round(e.bandwidth_hz),
             round(e.freq_std_hz, 1), fmt_classification(e, with_confidence=False),
             "" if e.classification_confidence is None else f"{e.classification_confidence:.0%}", e.receiver_id)
            for e in self.events])
        n_sim = sum(e.simulated for e in self.events)
        self.count.setText(f"{len(self.events)} événement(s) : {len(self.events) - n_sim} réel(s), {n_sim} simulé(s). "
                           f"Puissances en {c.power_unit}.")

    def export(self) -> None:
        if not self.events:
            self.ctx.notify.emit("Aucun événement à exporter.", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exporter les événements",
                                              str(paths.reports_dir() / f"evenements_{int(time.time())}.csv"),
                                              "CSV (*.csv)")
        if not path:
            return
        write_events_csv(self.events, path)
        self.ctx.db.audit(self.ctx.access.actor, "history.export", {"path": path, "count": len(self.events)})
        self.ctx.notify.emit(f"{len(self.events)} événements exportés.", "ok")

    def purge(self) -> None:
        if QMessageBox.question(self, "Purger l'historique",
                                "Supprimer définitivement tous les événements antérieurs à la date « au » ?") \
                != QMessageBox.Yes:
            return
        before = self.until.dateTime().toSecsSinceEpoch()

        def _do() -> int:
            self.ctx.access.require("history.purge", {"before": before})
            return self.ctx.db.purge_events(before)

        n = guarded(self.ctx, self, _do)
        if n is not None:
            self.ctx.notify.emit(f"{n} événement(s) supprimé(s).", "ok")
            self.refresh()
