"""Widgets communs : en-têtes, cartes, notifications, boîtes de dialogue d'accès."""

from __future__ import annotations

from typing import Callable, Iterable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..security.access import AccessDenied
from .context import AppContext


def page_header(title: str, subtitle: str = "", right: QWidget | None = None) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 6)
    col = QVBoxLayout()
    t = QLabel(title)
    t.setObjectName("pageTitle")
    col.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("pageSubtitle")
        s.setWordWrap(True)
        col.addWidget(s)
    lay.addLayout(col, 1)
    if right is not None:
        lay.addWidget(right, 0, Qt.AlignTop)
    return w


class Page(QWidget):
    """Base des écrans : marge, en-tête, accès au contexte."""

    title = ""
    subtitle = ""

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(18, 14, 18, 14)
        self.root.setSpacing(10)
        self.header_right = QWidget()
        self.header_right_lay = QHBoxLayout(self.header_right)
        self.header_right_lay.setContentsMargins(0, 0, 0, 0)
        self.root.addWidget(page_header(self.title, self.subtitle, self.header_right))

    def on_show(self) -> None:
        """Appelé quand l'écran devient visible."""


class Card(QFrame):
    def __init__(self, title: str, value: str = "—", hint: str = ""):
        super().__init__()
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        self.t = QLabel(title)
        self.t.setObjectName("cardTitle")
        self.v = QLabel(value)
        self.v.setObjectName("cardValue")
        self.h = QLabel(hint)
        self.h.setObjectName("hint")
        self.h.setWordWrap(True)
        lay.addWidget(self.t)
        lay.addWidget(self.v)
        lay.addWidget(self.h)

    def set(self, value: str, hint: str | None = None) -> None:
        self.v.setText(value)
        if hint is not None:
            self.h.setText(hint)


def badge(text: str, kind: str = "realBadge") -> QLabel:
    b = QLabel(text)
    b.setObjectName(kind)
    return b


def set_badge(lbl: QLabel, text: str, kind: str) -> None:
    lbl.setText(text)
    lbl.setObjectName(kind)
    lbl.style().unpolish(lbl)
    lbl.style().polish(lbl)


def button(text: str, slot: Callable | None = None, kind: str = "", tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if slot is not None:
        b.clicked.connect(slot)
    if tooltip:
        b.setToolTip(tooltip)
    return b


def make_table(headers: list[str], stretch_last: bool = True) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(stretch_last)
    # aucun tri tant que l'utilisateur ne clique pas sur un en-tête : l'ordre fourni est conservé
    t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
    return t


def fill_table(t: QTableWidget, rows: Iterable[Iterable], data: list | None = None) -> None:
    t.setSortingEnabled(False)
    rows = list(rows)
    t.setRowCount(len(rows))
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            it = QTableWidgetItem("" if v is None else str(v))
            if isinstance(v, (int, float)):
                it.setData(Qt.EditRole, v)
            if j == 0 and data is not None:
                it.setData(Qt.UserRole, data[i])
            t.setItem(i, j, it)
    t.setSortingEnabled(True)


def mhz_spin(value_hz: float = 446.1e6, lo: float = 0.009, hi: float = 300_000.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(6)
    s.setRange(lo, hi)
    s.setSuffix(" MHz")
    s.setSingleStep(0.0125)
    s.setValue(value_hz / 1e6)
    s.setKeyboardTracking(False)
    return s


def spin(value: float, lo: float, hi: float, suffix: str = "", decimals: int = 1, step: float = 1.0) -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(decimals)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(value)
    if suffix:
        s.setSuffix(" " + suffix)
    s.setKeyboardTracking(False)
    return s


class Toast(QFrame):
    """Notification non bloquante en bas à droite de la fenêtre."""

    def __init__(self, parent: QWidget, message: str, level: str = "info", ms: int = 4500):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("level", level)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        icon = {"error": "⛔", "warn": "⚠", "ok": "✔"}.get(level, "ℹ")
        lbl = QLabel(f"{icon}  {message}")
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(420)
        lay.addWidget(lbl)
        self.adjustSize()
        QTimer.singleShot(ms, self.deleteLater)


def unlock_dialog(ctx: AppContext, parent: QWidget | None = None) -> bool:
    """Demande le code administrateur (et propose d'en définir un au premier usage)."""
    if ctx.access.unlocked:
        return True
    if not ctx.access.has_pin:
        return set_pin_dialog(ctx, parent) and unlock_dialog(ctx, parent)
    dlg = QDialog(parent)
    dlg.setWindowTitle("Accès administrateur")
    lay = QFormLayout(dlg)
    lay.addRow(QLabel("Action protégée. Saisissez le code administrateur.\nLe déverrouillage expire après 10 minutes."))
    pin = QLineEdit()
    pin.setEchoMode(QLineEdit.Password)
    lay.addRow("Code :", pin)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addRow(bb)
    if dlg.exec() != QDialog.Accepted:
        return False
    try:
        ok = ctx.access.unlock(pin.text())
    except AccessDenied as exc:
        QMessageBox.warning(parent, "Accès refusé", str(exc))
        return False
    if not ok:
        QMessageBox.warning(parent, "Accès refusé", "Code invalide. L'échec a été journalisé.")
        return False
    ctx.access_changed.emit(True)
    return True


def set_pin_dialog(ctx: AppContext, parent: QWidget | None = None) -> bool:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Code administrateur")
    lay = QFormLayout(dlg)
    cur = QLineEdit()
    cur.setEchoMode(QLineEdit.Password)
    new1, new2 = QLineEdit(), QLineEdit()
    new1.setEchoMode(QLineEdit.Password)
    new2.setEchoMode(QLineEdit.Password)
    if ctx.access.has_pin:
        lay.addRow("Code actuel :", cur)
    else:
        lay.addRow(QLabel("Aucun code n'est défini. Choisissez un code (6 caractères minimum)\n"
                          "pour protéger les paramètres sensibles."))
    lay.addRow("Nouveau code :", new1)
    lay.addRow("Confirmation :", new2)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addRow(bb)
    if dlg.exec() != QDialog.Accepted:
        return False
    if new1.text() != new2.text():
        QMessageBox.warning(parent, "Code administrateur", "Les deux saisies diffèrent.")
        return False
    try:
        ctx.access.set_pin(new1.text(), cur.text() if ctx.access.has_pin else None)
    except (ValueError, AccessDenied) as exc:
        QMessageBox.warning(parent, "Code administrateur", str(exc))
        return False
    ctx.notify.emit("Code administrateur enregistré.", "ok")
    return True


def guarded(ctx: AppContext, parent: QWidget, fn: Callable[[], object]) -> object | None:
    """Exécute une action protégée ; demande le déverrouillage si nécessaire."""
    try:
        return fn()
    except AccessDenied:
        if unlock_dialog(ctx, parent):
            try:
                return fn()
            except AccessDenied as exc:
                QMessageBox.warning(parent, "Accès refusé", str(exc))
    return None


def error_box(parent: QWidget, title: str, exc: BaseException | str) -> None:
    QMessageBox.critical(parent, title, str(exc))
