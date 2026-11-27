"""iCCup launcher (Warcraft III / DotA ladder).

iCCup is usually unpacked into a folder rather than installed, so besides the
programs list a few common folders on every disk are checked.
"""

from __future__ import annotations

from pathlib import Path

from gupdater.core.context import SystemContext
from gupdater.core.models import Game, GameStatus, LauncherScan
from gupdater.launchers.base import Launcher, check_paths, find_entries
from gupdater.logins import LearnAreas

_WAR3_EXES = ("war3.exe", "warcraft iii.exe", "frozen throne.exe")


class ICCup(Launcher):
    id = "iccup"
    name = "iCCup"
    # The launcher updates itself and its maps even when no game folder was recognised.
    skip_without_games = False

    def learn_areas(self, ctx: SystemContext, scan: LauncherScan) -> LearnAreas:
        folders = [Path(scan.exe_path).parent if scan.exe_path else None]
        return LearnAreas(folders=tuple(str(f) for f in folders if f), registry_keys=(r"HKCU\Software\iCCup",))

    def is_running(self, ctx: SystemContext) -> bool:
        return any("iccup" in name for name in ctx.running)

    def _scan(self, ctx: SystemContext, result: LauncherScan) -> None:
        entries = find_entries(ctx, "iccup")
        candidates: list[Path | None] = [Path(e.install_location) for e in entries if e.install_location]
        for parts in (("iCCup",), ("Games", "iCCup"), ("Program Files (x86)", "iCCup"), ("Program Files", "iCCup")):
            candidates += ctx.drive_paths(*parts)
        folder = check_paths(result, candidates, "папка iCCup")
        for entry in entries:
            result.evidence.append(f"программа: {entry.display_name} ({entry.publisher}) — {entry.install_location}")

        result.installed = folder is not None or bool(entries)
        if folder is None or not folder.is_dir():
            return

        exes = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".exe")
        result.evidence.append(f"exe в папке: {', '.join(p.name for p in exes) or 'нет'}")
        launcher = next((p for p in exes if "iccup" in p.name.lower()), None) or next(
            (p for p in exes if "launcher" in p.name.lower()), None
        )
        result.exe_path = str(launcher or folder)

        war3 = self._find_war3(folder)
        if war3:
            result.games.append(
                Game(
                    name="Warcraft III (iCCup)",
                    game_id="war3",
                    install_path=str(war3.parent),
                    status=GameStatus.UNKNOWN,
                    note="iCCup проверяет обновления при запуске",
                )
            )

    @staticmethod
    def _find_war3(folder: Path) -> Path | None:
        for directory in [folder, *(p for p in folder.iterdir() if p.is_dir())]:
            try:
                children = list(directory.iterdir())
            except OSError:
                continue
            for child in children:
                if child.is_file() and child.name.lower() in _WAR3_EXES:
                    return child
        return None
