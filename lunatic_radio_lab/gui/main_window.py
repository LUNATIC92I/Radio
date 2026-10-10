"""Fenêtre principale : navigation latérale, écrans, barre d'état et notifications."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from .context import AppContext
from .pages.activity import ActivityPage
from .pages.audio import AudioPage
from .pages.channels import ChannelsPage
from .pages.console import ConsolePage
from .pages.dashboard import DashboardPage
from .pages.devices import DevicesPage
from .pages.history import HistoryPage
from .pages.identification import IdentificationPage
from .pages.lab import LabPage
from .pages.receiver_config import ReceiverConfigPage
from .pages.reports import ReportsPage
from .pages.security import SecurityPage
from .pages.spectrum import SpectrumPage
from .pages.waterfall import WaterfallPage
from .widgets import Toast, badge, set_badge

NAV = [
    ("◈  Tableau de bord", DashboardPage),
    ("⌁  Équipements", DevicesPage),
    ("∿  Analyseur de spectre", SpectrumPage),
    ("▤  Waterfall", WaterfallPage),
    ("◉  Détection d'activité", ActivityPage),
    ("⌖  Identification signaux", IdentificationPage),
    ("♫  Analyse audio", AudioPage),
    ("☰  Historique", HistoryPage),
    ("⚑  Canaux autorisés", ChannelsPage),
    ("⚙  Configuration récepteur", ReceiverConfigPage),
    ("⚗  Mode laboratoire", LabPage),
    ("›_ Console technique", ConsolePage),
    ("⎙  Rapports", ReportsPage),
    ("⛨  Sécurité & conformité", SecurityPage),
]


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(f"{APP_NAME} {__version__} — réception seule")
        self.resize(1440, 900)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(240)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 16, 10, 12)
        brand = QLabel("LUNATIC")
        brand.setObjectName("brand")
        sub = QLabel("RADIO LAB")
        sub.setObjectName("brandSub")
        sl.addWidget(brand)
        sl.addWidget(sub)
        sl.addSpacing(14)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        sl.addWidget(self.nav, 1)
        ro = QLabel("RÉCEPTION SEULE · LOCAL")
        ro.setObjectName("hint")
        sl.addWidget(ro)
        lay.addWidget(side)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.pages = []
        for label, cls in NAV:
            page = cls(ctx)
            self.pages.append(page)
            self.stack.addWidget(page)
            self.nav.addItem(QListWidgetItem(label))
        self.nav.currentRowChanged.connect(self._goto)
        self.nav.setCurrentRow(0)

        sb = self.statusBar()
        self.sb_mode = badge("SIMULATION", "simBadge")
        self.sb_acq = QLabel("Acquisition arrêtée")
        self.sb_sat = badge("", "okBadge")
        self.sb_sat.hide()
        self.sb_admin = QLabel("🔒")
        self.sb_msg = QLabel("")
        sb.addWidget(self.sb_mode)
        sb.addWidget(self.sb_acq)
        sb.addWidget(self.sb_msg, 1)
        sb.addPermanentWidget(self.sb_sat)
        sb.addPermanentWidget(self.sb_admin)

        ctx.notify.connect(self.toast)
        ctx.status.connect(self.sb_msg.setText)
        ctx.acquisition_changed.connect(self._acq)
        ctx.receiver_changed.connect(lambda _: self._mode())
        ctx.frame.connect(self._frame)
        ctx.access_changed.connect(lambda _: self._admin())
        self._toasts: list[Toast] = []
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._admin)
        self._timer.start(5000)
        self._mode()
        self._admin()

    def _goto(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        self.pages[i].on_show()

    def goto_page(self, cls: type) -> None:
        for i, p in enumerate(self.pages):
            if isinstance(p, cls):
                self.nav.setCurrentRow(i)
                return

    def _mode(self) -> None:
        if self.ctx.simulated:
            set_badge(self.sb_mode, "DONNÉES SIMULÉES", "simBadge")
        else:
            set_badge(self.sb_mode, "MESURE RÉELLE", "realBadge")

    def _acq(self, running: bool) -> None:
        self.sb_acq.setText(f"Acquisition en cours — {self.ctx.device.label}" if running else "Acquisition arrêtée")
        if not running:
            self.sb_sat.hide()
        self._mode()

    def _frame(self, fr, dets) -> None:  # noqa: ANN001
        if fr.saturated:
            set_badge(self.sb_sat, "⚠ SATURATION", "satBadge")
            self.sb_sat.show()
        elif self.sb_sat.isVisible():
            self.sb_sat.hide()

    def _admin(self) -> None:
        a = self.ctx.access
        self.sb_admin.setText(f"🔓 Admin ({int(a.remaining_s // 60)} min)" if a.unlocked else "🔒 Verrouillé")

    def toast(self, message: str, level: str = "info") -> None:
        t = Toast(self, message, level)
        self._toasts = [x for x in self._toasts if x is not None and _alive(x)] + [t]
        self._place_toasts()
        t.show()

    def _place_toasts(self) -> None:
        y = self.height() - 40
        for t in reversed(self._toasts[-4:]):
            if not _alive(t):
                continue
            t.adjustSize()
            y -= t.height() + 8
            t.move(self.width() - t.width() - 20, y)

    def resizeEvent(self, ev) -> None:  # noqa: ANN001, N802
        super().resizeEvent(ev)
        self._place_toasts()

    def closeEvent(self, ev: QCloseEvent) -> None:  # noqa: N802
        self.ctx.shutdown()
        super().closeEvent(ev)


def _alive(w: QWidget) -> bool:
    try:
        w.isVisible()
        return True
    except RuntimeError:
        return False
