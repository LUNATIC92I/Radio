"""Analyseur de spectre temps réel."""

from __future__ import annotations

import time

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QSplitter, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from ...dsp.spectrum import dynamic_range_db
from ...models import ReceiverConfig
from ...reports.builder import fmt_freq
from ..plots import SpectrumPlot, WaterfallWidget
from ..widgets import Page, button, error_box, fill_table, make_table, mhz_spin, spin

SAMPLE_RATES = [62_500, 125_000, 250_000, 500_000, 1_024_000, 2_048_000, 2_400_000, 3_200_000]
FFT_SIZES = [512, 1024, 2048, 4096, 8192, 16384]


class SpectrumPage(Page):
    title = "Analyseur de spectre"
    subtitle = ("Spectre moyenné (Welch) en dBFS relatifs. Puissance par case FFT : dépend de la résolution (RBW). "
                "Les mesures ne sont valides qu'en l'absence de saturation.")

    def __init__(self, ctx):
        super().__init__(ctx)
        self.btn_start = button("▶  Démarrer", self.toggle, "primary")
        self.header_right_lay.addWidget(self.btn_start)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.plot = SpectrumPlot()
        self.plot.marker_moved.connect(self._marker)
        ll.addWidget(self.plot, 3)
        self.wf = WaterfallWidget(history=150)
        ll.addWidget(self.wf, 2)
        split.addWidget(left)

        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        g = QGroupBox("Réglages (dans les limites du matériel)")
        f = QFormLayout(g)
        cfg = ctx.receiver.config
        self.freq = mhz_spin(cfg.center_freq_hz)
        self.rate = QComboBox()
        for r in SAMPLE_RATES:
            self.rate.addItem(f"{r / 1e3:g} kS/s", r)
        self.gain = spin(cfg.gain_db if cfg.gain_db is not None else 30.0, 0, 70, "dB", 1, 1)
        self.agc = QCheckBox("Gain automatique (AGC)")
        self.agc.setChecked(cfg.gain_db is None)
        self.fft = QComboBox()
        for n in FFT_SIZES:
            self.fft.addItem(str(n), n)
        self.fft.setCurrentText(str(ctx.fft_size))
        self.video = spin(0.0, 0.0, 0.95, "", 2, 0.05)
        self.video.setToolTip("Lissage exponentiel entre trames (0 = désactivé)")
        self.maxhold = QCheckBox("Max-hold")
        self.maxhold.toggled.connect(self._maxhold)
        f.addRow("Fréquence centrale", self.freq)
        f.addRow("Échantillonnage (largeur observée)", self.rate)
        f.addRow("Gain", self.gain)
        f.addRow("", self.agc)
        f.addRow("Taille FFT", self.fft)
        f.addRow("Moyennage vidéo", self.video)
        f.addRow("", self.maxhold)
        row = QHBoxLayout()
        row.addWidget(button("Appliquer", self.apply, "primary"))
        row.addWidget(button("Échelle auto", self._rescale))
        f.addRow(row)
        sl.addWidget(g)

        g2 = QGroupBox("Mesures")
        f2 = QFormLayout(g2)
        self.m_marker = QLabel("—")
        self.m_floor = QLabel("—")
        self.m_rbw = QLabel("—")
        self.m_avg = QLabel("—")
        self.m_sat = QLabel("—")
        self.m_dr = QLabel("—")
        f2.addRow("Marqueur", self.m_marker)
        f2.addRow("Plancher de bruit", self.m_floor)
        f2.addRow("Résolution (RBW)", self.m_rbw)
        f2.addRow("Moyennage", self.m_avg)
        f2.addRow("Saturation", self.m_sat)
        f2.addRow("Dynamique ADC", self.m_dr)
        lim = QLabel("Précision : puissance relative (dBFS) sans étalonnage ; incertitude fréquence liée à "
                     "l'oscillateur (ppm) et à la résolution ; largeur de bande non mesurable sous ≈ 2 RBW.")
        lim.setObjectName("hint")
        lim.setWordWrap(True)
        f2.addRow(lim)
        sl.addWidget(g2)
        g3 = QGroupBox("Émissions détectées (trame courante)")
        l3 = QVBoxLayout(g3)
        self.det = make_table(["Fréquence", "Canal dBFS", "SNR", "Largeur 99 %"])
        l3.addWidget(self.det)
        sl.addWidget(g3, 1)
        split.addWidget(side)
        split.setSizes([900, 360])
        self.root.addWidget(split, 1)

        ctx.frame.connect(self._frame)
        ctx.acquisition_changed.connect(self._acq)
        ctx.receiver_changed.connect(lambda _: self._load_cfg())
        ctx.channels_changed.connect(self._channels)
        self._channels()
        self._load_cfg()
        self._last_ui = 0.0

    def on_show(self) -> None:
        self._load_cfg()

    def _channels(self) -> None:
        self.plot.set_channels([(c.name, c.low_hz, c.high_hz) for c in self.ctx.channels.list()])

    def _load_cfg(self) -> None:
        cfg = self.ctx.receiver.config
        for w in (self.freq, self.gain, self.rate):
            w.blockSignals(True)
        self.freq.setValue(cfg.center_freq_hz / 1e6)
        i = self.rate.findData(int(cfg.sample_rate_hz))
        if i < 0:
            self.rate.addItem(f"{cfg.sample_rate_hz / 1e3:g} kS/s", int(cfg.sample_rate_hz))
            i = self.rate.count() - 1
        self.rate.setCurrentIndex(i)
        if cfg.gain_db is not None:
            self.gain.setValue(cfg.gain_db)
        self.agc.setChecked(cfg.gain_db is None)
        g0, g1 = self.ctx.device.gain_range_db
        if g1 > g0:
            self.gain.setRange(g0, g1)
        for w in (self.freq, self.gain, self.rate):
            w.blockSignals(False)
        dr = dynamic_range_db(self.ctx.device.adc_bits)
        self.m_dr.setText(f"≈ {dr:.0f} dB ({self.ctx.device.adc_bits} bits)" if dr else "non déclarée")
        self.btn_start.setText("■  Arrêter" if self.ctx.running else "▶  Démarrer")

    def toggle(self) -> None:
        if self.ctx.running:
            self.ctx.stop_acquisition()
        else:
            self.apply()
            self.ctx.start_acquisition()

    def _acq(self, running: bool) -> None:
        self.btn_start.setText("■  Arrêter" if running else "▶  Démarrer")
        self.plot.rescale()
        self.plot.reset_hold()

    def _rescale(self) -> None:
        self.plot.rescale()

    def _maxhold(self, on: bool) -> None:
        self.plot.max_hold_enabled = on
        self.plot.reset_hold()

    def apply(self) -> None:
        old = self.ctx.receiver.config
        cfg = ReceiverConfig(self.freq.value() * 1e6, float(self.rate.currentData()),
                             None if self.agc.isChecked() else self.gain.value(), old.bandwidth_hz,
                             old.ppm_correction, old.antenna)
        try:
            self.ctx.apply_config(cfg)
        except Exception as exc:  # noqa: BLE001
            error_box(self, "Configuration refusée", exc)
            return
        n = int(self.fft.currentData())
        if n != self.ctx.fft_size:
            self.ctx.set_fft_size(n)
        if self.ctx.engine is not None:
            self.ctx.engine.analyzer.video_avg = self.video.value()
        self.plot.rescale()
        self.plot.reset_hold()
        self.wf.clear()

    def _marker(self, f: float, p: float) -> None:
        self.m_marker.setText(f"{f / 1e6:.5f} MHz · {p:.1f} {self.ctx.power_unit}")

    def _frame(self, fr, dets) -> None:
        now = time.monotonic()
        if not self.isVisible() or now - self._last_ui < 0.05:
            return
        self._last_ui = now
        off = self.ctx.calibration_offset_db or 0.0
        self.plot.offset_db = off
        self.plot.threshold_db = self.ctx.activity_params.open_threshold_db
        self.plot.update_frame(fr, dets)
        self.wf.push(fr, off)
        unit = self.ctx.power_unit
        self.m_floor.setText(f"{fr.noise_floor_dbfs + off:.1f} {unit} / case")
        self.m_rbw.setText(f"{fr.rbw_hz:.1f} Hz (FFT {fr.fft_size}, {fr.sample_rate_hz / fr.fft_size:.1f} Hz/case)")
        self.m_avg.setText(f"{fr.averages} segments / trame")
        self.m_sat.setText(("⚠ OUI — " if fr.saturated else "non — ") + f"{fr.saturation_ratio:.3%}")
        self.m_sat.setStyleSheet("color: #E5484D; font-weight: 700" if fr.saturated else "")
        fill_table(self.det, [(fmt_freq(d.center_freq_hz), f"{d.channel_power_dbfs + off:.1f}", f"{d.snr_db:.1f} dB",
                               "n/m" if d.bandwidth_hz is None else f"{d.bandwidth_hz:.0f} Hz") for d in dets])
