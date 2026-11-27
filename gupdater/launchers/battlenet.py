"""Battle.net: games are found through their "Blizzard Uninstaller" entries."""

from __future__ import annotations

import re
from pathlib import Path

from gupdater.core import protobuf
from gupdater.core.context import SystemContext
from gupdater.core.models import Game, GameStatus, LauncherScan
from gupdater.launchers.base import Launcher, check_paths, exe_candidates, protocol_exe
from gupdater.logins import LearnAreas, SessionSpec

_UID = re.compile(r"--uid=([\w.-]+)")
_VERSION = re.compile(r"^\d+(\.\d+){2,3}$")


def product_versions(product_db: Path) -> dict[str, str]:
    """Installed version of each Battle.net product, by uid ("hs_beta": "33.2.0.230002").

    product.db holds one message per installed product (field 1), starting with
    its uid (field 1); the version is the first "1.2.3.4"-like string inside.
    """
    try:
        data = product_db.read_bytes()
    except OSError:
        return {}
    versions: dict[str, str] = {}
    for number, wire, value in protobuf.fields(data) or []:
        if number != 1 or wire != 2:
            continue
        install = protobuf.fields(value) or []
        uid = next((protobuf.text(v) for n, w, v in install if n == 1 and w == 2), None)
        version = next((s for s in protobuf.strings(value) if _VERSION.match(s)), None)
        if uid and version:
            versions[uid] = version
    return versions
_EXE_NAMES = ("Battle.net Launcher.exe", "Battle.net.exe")


class BattleNet(Launcher):
    id = "battlenet"
    name = "Battle.net"
    process_names = ("battle.net.exe",)
    program_names = ("battle.net",)

    def extra_folders(self, ctx: SystemContext) -> tuple[str, ...]:
        # Downloads are done by Agent.exe, which lives in ProgramData.
        agent = ctx.env_path("PROGRAMDATA", "Battle.net")
        return (str(agent),) if agent else ()

    login_hint = "Войдите под аккаунтом клуба и отметьте «Запомнить меня»."

    def session_spec(self, ctx: SystemContext, scan: LauncherScan) -> SessionSpec:
        config = ctx.env_path("APPDATA", "Battle.net", "Battle.net.config")
        return SessionSpec(files=(str(config),) if config else ())

    def learn_areas(self, ctx: SystemContext, scan: LauncherScan) -> LearnAreas:
        folders = [ctx.env_path("APPDATA", "Battle.net"), ctx.env_path("LOCALAPPDATA", "Battle.net")]
        return LearnAreas(
            folders=tuple(str(f) for f in folders if f),
            registry_keys=(r"HKCU\Software\Blizzard Entertainment\Battle.net",),
        )

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
        versions = product_versions(agent_db) if agent_db else {}
        if agent_db:
            result.evidence.append(f"версии из product.db: {versions or 'не прочитаны'}")

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
                    version=versions.get(uid.group(1) if uid else "") or entry.display_version or None,
                    size_bytes=entry.size_bytes,
                    status=GameStatus.UNKNOWN,
                    note="Battle.net обновляет игры сам, когда открыт",
                )
            )

        result.installed = exe is not None or agent_db is not None or bool(result.games)
        if exe:
            result.exe_path = str(exe)
