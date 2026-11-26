"""Battle.net: games are found through their "Blizzard Uninstaller" entries."""

from __future__ import annotations

import re

from gupdater.core.context import SystemContext
from gupdater.core.models import Game, GameStatus, LauncherScan
from gupdater.launchers.base import Launcher, check_paths, exe_candidates, protocol_exe

_UID = re.compile(r"--uid=([\w.-]+)")
_EXE_NAMES = ("Battle.net Launcher.exe", "Battle.net.exe")


class BattleNet(Launcher):
    id = "battlenet"
    name = "Battle.net"
    process_names = ("battle.net.exe",)

    def extra_folders(self, ctx: SystemContext) -> tuple[str, ...]:
        # Downloads are done by Agent.exe, which lives in ProgramData.
        agent = ctx.env_path("PROGRAMDATA", "Battle.net")
        return (str(agent),) if agent else ()

    def _scan(self, ctx: SystemContext, result: LauncherScan) -> None:
        exe_paths = []
        for entry in ctx.uninstall_entries:
            if entry.display_name.lower() == "battle.net":
                exe_paths += exe_candidates(entry.install_location, *_EXE_NAMES)
        handler = protocol_exe(ctx, "battlenet")
        if handler:
            exe_paths += exe_candidates(handler.parent, *_EXE_NAMES)
        for var in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            exe_paths += exe_candidates(ctx.env_path(var, "Battle.net"), *_EXE_NAMES)
        exe = check_paths(result, exe_paths, "Battle.net")
        agent_db = check_paths(result, [ctx.env_path("PROGRAMDATA", "Battle.net", "Agent", "product.db")], "product.db")

        for entry in ctx.uninstall_entries:
            uninstaller = entry.uninstall_string.lower()
            if entry.display_name.lower() == "battle.net":
                continue
            if "blizzard uninstaller" not in uninstaller and "battle.net" not in uninstaller:
                continue
            uid = _UID.search(entry.uninstall_string)
            result.games.append(
                Game(
                    name=entry.display_name,
                    game_id=uid.group(1) if uid else entry.key,
                    install_path=entry.install_location or None,
                    version=entry.display_version or None,
                    size_bytes=entry.size_bytes,
                    status=GameStatus.UNKNOWN,
                    note="Battle.net обновляет игры сам, когда открыт",
                )
            )

        result.installed = exe is not None or agent_db is not None or bool(result.games)
        if exe:
            result.exe_path = str(exe)
