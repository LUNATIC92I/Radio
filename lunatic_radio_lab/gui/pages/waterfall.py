"""Waterfall plein écran."""

from __future__ import annotations

import time

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QSpinBox

from ..plots import WaterfallWidget
from ..widgets import Page, button, spin


class WaterfallPage(Page):
    title = "Waterfall"
    subtitle = "Évolution temporelle du spectre (trames récentes en haut). Cliquez pour lire une fréquence."

    def __init__(self, ctx):
        super().__init__(ctx)
        bar = QHBoxLayout()
        self.history = QSpinBox()
        self.history.setRange(50, 2000)
        self.history.setValue(400)
        self.history.setSuffix(" trames")
        self.history.valueChanged.connect(lambda n: self.wf.set_history(n))
        self.auto = QCheckBox("Niveaux automatiques")
        self.auto.setChecked(True)
        self.auto.toggled.connect(self._auto)
        self.lo = spin(-110, -200, 50, "dB", 0, 5)
        self.hi = spin(-40, -200, 50, "dB", 0, 5)
        bar.addWidget(QLabel("Historique"))
        bar.addWidget(self.history)
        bar.addWidget(self.auto)
        bar.addWidget(QLabel("Min"))
        bar.addWidget(self.lo)
        bar.addWidget(QLabel("Max"))
        bar.addWidget(self.hi)
        bar.addWidget(button("Appliquer niveaux", self._levels))
        bar.addWidget(button("Effacer", lambda: self.wf.clear()))
        bar.addStretch(1)
        self.info = QLabel("—")
        self.info.setObjectName("hint")
        bar.addWidget(self.info)
        self.root.addLayout(bar)
        self.wf = WaterfallWidget(history=400, columns=1536)
        self.wf.clicked_freq.connect(lambda f: self.info.setText(f"Fréquence sélectionnée : {f / 1e6:.5f} MHz"))
        self.root.addWidget(self.wf, 1)
        ctx.frame.connect(self._frame)
        self._last = 0.0
        self._frames = 0
        self._t0 = time.monotonic()

    def _auto(self, on: bool) -> None:
        self.wf.auto_levels = on

    def _levels(self) -> None:
        self.auto.setChecked(False)
        self.wf.bar.setLevels((self.lo.value(), self.hi.value()))

    def _frame(self, fr, dets) -> None:
        # le waterfall accumule même masqué pour garder l'historique
        self.wf.push(fr, self.ctx.calibration_offset_db or 0.0)
        self._frames += 1
        now = time.monotonic()
        if now - self._last > 1.0 and self.isVisible():
            rate = self._frames / max(now - self._t0, 1e-3)
            self.info.setText(f"{rate:.1f} trames/s · {fr.sample_rate_hz / 1e3:.0f} kHz observés · "
                              f"{'SIMULATION' if fr.simulated else 'réel'}")
            self._last = now
            self._frames = 0
            self._t0 = now
