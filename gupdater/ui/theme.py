"""Graphite "liquid glass" look: dark graphite backdrop, translucent glass panels."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QLinearGradient,
    QPainter,
    QPalette,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

ASSETS = Path(__file__).resolve().parent.parent / "assets"

TEXT = "#ECEEF2"
TEXT_2 = "#9AA0AA"
TEXT_3 = "#6B7079"
ACCENT = "#0A84FF"

_QSS = """
* { color: %(text)s; }
QToolTip { background: #2A2D33; color: %(text)s; border: 1px solid rgba(255,255,255,40); border-radius: 8px; padding: 6px; }
QLabel#Muted { color: %(text2)s; }
QLabel#Title { font-size: 21pt; font-weight: 800; }
QLabel#Section { font-weight: 700; color: #C9CDD4; }
QListWidget#Cards { background: transparent; border: none; outline: none; }
QListWidget#Cards::item { background: transparent; border: none; }
QListWidget#Cards::item:selected, QListWidget#Cards::item:hover { background: transparent; }
QFrame#Row { background: rgba(255,255,255,14); border: 1px solid rgba(255,255,255,24); border-radius: 16px; }
QFrame#Row:hover { background: rgba(255,255,255,22); border-color: rgba(255,255,255,40); }
QFrame#Row QLabel { background: transparent; }
QPushButton#Round { border-radius: 16px; min-width: 32px; max-width: 32px; min-height: 32px; max-height: 32px;
                    padding: 0; font-size: 11pt; }
QLabel#Warning { background: rgba(255,159,10,28); border: 1px solid rgba(255,159,10,96); border-radius: 12px;
                 padding: 8px 12px; color: #FFD9A0; }
QLabel#Chip { background: rgba(255,255,255,20); border: 1px solid rgba(255,255,255,31); border-radius: 10px;
              padding: 2px 10px; color: #C9CDD4; }

QGroupBox { background: rgba(255,255,255,14); border: 1px solid rgba(255,255,255,26); border-radius: 16px;
            margin-top: 16px; padding: 16px 12px 10px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; top: 2px; padding: 0 4px; color: #C9CDD4; }
QFrame#Glass { background: rgba(255,255,255,14); border: 1px solid rgba(255,255,255,26); border-radius: 16px; }

QPushButton { font-weight: 600; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,42), stop:1 rgba(255,255,255,18));
              border: 1px solid rgba(255,255,255,42); border-radius: 12px; padding: 7px 16px; }
QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,60), stop:1 rgba(255,255,255,26));
                    border-color: rgba(255,255,255,64); }
QPushButton:pressed { background: rgba(255,255,255,16); }
QPushButton:disabled { color: rgba(236,238,242,90); background: rgba(255,255,255,10); border-color: rgba(255,255,255,16); }
QPushButton#Primary { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFFFFF, stop:1 #D6DAE0);
                      color: #15171A; border: 1px solid rgba(255,255,255,160); font-weight: 600; }
QPushButton#Primary:hover { background: #FFFFFF; }
QPushButton#Primary:disabled { background: rgba(255,255,255,60); color: rgba(21,23,26,140); }
QPushButton#Accent { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3D9BFF, stop:1 #0A6FE0);
                     border: 1px solid rgba(120,180,255,160); font-weight: 600; color: #FFFFFF; }

QTabWidget::pane { border: none; top: 8px; }
QTabBar::tab { background: transparent; color: %(text2)s; padding: 8px 20px; margin-right: 6px; font-weight: 700;
               border-radius: 12px; border: 1px solid transparent; }
QTabBar::tab:selected { background: rgba(255,255,255,32); color: #FFFFFF; border: 1px solid rgba(255,255,255,42); }
QTabBar::tab:hover:!selected { color: #D8DBE0; background: rgba(255,255,255,12); }

QTableWidget, QTreeWidget, QPlainTextEdit, QListWidget {
    background: rgba(0,0,0,46); border: 1px solid rgba(255,255,255,20); border-radius: 12px;
    alternate-background-color: rgba(255,255,255,8); gridline-color: transparent;
    selection-background-color: rgba(10,132,255,90); selection-color: #FFFFFF; }
QHeaderView { background: transparent; }
QHeaderView::section { background: transparent; color: %(text2)s; border: none;
                       border-bottom: 1px solid rgba(255,255,255,20); padding: 6px 8px; font-weight: 600; }
QTableCornerButton::section { background: transparent; border: none; }
QTableView::item, QTreeView::item { padding: 3px 6px; border: none; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator, QTableView::indicator { width: 18px; height: 18px; border-radius: 6px;
    border: 1px solid rgba(255,255,255,72); background: rgba(255,255,255,15); }
QCheckBox::indicator:hover, QTableView::indicator:hover { border-color: rgba(255,255,255,120); }
QCheckBox::indicator:checked, QTableView::indicator:checked { background: %(accent)s; border-color: %(accent)s;
    image: url(%(check)s); }

QLineEdit { background: rgba(255,255,255,18); border: 1px solid rgba(255,255,255,31); border-radius: 10px;
            padding: 6px 10px; selection-background-color: %(accent)s; }
QLineEdit:focus { border-color: rgba(10,132,255,200); }
QSpinBox, QTimeEdit { background: rgba(255,255,255,18); border: 1px solid rgba(255,255,255,31); border-radius: 10px;
                      padding: 4px 8px; min-height: 22px; selection-background-color: %(accent)s; }
QSpinBox:focus, QTimeEdit:focus { border-color: rgba(10,132,255,200); }
QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {
    width: 20px; border: none; background: transparent; }
QSpinBox::up-arrow, QTimeEdit::up-arrow { image: url(%(up)s); width: 10px; height: 10px; }
QSpinBox::down-arrow, QTimeEdit::down-arrow { image: url(%(down)s); width: 10px; height: 10px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 3px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 3px; }
QScrollBar::handle { background: rgba(255,255,255,46); border-radius: 4px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:hover { background: rgba(255,255,255,80); }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QStatusBar { color: %(text2)s; background: transparent; }
QStatusBar::item { border: none; }
QProgressBar { background: rgba(255,255,255,20); border: none; border-radius: 6px; min-height: 10px; max-height: 10px;
               text-align: center; color: transparent; }
QProgressBar::chunk { background: %(accent)s; border-radius: 6px; }
QDialog, QMessageBox, QProgressDialog { background: #1C1E22; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#17181C",
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: "#1E2025",
        QPalette.ColorRole.AlternateBase: "#24262B",
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: "#2A2C31",
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: "#2A2D33",
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_3,
        QPalette.ColorRole.Link: ACCENT,
        QPalette.ColorRole.BrightText: "#FFFFFF",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_3))
    app.setPalette(palette)

    family = load_fonts()
    font = QFont(family or ("Segoe UI" if sys.platform == "win32" else app.font().family()))
    font.setPointSizeF(10)
    font.setWeight(QFont.Weight.Medium)
    app.setFont(font)
    app.setStyleSheet(_QSS % {
        "text": TEXT, "text2": TEXT_2, "accent": ACCENT, "check": (ASSETS / "check.png").as_posix(),
        "up": (ASSETS / "arrow-up.png").as_posix(), "down": (ASSETS / "arrow-down.png").as_posix(),
    })
    app.setWindowIcon(app_icon())


def load_fonts() -> str | None:
    """Inter (SIL Open Font License), shipped in assets/fonts; returns its family name."""
    family = None
    for path in sorted((ASSETS / "fonts").glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        family = family or (families[0] if families else None)
    return family


def app_icon() -> QIcon:
    icon = QIcon()
    for name in ("logo-256.png", "logo.png"):
        path = ASSETS / name
        if path.is_file():
            icon.addFile(str(path))
    return icon


def logo_pixmap(size: int, ratio: float = 1.0) -> QPixmap:
    pixmap = QPixmap(str(ASSETS / "logo-256.png"))
    if pixmap.isNull():
        return pixmap
    scaled = pixmap.scaled(int(size * ratio), int(size * ratio), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    scaled.setDevicePixelRatio(ratio)
    return scaled


class Backdrop(QWidget):
    """Graphite background with soft coloured light behind the glass panels."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        base = QLinearGradient(QPointF(0, 0), QPointF(0, rect.height()))
        base.setColorAt(0.0, QColor("#24262C"))
        base.setColorAt(1.0, QColor("#111215"))
        painter.fillRect(rect, base)
        w, h = rect.width(), rect.height()
        for (x, y, radius, color) in (
            (0.12, 0.05, 0.55, QColor(90, 120, 255, 46)),
            (0.92, 0.18, 0.45, QColor(170, 110, 255, 26)),
            (0.85, 0.95, 0.55, QColor(40, 200, 180, 24)),
            (0.30, 0.90, 0.40, QColor(255, 150, 90, 12)),
        ):
            center = QPointF(x * w, y * h)
            glow = QRadialGradient(center, radius * max(w, h))
            glow.setColorAt(0.0, color)
            transparent = QColor(color)
            transparent.setAlpha(0)
            glow.setColorAt(1.0, transparent)
            painter.fillRect(rect, glow)
        painter.end()


def dark_title_bar(widget: QWidget) -> None:
    """Make the Windows title bar dark to match the window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (newer, older Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except (OSError, AttributeError):
        pass
