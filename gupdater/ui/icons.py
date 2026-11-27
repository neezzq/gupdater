"""Launcher icons: the launcher's own icon from its program file, or a glass monogram."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QFileInfo, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFileIconProvider

# Monogram and tile colour for launchers whose program file is not at hand.
_MONOGRAMS = {
    "steam": ("S", "#2A475E"),
    "epic": ("E", "#3A3A3C"),
    "vkplay": ("VK", "#0077FF"),
    "battlenet": ("B", "#148EFF"),
    "riot": ("R", "#D13639"),
    "ea": ("EA", "#E8423F"),
    "lesta": ("L", "#D9890B"),
    "iccup": ("iC", "#2E8B57"),
}


@lru_cache(maxsize=64)
def _file_icon(exe_path: str) -> QIcon:
    return QFileIconProvider().icon(QFileInfo(exe_path))


@lru_cache(maxsize=16)
def monogram(launcher_id: str, size: int = 64) -> QIcon:
    text, color = _MONOGRAMS.get(launcher_id, (launcher_id[:1].upper(), "#5A5E66"))
    base = QColor(color)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(2, 2, size - 4, size - 4)
    path = QPainterPath()
    path.addRoundedRect(rect, size * 0.24, size * 0.24)
    fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    fill.setColorAt(0, base.lighter(135))
    fill.setColorAt(1, base.darker(150))
    painter.fillPath(path, fill)
    gloss = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gloss.setColorAt(0, QColor(255, 255, 255, 70))
    gloss.setColorAt(0.5, QColor(255, 255, 255, 0))
    painter.fillPath(path, gloss)
    painter.setPen(QColor(255, 255, 255, 60))
    painter.drawPath(path)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(int(size * (0.46 if len(text) == 1 else 0.34)))
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(pixmap)


def launcher_icon(launcher_id: str, exe_path: str | None = None) -> QIcon:
    """The launcher's own icon on Windows when its program is found, otherwise a monogram tile."""
    if sys.platform == "win32" and exe_path and Path(exe_path).is_file():
        icon = _file_icon(exe_path)
        if not icon.isNull():
            return icon
    return monogram(launcher_id)
