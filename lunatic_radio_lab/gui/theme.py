"""Identité visuelle : laboratoire radio / cybersécurité — graphite, argent, bleu électrique."""

from __future__ import annotations

import pyqtgraph as pg

GRAPHITE_0 = "#0F1115"  # fond principal
GRAPHITE_1 = "#171A20"  # panneaux
GRAPHITE_2 = "#1F232B"  # champs
GRAPHITE_3 = "#2A2F39"  # bordures
SILVER = "#C3C8D1"
SILVER_DIM = "#8A919C"
ELECTRIC = "#1E90FF"
ELECTRIC_LIGHT = "#5CB3FF"
CYAN = "#00D1FF"
SIM = "#B04BD8"  # données simulées
WARN = "#E0A100"
ERROR = "#E5484D"
OK = "#2EBD85"

QSS = f"""
* {{ font-family: "Inter", "Segoe UI", "DejaVu Sans", sans-serif; font-size: 10pt; color: {SILVER}; }}
QMainWindow, QWidget#page, QStackedWidget, QDialog, QWizard {{ background: {GRAPHITE_0}; }}
QWidget {{ background: transparent; }}
QFrame#sidebar {{ background: {GRAPHITE_1}; border-right: 1px solid {GRAPHITE_3}; }}
QLabel#brand {{ color: {ELECTRIC}; font-size: 15pt; font-weight: 800; letter-spacing: 2px; }}
QLabel#brandSub {{ color: {SILVER_DIM}; font-size: 8pt; letter-spacing: 3px; }}
QLabel#pageTitle {{ font-family: "Segoe UI", "DejaVu Sans", sans-serif; font-size: 16pt; font-weight: 700; color: #E6E9EE; }}
QLabel#pageSubtitle {{ color: {SILVER_DIM}; }}
QLabel#cardValue {{ font-size: 17pt; font-weight: 700; color: #E6E9EE; }}
QLabel#cardTitle {{ color: {SILVER_DIM}; font-size: 8.5pt; text-transform: uppercase; }}
QLabel#hint {{ color: {SILVER_DIM}; font-size: 8.5pt; }}
QLabel#simBadge {{ background: {SIM}; color: white; font-weight: 700; padding: 2px 8px; border-radius: 4px; }}
QLabel#realBadge {{ background: {ELECTRIC}; color: white; font-weight: 700; padding: 2px 8px; border-radius: 4px; }}
QLabel#satBadge {{ background: {ERROR}; color: white; font-weight: 700; padding: 2px 8px; border-radius: 4px; }}
QLabel#okBadge {{ background: {OK}; color: #0B1A12; font-weight: 700; padding: 2px 8px; border-radius: 4px; }}
QLabel#warnBadge {{ background: {WARN}; color: #1A1400; font-weight: 700; padding: 2px 8px; border-radius: 4px; }}
QFrame#card {{ background: {GRAPHITE_1}; border: 1px solid {GRAPHITE_3}; border-radius: 8px; }}
QGroupBox {{ background: {GRAPHITE_1}; border: 1px solid {GRAPHITE_3}; border-radius: 8px; margin-top: 14px;
             padding: 10px 8px 8px 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {ELECTRIC_LIGHT}; }}
QListWidget#nav {{ background: transparent; border: none; outline: none; }}
QListWidget#nav::item {{ padding: 8px 10px; border-radius: 6px; margin: 1px 6px; color: {SILVER}; }}
QListWidget#nav::item:selected {{ background: {GRAPHITE_3}; color: white; border-left: 3px solid {ELECTRIC}; }}
QListWidget#nav::item:hover {{ background: {GRAPHITE_2}; }}
QPushButton {{ background: {GRAPHITE_2}; border: 1px solid {GRAPHITE_3}; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ELECTRIC}; }}
QPushButton:pressed {{ background: {GRAPHITE_3}; }}
QPushButton:disabled {{ color: #5A606A; border-color: {GRAPHITE_2}; }}
QPushButton#primary {{ background: {ELECTRIC}; border: 1px solid {ELECTRIC}; color: white; font-weight: 700; }}
QPushButton#primary:hover {{ background: {ELECTRIC_LIGHT}; }}
QPushButton#danger {{ background: #3A1517; border: 1px solid {ERROR}; color: #FFC9CB; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateTimeEdit, QPlainTextEdit, QTextEdit {{
    background: {GRAPHITE_2}; border: 1px solid {GRAPHITE_3}; border-radius: 5px; padding: 4px 6px;
    selection-background-color: {ELECTRIC}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ELECTRIC}; }}
QComboBox QAbstractItemView {{ background: {GRAPHITE_2}; border: 1px solid {GRAPHITE_3}; selection-background-color: {ELECTRIC}; }}
QTableWidget, QTableView, QTreeWidget, QListWidget {{ background: {GRAPHITE_1}; alternate-background-color: {GRAPHITE_2};
    border: 1px solid {GRAPHITE_3}; border-radius: 6px; gridline-color: {GRAPHITE_3}; }}
QHeaderView::section {{ background: {GRAPHITE_2}; color: {SILVER}; padding: 5px; border: none;
    border-right: 1px solid {GRAPHITE_3}; border-bottom: 1px solid {GRAPHITE_3}; font-weight: 600; }}
QTableView::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{ background: #12406E; color: white; }}
QProgressBar {{ background: {GRAPHITE_2}; border: 1px solid {GRAPHITE_3}; border-radius: 5px; text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {ELECTRIC}; border-radius: 4px; }}
QStatusBar {{ background: {GRAPHITE_1}; border-top: 1px solid {GRAPHITE_3}; }}
QTabWidget::pane {{ border: 1px solid {GRAPHITE_3}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: {GRAPHITE_1}; padding: 6px 14px; border: 1px solid {GRAPHITE_3}; border-bottom: none;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {GRAPHITE_3}; color: white; }}
QCheckBox::indicator {{ width: 15px; height: 15px; }}
QScrollBar:vertical {{ background: {GRAPHITE_1}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {GRAPHITE_3}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: {GRAPHITE_1}; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {GRAPHITE_3}; border-radius: 4px; min-width: 30px; }}
QToolTip {{ background: {GRAPHITE_2}; color: white; border: 1px solid {ELECTRIC}; }}
QSplitter::handle {{ background: {GRAPHITE_3}; }}
QFrame#toast {{ background: {GRAPHITE_2}; border: 1px solid {ELECTRIC}; border-radius: 8px; }}
QFrame#toast[level="error"] {{ border-color: {ERROR}; }}
QFrame#toast[level="warn"] {{ border-color: {WARN}; }}
QFrame#toast[level="ok"] {{ border-color: {OK}; }}
"""


def configure_pyqtgraph() -> None:
    pg.setConfigOptions(antialias=False, background=GRAPHITE_1, foreground=SILVER, imageAxisOrder="row-major")


def waterfall_colormap() -> pg.ColorMap:
    """Palette noir → bleu électrique → cyan → blanc (lisible, cohérente avec la charte)."""
    pos = [0.0, 0.35, 0.65, 0.85, 1.0]
    cols = [(8, 10, 14), (14, 40, 100), (30, 144, 255), (0, 209, 255), (240, 248, 255)]
    return pg.ColorMap(pos, cols)
