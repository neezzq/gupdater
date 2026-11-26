"""Lesta Game Center (Мир танков, Мир кораблей, Tanks Blitz).

It is a fork of the Wargaming Game Center, so it is looked for in the same
places; the recon report confirms or corrects that.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from gupdater.core.context import SystemContext, UninstallEntry
from gupdater.core.models import Game, GameStatus, LauncherScan
from gupdater.launchers.base import Launcher, check_paths, exe_candidates

_EXE_NAMES = ("lgc.exe", "lgc_api.exe")


def is_lesta_entry(entry: UninstallEntry) -> bool:
    """Lesta's own programs: judged by name, publisher and uninstaller, not by folder."""
    text = f"{entry.display_name} {entry.publisher} {entry.uninstall_string}".lower()
    return "lesta" in text or "леста" in text


def _is_launcher_entry(display_name: str) -> bool:
    name = display_name.lower()
    return "game center" in name or "игровой центр" in name


def read_game_version(install_path: str) -> str | None:
    """``<version_name>`` from the game's ``game_info.xml``, if there is one."""
    info = Path(install_path) / "game_info.xml"
    if not install_path or not info.is_file():
        return None
    try:
        node = ET.parse(info).getroot().find(".//version_name")
    except (ET.ParseError, OSError):
        return None
    return node.text.strip() if node is not None and node.text else None


class Lesta(Launcher):
    id = "lesta"
    name = "Lesta Game Center"
    process_names = _EXE_NAMES

    def _scan(self, ctx: SystemContext, result: LauncherScan) -> None:
        center = ctx.env_path("PROGRAMDATA", "Lesta", "GameCenter")
        lesta_entries = [e for e in ctx.uninstall_entries if is_lesta_entry(e)]
        folders = [center] + [
            Path(e.install_location) for e in lesta_entries if _is_launcher_entry(e.display_name) and e.install_location
        ]
        exe = check_paths(result, [p for f in folders for p in exe_candidates(f, *_EXE_NAMES)], "lgc.exe")
        if exe:
            result.exe_path = str(exe)
        apps = center / "apps" if center else None
        if apps and apps.is_dir():
            names = sorted(p.name for p in apps.iterdir())
            result.evidence.append(f"GameCenter\\apps: {', '.join(names) or 'пусто'}")

        for entry in lesta_entries:
            if _is_launcher_entry(entry.display_name):
                continue
            result.games.append(
                Game(
                    name=entry.display_name,
                    game_id=entry.key,
                    install_path=entry.install_location or None,
                    version=read_game_version(entry.install_location) or entry.display_version or None,
                    size_bytes=entry.size_bytes,
                    status=GameStatus.UNKNOWN,
                    note="Lesta Game Center обновляет игру сам, когда открыт",
                )
            )

        result.installed = exe is not None or any(_is_launcher_entry(e.display_name) for e in lesta_entries)
