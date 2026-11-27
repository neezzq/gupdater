"""Render launcher icon tiles and small UI glyphs to PNG (results are committed).

Brand marks come from Simple Icons (CC0, scripts/brand-icons); the brands
themselves belong to their owners and are shown only to name the launcher.
    QT_QPA_PLATFORM=offscreen python scripts/make_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
BRANDS = ROOT / "scripts" / "brand-icons"
ASSETS = ROOT / "gupdater" / "assets"

# launcher id -> (Simple Icons slug or None, tile colour, monogram when there is no mark)
TILES = {
    "steam": ("steam", "#1B2838", ""),
    "epic": ("epicgames", "#2B2B2E", ""),
    "vkplay": ("vk", "#0077FF", ""),
    "battlenet": ("battledotnet", "#148EFF", ""),
    "riot": ("riotgames", "#D13639", ""),
    "ea": ("ea", "#FF4747", ""),
    "lesta": (None, "#E0A100", "L"),
    "iccup": (None, "#2E8B57", "iC"),
}


def tile(color: str, size: int) -> tuple[QImage, QPainter, QRectF]:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(size * 0.03, size * 0.03, size * 0.94, size * 0.94)
    path = QPainterPath()
    path.addRoundedRect(rect, size * 0.23, size * 0.23)
    base = QColor(color)
    fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    fill.setColorAt(0, base.lighter(130))
    fill.setColorAt(1, base.darker(135))
    painter.fillPath(path, fill)
    gloss = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gloss.setColorAt(0, QColor(255, 255, 255, 64))
    gloss.setColorAt(0.55, QColor(255, 255, 255, 0))
    painter.fillPath(path, gloss)
    painter.setPen(QColor(255, 255, 255, 56))
    painter.drawPath(path)
    return image, painter, rect


def white_mark(svg: bytes, size: int) -> QImage:
    renderer = QSvgRenderer(QByteArray(svg))
    mark = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    mark.fill(Qt.GlobalColor.transparent)
    p = QPainter(mark)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(mark.rect(), QColor("#FFFFFF"))
    p.end()
    return mark


def launcher_tile(launcher_id: str, size: int = 128) -> QImage:
    slug, color, letters = TILES[launcher_id]
    image, painter, rect = tile(color, size)
    if slug:
        mark_size = int(size * 0.56)
        mark = white_mark((BRANDS / f"{slug}.svg").read_bytes(), mark_size)
        offset = (size - mark_size) / 2
        painter.drawImage(int(offset), int(offset), mark)
    else:
        font = QFont("Inter")
        font.setWeight(QFont.Weight.ExtraBold)
        font.setPixelSize(int(size * (0.5 if len(letters) == 1 else 0.4)))
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, letters)
    painter.end()
    return image


def glyph(svg_path: Path, size: int) -> QImage:
    renderer = QSvgRenderer(str(svg_path))
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return image


def main() -> None:
    app = QGuiApplication(sys.argv[:1])
    from PySide6.QtGui import QFontDatabase

    for font in (ASSETS / "fonts").glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(font))
    out = ASSETS / "launchers"
    out.mkdir(exist_ok=True)
    for launcher_id in TILES:
        launcher_tile(launcher_id).save(str(out / f"{launcher_id}.png"))
    for name, size in (("check", 36), ("arrow-up", 20), ("arrow-down", 20)):
        glyph(ASSETS / f"{name}.svg", size).save(str(ASSETS / f"{name}.png"))
    print("written to", out)
    del app


if __name__ == "__main__":
    main()
