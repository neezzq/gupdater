"""Warnings about the PC that the admin should see in the window."""

from __future__ import annotations

import os
import sys

from gupdater.core.freeze import freeze_advice
from gupdater.report import ScanResult
from gupdater.settings import data_dir


def environment_warning(result: ScanResult, demo: bool) -> str:
    """Empty when there is nothing to warn about."""
    names = result.inventory.disk_freeze
    if not names:
        return ""
    text = freeze_advice(names)
    folder = data_dir()
    system = os.environ.get("SYSTEMDRIVE", "C:").upper()
    if sys.platform == "win32" and str(folder).upper().startswith(system):
        text += (f" Сейчас настройки и входы GUpdater лежат на системном диске ({folder}) и пропадут при "
                 "откате — переложите GUpdater.exe на диск с играми.")
    return text
