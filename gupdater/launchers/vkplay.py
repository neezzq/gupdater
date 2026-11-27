"""VK Play (formerly the Mail.ru / MY.GAMES "Game Center").

Where VK Play keeps its list of games is not known yet, so this detector is
deliberately broad: the recon report shows what it matched and why, and the
detection gets narrowed once real club PCs have been looked at.
"""

from __future__ import annotations

from pathlib import Path

from gupdater.core.context import SystemContext
from gupdater.core.models import Game, GameStatus, LauncherScan
from gupdater.launchers.base import Launcher, check_paths, exe_candidates, find_entries, protocol_exe
from gupdater.launchers.lesta import is_lesta_entry
from gupdater.logins import LearnAreas

_LAUNCHER_WORDS = ("vk play", "vkplay", "game center", "gamecenter", "игровой центр")
_EXE_NAMES = ("GameCenter.exe", "VKPlay.exe", "VK Play.exe", "VKPlayLoader.exe")


def _is_launcher_entry(display_name: str) -> bool:
    name = display_name.lower()
    return any(word in name for word in _LAUNCHER_WORDS) and not any(w in name for w in ("lesta", "wargaming"))


class VKPlay(Launcher):
    id = "vkplay"
    name = "VK Play"
    process_names = ("gamecenter.exe", "vkplay.exe", "vk play.exe", "vkplayloader.exe")
    program_names = ("vk play игровой центр", "vk play")

    def learn_areas(self, ctx: SystemContext, scan: LauncherScan) -> LearnAreas:
        folders = [ctx.env_path("LOCALAPPDATA", "GameCenter"), ctx.env_path("APPDATA", "GameCenter"),
                   ctx.env_path("LOCALAPPDATA", "VK Play"), ctx.env_path("APPDATA", "VK Play")]
        return LearnAreas(folders=tuple(str(f) for f in folders if f), registry_keys=(r"HKCU\Software\GameCenter", r"HKCU\Software\VK", r"HKCU\Software\Mail.Ru"))

    def _scan(self, ctx: SystemContext, result: LauncherScan) -> None:
        folders: list[Path | None] = [
            ctx.env_path("LOCALAPPDATA", "GameCenter"),
            ctx.env_path("LOCALAPPDATA", "VK Play"),
            ctx.env_path("PROGRAMFILES(X86)", "VK Play"),
            ctx.env_path("PROGRAMFILES", "VK Play"),
        ]
        launcher_entries = [e for e in ctx.uninstall_entries if _is_launcher_entry(e.display_name)]
        folders += [Path(e.install_location) for e in launcher_entries if e.install_location]
        exe_paths = [protocol_exe(ctx, "vkplay")]
        exe_paths += [p for folder in folders for p in exe_candidates(folder, *_EXE_NAMES)]
        exe = check_paths(result, exe_paths, "лаунчер VK Play")
        for entry in launcher_entries:
            result.evidence.append(f"программа: {entry.display_name} ({entry.publisher}) — {entry.install_location}")

        for entry in find_entries(ctx, "gcgame_", "gamecenter", "vkplay", "vk play"):
            if _is_launcher_entry(entry.display_name) or is_lesta_entry(entry):
                continue
            result.games.append(
                Game(
                    name=entry.display_name,
                    game_id=entry.key,
                    install_path=entry.install_location or None,
                    version=entry.display_version or None,
                    size_bytes=entry.size_bytes,
                    status=GameStatus.UNKNOWN,
                    note="найдена по списку программ Windows",
                )
            )

        result.installed = exe is not None or bool(launcher_entries)
        if exe:
            result.exe_path = str(exe)
