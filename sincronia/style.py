"""Tema escuro inspirado nos apps profissionais da Apple (Final Cut, Logic)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#0A84FF"
BG = "#1C1C1E"
SURFACE = "#232325"
TOOLBAR = "#2C2C2E"
SEPARATOR = "#000000"
CONTROL = "#3A3A3C"
TEXT = "#F5F5F7"
TEXT_2 = "#98989D"
TEXT_3 = "#636366"
RED = "#FF453A"
GREEN = "#30D158"
ORANGE = "#FF9F0A"

# Cores de sistema do macOS (modo escuro), uma para cada câmera/gravador.
DEVICE_COLORS = ["#0A84FF", "#30D158", "#FF9F0A", "#BF5AF2", "#FF375F",
                 "#40C8E0", "#FFD60A", "#5E5CE6", "#AC8E68"]


def device_color(index: int) -> QColor:
    return QColor(DEVICE_COLORS[index % len(DEVICE_COLORS)])


STYLESHEET = f"""
QWidget {{ color: {TEXT}; font-size: 13px; }}
QMainWindow, #central {{ background: {BG}; }}

QToolBar {{ background: {TOOLBAR}; border: none; border-bottom: 1px solid {SEPARATOR};
            padding: 8px 12px; spacing: 8px; }}

QPushButton {{ background: {CONTROL}; border: 1px solid #48484A; border-radius: 7px;
               padding: 6px 18px; min-height: 18px; color: {TEXT}; }}
QPushButton:hover {{ background: #48484A; }}
QPushButton:pressed {{ background: #2C2C2E; }}
QPushButton:disabled {{ color: {TEXT_3}; background: #2A2A2C; border-color: #333335; }}
QPushButton[primary="true"] {{ background: {ACCENT}; border-color: {ACCENT}; font-weight: 600; color: white; }}
QPushButton[primary="true"]:hover {{ background: #409CFF; border-color: #409CFF; }}
QPushButton[primary="true"]:pressed {{ background: #0071E3; }}
QPushButton[primary="true"]:disabled {{ background: #1B3556; border-color: #1B3556; color: #7D8A9C; }}

QToolButton {{ background: transparent; border: none; border-radius: 5px; padding: 2px 8px;
               color: {TEXT_2}; font-size: 16px; }}
QToolButton:hover {{ background: {CONTROL}; color: {TEXT}; }}
QToolButton:disabled {{ color: {TEXT_3}; }}
QToolButton::menu-indicator {{ image: none; }}

#sidebar {{ background: {SURFACE}; }}
#sidebarTitle {{ color: {TEXT_2}; font-size: 11px; font-weight: 600; padding: 12px 14px 4px 14px; }}
#sidebarFooter {{ border-top: 1px solid #2F2F31; }}
QTreeWidget {{ background: transparent; border: none; outline: 0; padding: 0 6px; }}
QTreeWidget::item {{ height: 24px; border-radius: 5px; }}
QTreeWidget::item:hover:!selected {{ background: #2E2E30; }}
QTreeWidget::item:selected {{ background: {ACCENT}; color: white; }}
QTreeWidget::branch {{ background: transparent; }}

#statusbar {{ background: {TOOLBAR}; border-top: 1px solid {SEPARATOR}; }}
#statusText {{ color: #D1D1D6; font-weight: 500; }}
#statusbar QPushButton {{ padding: 2px 12px; border-radius: 5px; font-size: 12px; }}

QProgressBar {{ background: {CONTROL}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QSplitter::handle {{ background: {SEPARATOR}; }}

QScrollBar:horizontal {{ height: 12px; background: transparent; margin: 0; }}
QScrollBar:vertical {{ width: 12px; background: transparent; margin: 0; }}
QScrollBar::handle {{ background: #4A4A4C; border-radius: 4px; margin: 3px; }}
QScrollBar::handle:hover {{ background: #636366; }}
QScrollBar::handle:horizontal {{ min-width: 40px; }}
QScrollBar::handle:vertical {{ min-height: 40px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenuBar {{ background: {TOOLBAR}; }}
QMenuBar::item:selected {{ background: {CONTROL}; border-radius: 4px; }}
QMenu {{ background: #2C2C2E; border: 1px solid #48484A; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 5px 24px 5px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::item:disabled {{ color: {TEXT_3}; }}
QMenu::separator {{ height: 1px; background: #48484A; margin: 5px 8px; }}

QToolTip {{ background: #2C2C2E; color: {TEXT}; border: 1px solid #48484A; padding: 6px; border-radius: 6px; }}

QMessageBox, QInputDialog {{ background: {TOOLBAR}; }}
QLineEdit {{ background: {CONTROL}; border: 1px solid #48484A; border-radius: 6px; padding: 4px 6px;
             selection-background-color: {ACCENT}; }}
QLineEdit:focus {{ border-color: {ACCENT}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    try:   # Qt 6.8+: deixa a barra de título do sistema escura também
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    except AttributeError:
        pass
    pal = QPalette()
    colors = {
        QPalette.Window: TOOLBAR, QPalette.WindowText: TEXT, QPalette.Base: BG,
        QPalette.AlternateBase: SURFACE, QPalette.Text: TEXT, QPalette.Button: CONTROL,
        QPalette.ButtonText: TEXT, QPalette.Highlight: ACCENT, QPalette.HighlightedText: "#FFFFFF",
        QPalette.ToolTipBase: TOOLBAR, QPalette.ToolTipText: TEXT, QPalette.PlaceholderText: TEXT_2,
        QPalette.Link: ACCENT, QPalette.BrightText: RED,
    }
    for role, color in colors.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(TEXT_3))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
