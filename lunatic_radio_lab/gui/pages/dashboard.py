"""Tableau de bord."""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGridLayout, QGroupBox, QHBoxLayout, QLabel, QVBoxLayout

from ...reports.builder import fmt_classification, fmt_freq, fmt_ts
from ...selftest import run_selftests
from ..plots import SpectrumPlot
from ..widgets import Card, Page, button, fill_table, make_table


class DashboardPage(Page):
    title = "Tableau de bord"
    subtitle = "État du récepteur, activité récente et accès rapide. Logiciel en réception seule."

    def __init__(self, ctx):
        super().__init__(ctx)
        self.btn_start = button("▶  Démarrer l'acquisition", self.toggle, "primary")
        self.header_right_lay.addWidget(button("Autotest", self.selftest, tooltip="Vérifie la chaîne de mesure"))
        self.header_right_lay.addWidget(self.btn_start)
        grid = QGridLayout()
        self.c_rx = Card("Récepteur", "—")
        self.c_mode = Card("Nature des données", "—")
        self.c_freq = Card("Fréquence centrale", "—")
        self.c_floor = Card("Plancher de bruit", "—", "par case FFT")
        self.c_events = Card("Événements (1 h)", "0")
        self.c_sat = Card("Saturation ADC", "—")
        for i, c in enumerate((self.c_rx, self.c_mode, self.c_freq, self.c_floor, self.c_events, self.c_sat)):
            grid.addWidget(c, 0, i)
        self.root.addLayout(grid)
        mid = QHBoxLayout()
        g = QGroupBox("Spectre en direct")
        gl = QVBoxLayout(g)
        self.plot = SpectrumPlot()
        self.plot.setMinimumHeight(220)
        gl.addWidget(self.plot)
        mid.addWidget(g, 3)
        g2 = QGroupBox("Émissions présentes (trame courante)")
        gl2 = QVBoxLayout(g2)
        self.det_table = make_table(["Fréquence", "Puissance canal", "SNR", "Largeur"])
        gl2.addWidget(self.det_table)
        mid.addWidget(g2, 2)
        self.root.addLayout(mid, 2)
        g3 = QGroupBox("Derniers événements")
        gl3 = QVBoxLayout(g3)
        self.ev_table = make_table(["Début", "Durée", "Fréquence", "Canal", "Puissance moy.", "Caractérisation",
                                    "Nature"])
        gl3.addWidget(self.ev_table)
        self.root.addWidget(g3, 2)
        warn = QLabel("Rappel : un événement signale une émission détectée, pas l'identification d'un équipement. "
                      "N'écoutez et n'enregistrez que les communications pour lesquelles vous êtes autorisé.")
        warn.setObjectName("hint")
        warn.setWordWrap(True)
        self.root.addWidget(warn)
        ctx.frame.connect(self._frame)
        ctx.acquisition_changed.connect(self._acq)
        ctx.history_changed.connect(self.refresh_events)
        ctx.receiver_changed.connect(lambda _: self.refresh_static())
        self._last_ui = 0.0
        self.refresh_static()
        self.refresh_events()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh_static)
        self._timer.start(2000)

    def on_show(self) -> None:
        self.refresh_static()
        self.refresh_events()

    def toggle(self) -> None:
        if self.ctx.running:
            self.ctx.stop_acquisition()
        else:
            self.ctx.start_acquisition()

    def _acq(self, running: bool) -> None:
        self.btn_start.setText("■  Arrêter l'acquisition" if running else "▶  Démarrer l'acquisition")
        self.plot.rescale()
        self.refresh_static()

    def refresh_static(self) -> None:
        ctx = self.ctx
        self.c_rx.set(ctx.device.model if len(ctx.device.model) < 26 else ctx.device.model[:24] + "…",
                      ctx.device.status_text)
        self.c_mode.set("SIMULATION" if ctx.simulated else "RÉELLE",
                        "Mode laboratoire : " + ctx.scenario.name if ctx.simulated else "Matériel / fichier IQ")
        cfg = ctx.receiver.config
        self.c_freq.set(f"{cfg.center_freq_hz / 1e6:.4f} MHz",
                        f"{cfg.sample_rate_hz / 1e3:.0f} kS/s · gain {'auto' if cfg.gain_db is None else f'{cfg.gain_db:.0f} dB'}"
                        + (" · en cours" if ctx.running else " · arrêté"))
        n = len(ctx.db.query_events(since=time.time() - 3600))
        self.c_events.set(str(n), "réels + simulés, base locale")

    def refresh_events(self) -> None:
        evs = self.ctx.db.query_events(limit=12)
        fill_table(self.ev_table, [
            (fmt_ts(e.start_ts), f"{e.duration_s:.2f} s", fmt_freq(e.emission_freq_hz), e.channel_name or "—",
             f"{self.ctx.to_display_power(e.mean_power_dbfs):.1f} {self.ctx.power_unit}",
             fmt_classification(e),
             "SIMULÉ" if e.simulated else "RÉEL") for e in evs])

    def _frame(self, fr, dets) -> None:
        now = time.monotonic()
        if not self.isVisible() or now - self._last_ui < 0.1:
            return
        self._last_ui = now
        self.plot.offset_db = self.ctx.calibration_offset_db or 0.0
        self.plot.threshold_db = self.ctx.activity_params.open_threshold_db
        self.plot.update_frame(fr, dets)
        unit = self.ctx.power_unit
        self.c_floor.set(f"{self.ctx.to_display_power(fr.noise_floor_dbfs):.1f} {unit}", f"RBW {fr.rbw_hz:.0f} Hz")
        self.c_sat.set("OUI" if fr.saturated else "non", f"{fr.saturation_ratio:.3%} d'échantillons écrêtés")
        fill_table(self.det_table, [(fmt_freq(d.center_freq_hz), f"{self.ctx.to_display_power(d.channel_power_dbfs):.1f}",
                                     f"{d.snr_db:.1f} dB", "n/m" if d.bandwidth_hz is None else f"{d.bandwidth_hz:.0f} Hz")
                                    for d in dets])

    def selftest(self) -> None:
        res = run_selftests()
        for r in res:
            self.ctx.db.add_test_result(r)
        ok = sum(r.passed for r in res)
        self.ctx.db.audit(self.ctx.access.actor, "selftest", {"passed": ok, "total": len(res)})
        self.ctx.notify.emit(f"Autotest : {ok}/{len(res)} tests réussis (détails dans Rapports).",
                             "ok" if ok == len(res) else "warn")
