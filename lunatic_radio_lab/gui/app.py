"""Lancement de l'interface graphique."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from .. import APP_NAME, APP_ORG, paths


def _setup_file_logging() -> None:
    h = RotatingFileHandler(paths.logs_dir() / "lunatic_radio_lab.log", maxBytes=2_000_000, backupCount=5,
                            encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(h)
    root.setLevel(logging.INFO)


def create_app(argv: list[str] | None = None):  # noqa: ANN201
    from PySide6.QtWidgets import QApplication

    from .theme import QSS, configure_pyqtgraph

    app = QApplication.instance() or QApplication(argv or sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
    configure_pyqtgraph()
    return app


def run_gui(argv: list[str] | None = None) -> int:
    _setup_file_logging()
    app = create_app(argv)
    from .context import AppContext
    from .main_window import MainWindow

    ctx = AppContext()
    ctx.db.audit(ctx.access.actor, "app.start", {})
    win = MainWindow(ctx)
    win.show()
    if not ctx.access.has_pin:
        ctx.notify.emit("Définissez un code administrateur (Sécurité & conformité) pour protéger les paramètres "
                        "sensibles.", "warn")
    if ctx.simulated:
        ctx.notify.emit("Aucun matériel sélectionné : mode SIMULATION actif.", "info")
    return app.exec()
