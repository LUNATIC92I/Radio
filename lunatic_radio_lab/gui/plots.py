"""Graphiques temps réel : spectre et waterfall (PyQtGraph)."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal

from ..models import Detection, SpectrumFrame
from . import theme


def _decimate(freqs: np.ndarray, power: np.ndarray, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    if len(power) <= max_points:
        return freqs, power
    step = int(np.ceil(len(power) / max_points))
    n = (len(power) // step) * step
    return freqs[:n].reshape(-1, step).mean(axis=1), power[:n].reshape(-1, step).max(axis=1)


class SpectrumPlot(pg.PlotWidget):
    """Spectre (MHz / dBFS) : trace, max-hold, plancher, seuil, détections, marqueur."""

    marker_moved = Signal(float, float)  # fréquence Hz, puissance

    def __init__(self, unit: str = "dBFS"):
        super().__init__()
        self.setLabel("bottom", "Fréquence", units="Hz")
        self.setLabel("left", "Puissance", units=unit)
        self.showGrid(x=True, y=True, alpha=0.18)
        self.setYRange(-120, 0)
        self.getPlotItem().setMenuEnabled(False)
        self.trace = self.plot(pen=pg.mkPen(theme.ELECTRIC, width=1))
        self.hold = self.plot(pen=pg.mkPen(theme.SILVER_DIM, width=1, style=Qt.DotLine))
        self.floor_line = pg.InfiniteLine(angle=0, pen=pg.mkPen(theme.WARN, width=1, style=Qt.DashLine),
                                          label="plancher", labelOpts={"color": theme.WARN, "position": 0.03})
        self.thr_line = pg.InfiniteLine(angle=0, pen=pg.mkPen(theme.ERROR, width=1, style=Qt.DashLine),
                                        label="seuil", labelOpts={"color": theme.ERROR, "position": 0.08})
        self.addItem(self.floor_line)
        self.addItem(self.thr_line)
        self.vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(theme.CYAN, width=1))
        self.addItem(self.vline)
        self.marker_text = pg.TextItem(color=theme.CYAN, anchor=(0, 1))
        self.addItem(self.marker_text)
        self.sim_text = pg.TextItem("", color=theme.SIM, anchor=(1, 0))
        self.addItem(self.sim_text)
        self.sat_text = pg.TextItem("", color=theme.ERROR, anchor=(0, 0))
        self.addItem(self.sat_text)
        self._regions: list[pg.LinearRegionItem] = []
        self._chan_regions: list[pg.LinearRegionItem] = []
        self.max_hold_enabled = False
        self._hold_data: np.ndarray | None = None
        self.threshold_db = 10.0
        self.offset_db = 0.0
        self.max_points = 2048
        self._freqs: np.ndarray | None = None
        self._pow: np.ndarray | None = None
        self._autorange_done = False
        self.scene().sigMouseMoved.connect(self._mouse)

    def reset_hold(self) -> None:
        self._hold_data = None
        self.hold.setData([], [])

    def set_channels(self, windows: list[tuple[str, float, float]]) -> None:
        for r in self._chan_regions:
            self.removeItem(r)
        self._chan_regions = []
        for name, lo, hi in windows:
            r = pg.LinearRegionItem((lo, hi), movable=False, brush=pg.mkBrush(30, 144, 255, 18),
                                    pen=pg.mkPen(30, 144, 255, 60))
            r.setZValue(-20)
            r.setToolTip(name)
            self.addItem(r)
            self._chan_regions.append(r)

    def update_frame(self, fr: SpectrumFrame, dets: list[Detection] | None = None) -> None:
        f, p = _decimate(np.asarray(fr.freqs_hz), np.asarray(fr.power_dbfs, dtype=np.float64) + self.offset_db,
                         self.max_points)
        self._freqs, self._pow = f, p
        self.trace.setData(f, p)
        self.trace.setPen(pg.mkPen(theme.SIM if fr.simulated else theme.ELECTRIC, width=1))
        if self.max_hold_enabled:
            if self._hold_data is None or self._hold_data.shape != p.shape:
                self._hold_data = p.copy()
            else:
                np.maximum(self._hold_data, p, out=self._hold_data)
            self.hold.setData(f, self._hold_data)
        floor = fr.noise_floor_dbfs + self.offset_db
        self.floor_line.setValue(floor)
        self.thr_line.setValue(floor + self.threshold_db)
        vr = self.viewRange()
        self.sim_text.setText("SIMULATION" if fr.simulated else "")
        self.sim_text.setPos(vr[0][1], vr[1][1])
        self.sat_text.setText("⚠ SATURATION ADC — réduisez le gain" if fr.saturated else "")
        self.sat_text.setPos(vr[0][0], vr[1][1])
        if not self._autorange_done:
            self.setXRange(f[0], f[-1], padding=0)
            self.setYRange(floor - 15, max(floor + 70, float(p.max()) + 10))
            self._autorange_done = True
        for r in self._regions:
            self.removeItem(r)
        self._regions = []
        for d in dets or []:
            r = pg.LinearRegionItem((d.low_hz, d.high_hz), movable=False, brush=pg.mkBrush(46, 189, 133, 40),
                                    pen=pg.mkPen(46, 189, 133, 120))
            r.setZValue(-10)
            self.addItem(r)
            self._regions.append(r)

    def rescale(self) -> None:
        self._autorange_done = False

    def _mouse(self, pos) -> None:  # noqa: ANN001
        if self._freqs is None or not self.sceneBoundingRect().contains(pos):
            return
        mp = self.getPlotItem().vb.mapSceneToView(pos)
        fx = mp.x()
        i = int(np.clip(np.searchsorted(self._freqs, fx), 0, len(self._freqs) - 1))
        pw = float(self._pow[i])
        self.vline.setPos(self._freqs[i])
        self.marker_text.setText(f"{self._freqs[i] / 1e6:.5f} MHz\n{pw:.1f}")
        self.marker_text.setPos(self._freqs[i], pw)
        self.marker_moved.emit(float(self._freqs[i]), pw)


class WaterfallWidget(pg.GraphicsLayoutWidget):
    """Waterfall : temps vers le bas, fréquence en abscisse."""

    clicked_freq = Signal(float)

    def __init__(self, history: int = 300, columns: int = 1024):
        super().__init__()
        self.history = history
        self.columns = columns
        self.plot = self.addPlot()
        self.plot.setLabel("bottom", "Fréquence", units="Hz")
        self.plot.setLabel("left", "Trames (récentes en haut)")
        self.plot.setMenuEnabled(False)
        self.img = pg.ImageItem()
        self.plot.addItem(self.img)
        self.plot.invertY(True)
        self.bar = pg.ColorBarItem(values=(-110, -40), colorMap=theme.waterfall_colormap(), label="dBFS",
                                   interactive=True, width=12)
        self.bar.setImageItem(self.img, insert_in=self.plot)
        self.data = np.full((history, columns), -140.0, dtype=np.float32)
        self.f0 = 0.0
        self.f1 = 1.0
        self.auto_levels = True
        self.timestamps = np.zeros(history)
        self.sim_label = pg.TextItem("", color=theme.SIM, anchor=(1, 0))
        self.plot.addItem(self.sim_label)
        self.img.mouseClickEvent = self._click  # type: ignore[assignment]

    def set_history(self, n: int) -> None:
        self.history = n
        self.data = np.full((n, self.columns), -140.0, dtype=np.float32)
        self.timestamps = np.zeros(n)

    def clear(self) -> None:
        self.data[:] = -140.0

    def push(self, fr: SpectrumFrame, offset_db: float = 0.0) -> None:
        f, p = _decimate(np.asarray(fr.freqs_hz), np.asarray(fr.power_dbfs, dtype=np.float64) + offset_db, self.columns)
        if len(p) != self.data.shape[1] or f[0] != self.f0 or f[-1] != self.f1:
            self.data = np.full((self.history, len(p)), -140.0, dtype=np.float32)
            self.f0, self.f1 = float(f[0]), float(f[-1])
        self.data = np.roll(self.data, 1, axis=0)
        self.data[0] = p
        self.timestamps = np.roll(self.timestamps, 1)
        self.timestamps[0] = fr.timestamp
        self.img.setImage(self.data, autoLevels=False)
        bw = (self.f1 - self.f0) * len(p) / max(len(p) - 1, 1)
        self.img.setRect(self.f0 - bw / len(p) / 2, 0, bw, self.history)
        if self.auto_levels:
            floor = fr.noise_floor_dbfs + offset_db
            self.bar.setLevels((floor - 5, floor + 55))
        self.sim_label.setText("SIMULATION" if fr.simulated else "")
        self.sim_label.setPos(self.f1, 0)

    def _click(self, ev) -> None:  # noqa: ANN001
        pos = ev.pos()
        if self.data.shape[1] > 1:
            f = self.f0 + (self.f1 - self.f0) * pos.x() / self.data.shape[1]
            self.clicked_freq.emit(float(f))
