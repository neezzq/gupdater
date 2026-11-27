"""Launcher icons: brand tiles shipped with GUpdater, or the launcher's own icon."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QFileInfo
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider

from gupdater.ui.theme import ASSETS

# Launchers with a brand mark among the shipped tiles (the rest show letters).
_BRAND_TILES = {"steam", "epic", "vkplay", "battlenet", "riot", "ea"}


@lru_cache(maxsize=64)
def _file_icon(exe_path: str) -> QIcon:
    return QFileIconProvider().icon(QFileInfo(exe_path))


@lru_cache(maxsize=16)
def _tile(launcher_id: str) -> QIcon:
    return QIcon(str(ASSETS / "launchers" / f"{launcher_id}.png"))


def launcher_icon(launcher_id: str, exe_path: str | None = None) -> QIcon:
    if launcher_id in _BRAND_TILES:
        return _tile(launcher_id)
    # No shipped mark: the launcher's own icon is better than letters.
    if sys.platform == "win32" and exe_path and Path(exe_path).is_file():
        icon = _file_icon(exe_path)
        if not icon.isNull():
            return icon
    return _tile(launcher_id)
