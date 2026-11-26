"""EA app (and the older Origin): games are found in the Windows programs list."""

from __future__ import annotations

from gupdater.core.context import SystemContext
from gupdater.core.models import Game, GameStatus, LauncherScan
from gupdater.launchers.base import Launcher, check_paths, exe_candidates, is_managed_by_other_launcher

_LAUNCHER_NAMES = {"ea app", "ea desktop", "origin"}


class EA(Launcher):
    id = "ea"
    name = "EA app"
    process_names = ("eadesktop.exe", "eabackgroundservice.exe", "origin.exe")

    def _scan(self, ctx: SystemContext, result: LauncherScan) -> None:
        exe_paths = exe_candidates(
            ctx.env_path("PROGRAMFILES", "Electronic Arts", "EA Desktop", "EA Desktop"), "EADesktop.exe"
        )
        for entry in ctx.uninstall_entries:
            if entry.display_name.lower() in ("ea app", "ea desktop"):
                exe_paths += exe_candidates(entry.install_location, "EA Desktop\\EADesktop.exe", "EADesktop.exe")
        exe = check_paths(result, exe_paths, "EADesktop.exe")
        origin = check_paths(result, exe_candidates(ctx.env_path("PROGRAMFILES(X86)", "Origin"), "Origin.exe"), "Origin.exe")
        if origin:
            result.notes.append("Найден старый лаунчер Origin")

        for entry in ctx.uninstall_entries:
            if entry.display_name.lower() in _LAUNCHER_NAMES or is_managed_by_other_launcher(entry):
                continue
            uninstaller = entry.uninstall_string.lower()
            if "electronic arts" in entry.publisher.lower() or "eainstaller" in uninstaller or "__installer" in uninstaller:
                result.games.append(
                    Game(
                        name=entry.display_name,
                        game_id=entry.key,
                        install_path=entry.install_location or None,
                        version=entry.display_version or None,
                        size_bytes=entry.size_bytes,
                        status=GameStatus.UNKNOWN,
                        note="EA app обновляет игры сам, когда открыт",
                    )
                )

        result.installed = exe is not None or origin is not None
        result.exe_path = str(exe or origin) if (exe or origin) else None
