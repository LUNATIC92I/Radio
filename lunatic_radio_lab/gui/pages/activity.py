"""Détection d'activité radio : seuils, filtres, événements en cours et clos."""

from __future__ import annotations

import time

from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget,
)

from ...dsp.activity import ActivityParams
from ...reports.builder import fmt_freq, fmt_ts
from ..widgets import Page, button, fill_table, make_table, spin


class ActivityPage(Page):
    title = "Détection d'activité"
    subtitle = ("Périodes où une émission dépasse le seuil configuré. Une détection n'est PAS l'identification "
                "d'un talkie-walkie : la caractérisation éventuelle est indiquée avec son niveau de confiance.")

    def __init__(self, ctx):
        super().__init__(ctx)
        self.btn = button("▶  Démarrer", self.toggle, "primary")
        self.header_right_lay.addWidget(self.btn)
        top = QHBoxLayout()
        g = QGroupBox("Seuils et filtres anti-fausses alertes")
        f = QFormLayout(g)
        p = ctx.activity_params
        self.open_thr = spin(p.open_threshold_db, 3, 60, "dB", 1, 0.5)
        self.open_thr.setToolTip("Dépassement du plancher de bruit nécessaire pour ouvrir un événement")
        self.hyst = spin(p.hysteresis_db, 0, 30, "dB", 1, 0.5)
        self.hyst.setToolTip("Hystérésis : l'événement reste ouvert tant que le niveau dépasse (seuil − hystérésis)")
        self.persist = QSpinBox()
        self.persist.setRange(1, 50)
        self.persist.setValue(p.persistence_frames)
        self.persist.setToolTip("Nombre de trames consécutives au-dessus du seuil avant confirmation")
        self.min_dur = spin(p.min_duration_s, 0, 60, "s", 2, 0.05)
        self.hang = spin(p.hang_time_s, 0, 10, "s", 2, 0.05)
        self.hang.setToolTip("Temps de maintien : tolère des coupures brèves (alternat, évanouissements)")
        self.tol = spin(p.freq_tolerance_hz / 1e3, 0.1, 100, "kHz", 2, 0.5)
        self.min_bw = spin(p.min_bandwidth_hz / 1e3, 0, 1000, "kHz", 2, 0.5)
        self.max_bw = spin(0 if p.max_bandwidth_hz == float("inf") else p.max_bandwidth_hz / 1e3, 0, 10_000,
                           "kHz (0 = illimité)", 2, 1)
        self.dc = spin(p.dc_exclude_hz / 1e3, 0, 100, "kHz", 2, 0.5)
        self.dc.setToolTip("Ignore la raie DC des récepteurs à conversion directe")
        self.chan_only = QCheckBox("Uniquement dans les canaux autorisés")
        self.chan_only.setChecked(p.channels_only)
        f.addRow("Seuil d'ouverture", self.open_thr)
        f.addRow("Hystérésis", self.hyst)
        f.addRow("Persistance", self.persist)
        f.addRow("Durée minimale", self.min_dur)
        f.addRow("Temps de maintien", self.hang)
        f.addRow("Tolérance de fréquence", self.tol)
        f.addRow("Largeur minimale", self.min_bw)
        f.addRow("Largeur maximale", self.max_bw)
        f.addRow("Exclusion DC", self.dc)
        f.addRow("", self.chan_only)
        f.addRow(button("Appliquer les paramètres", self.apply, "primary"))
        top.addWidget(g, 1)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        g2 = QGroupBox("Émissions en cours")
        l2 = QVBoxLayout(g2)
        self.open_table = make_table(["Fréquence", "Depuis", "Durée", "Canal", "Confirmée"])
        l2.addWidget(self.open_table)
        self.stats = QLabel("—")
        self.stats.setObjectName("hint")
        l2.addWidget(self.stats)
        rl.addWidget(g2)
        top.addWidget(right, 2)
        self.root.addLayout(top, 2)
        g3 = QGroupBox("Événements de la session")
        l3 = QVBoxLayout(g3)
        self.ev_table = make_table(["#", "Début", "Fin", "Durée (s)", "Fréq. configurée", "Fréq. émission", "Canal",
                                    "Crête", "Moyenne", "SNR", "Largeur", "Récepteur", "Caractérisation", "Nature"])
        l3.addWidget(self.ev_table)
        self.root.addWidget(g3, 3)
        ctx.events_closed.connect(lambda _: self._refresh_events())
        ctx.frame.connect(self._frame)
        ctx.acquisition_changed.connect(self._acq)
        self._last = 0.0

    def toggle(self) -> None:
        if self.ctx.running:
            self.ctx.stop_acquisition()
        else:
            self.ctx.start_acquisition()

    def _acq(self, running: bool) -> None:
        self.btn.setText("■  Arrêter" if running else "▶  Démarrer")
        self._refresh_events()

    def apply(self) -> None:
        p = ActivityParams(
            open_threshold_db=self.open_thr.value(), hysteresis_db=self.hyst.value(),
            persistence_frames=self.persist.value(), min_duration_s=self.min_dur.value(),
            hang_time_s=self.hang.value(), freq_tolerance_hz=self.tol.value() * 1e3,
            min_bandwidth_hz=self.min_bw.value() * 1e3,
            max_bandwidth_hz=self.max_bw.value() * 1e3 if self.max_bw.value() > 0 else float("inf"),
            dc_exclude_hz=self.dc.value() * 1e3, channels_only=self.chan_only.isChecked(),
        )
        if p.channels_only and not self.ctx.channels.list():
            self.ctx.notify.emit("Aucun canal autorisé défini : le filtre de canaux bloquera toute détection.", "warn")
        self.ctx.save_activity_params(p)

    def _frame(self, fr, dets) -> None:
        now = time.monotonic()
        if not self.isVisible() or now - self._last < 0.25 or self.ctx.engine is None:
            return
        self._last = now
        det = self.ctx.engine.detector
        rows = []
        for t in det.tracks_snapshot():
            rows.append((fmt_freq(t.freq), fmt_ts(t.start_ts), f"{t.last_ts - t.start_ts:.1f} s",
                         t.channel.name if t.channel else "—", "oui" if t.active else "candidat"))
        fill_table(self.open_table, rows)
        self.stats.setText(f"Candidats rejetés (persistance/durée insuffisante) : {det.false_alarm_rejected} · "
                           f"événements clos : {self.ctx.engine.events_total} · plancher {fr.noise_floor_dbfs:.1f} dBFS")

    def _refresh_events(self) -> None:
        evs = list(reversed(self.ctx.session_events[-500:]))
        c = self.ctx
        fill_table(self.ev_table, [
            (e.id, fmt_ts(e.start_ts), fmt_ts(e.end_ts), round(e.duration_s, 2), fmt_freq(e.configured_freq_hz),
             fmt_freq(e.emission_freq_hz), e.channel_name or "—", f"{c.to_display_power(e.peak_power_dbfs):.1f}",
             f"{c.to_display_power(e.mean_power_dbfs):.1f}", f"{e.snr_db:.1f} dB",
             "n/m" if e.bandwidth_hz is None else f"{e.bandwidth_hz:.0f} Hz", e.receiver_id,
             f"{e.classification} ({e.classification_confidence:.0%})" if e.classification and e.classification_confidence is not None else "—",
             "SIMULÉ" if e.simulated else "RÉEL") for e in evs])
