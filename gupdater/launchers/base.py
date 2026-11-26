"""Common code for launcher detectors."""

from __future__ import annotations

import re
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Iterable

from gupdater.core.context import SystemContext, UninstallEntry
from gupdater.core.models import LauncherScan
from gupdater.core.registry import reg_str


@dataclass(frozen=True)
class LaunchSpec:
    """How the autopilot starts, watches and closes a launcher."""

    command: tuple[str, ...]
    # Processes whose disk/network activity counts as "the launcher is busy".
    process_names: frozenset[str] = frozenset()
    # Processes started from these folders count too (helpers with odd names).
    folders: tuple[str, ...] = ()
    # Polite way to ask the launcher to quit; otherwise its windows get closed.
    close_command: tuple[str, ...] | None = None


@dataclass
class Progress:
    """What a launcher itself says about its updates (None = it does not say)."""

    busy: bool | None = None
    # (game id, game name) still waiting for an update.
    pending: list[tuple[str, str]] = field(default_factory=list)
    logged_in: bool | None = None


class Launcher(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    process_names: ClassVar[tuple[str, ...]] = ()
    # Extra processes that do the downloading for this launcher.
    helper_processes: ClassVar[tuple[str, ...]] = ()
    start_args: ClassVar[tuple[str, ...]] = ()
    # Autopilot skips the launcher when no games were found (False where
    # game detection is incomplete and the launcher may still need a run).
    skip_without_games: ClassVar[bool] = True

    def launch_spec(self, ctx: SystemContext, scan: LauncherScan) -> LaunchSpec | None:
        """None when the launcher's program file is not known."""
        if not scan.exe_path or not Path(scan.exe_path).is_file():
            return None
        exe = Path(scan.exe_path)
        return LaunchSpec(
            command=(str(exe), *self.start_args),
            process_names=frozenset(n.lower() for n in self.process_names + self.helper_processes),
            folders=(str(exe.parent), *self.extra_folders(ctx)),
        )

    def extra_folders(self, ctx: SystemContext) -> tuple[str, ...]:
        return ()

    def progress(self, ctx: SystemContext) -> Progress:
        return Progress()

    def nudge_commands(self, ctx: SystemContext, scan: LauncherScan, pending: list[tuple[str, str]]) -> list[tuple[tuple[str, ...], str]]:
        """Commands that make the launcher start stuck updates: (command, log message)."""
        return []

    def scan(self, ctx: SystemContext) -> LauncherScan:
        result = LauncherScan(launcher_id=self.id, name=self.name)
        try:
            self._scan(ctx, result)
        except Exception as exc:  # one broken detector must not stop the others
            result.error = f"{type(exc).__name__}: {exc}"
            result.evidence.append(traceback.format_exc().strip())
        self._drop_missing_games(result)
        result.running = self.is_running(ctx)
        result.games.sort(key=lambda g: g.name.lower())
        return result

    @staticmethod
    def _drop_missing_games(result: LauncherScan) -> None:
        """Programs lists keep entries of deleted games: a game without its folder is not installed."""
        kept = []
        for game in result.games:
            if game.install_path and not Path(game.install_path).exists():
                result.notes.append(f"«{game.name}» записана в Windows, но её папки нет ({game.install_path}) — похоже, удалена")
            else:
                kept.append(game)
        result.games = kept
        if result.installed and not result.exe_path and not kept:
            result.installed = False

    def is_running(self, ctx: SystemContext) -> bool:
        return ctx.is_running(*self.process_names)

    @abstractmethod
    def _scan(self, ctx: SystemContext, result: LauncherScan) -> None:
        """Fill ``result``: installed/exe_path, games, notes, evidence."""


def check_paths(result: LauncherScan, paths: Iterable[Path | None], label: str) -> Path | None:
    """Return the first existing path and record what was checked."""
    found = None
    seen: set[str] = set()
    for path in paths:
        if path is None or str(path) in seen:
            continue
        seen.add(str(path))
        exists = path.exists()
        result.evidence.append(f"{label}: {'есть' if exists else 'нет'} — {path}")
        if exists and found is None:
            found = path
    return found


def find_entries(ctx: SystemContext, *needles: str) -> list[UninstallEntry]:
    """Programs whose name/publisher/paths mention any of ``needles``."""
    lowered = [n.lower() for n in needles]
    return [e for e in ctx.uninstall_entries if any(n in e.haystack for n in lowered)]


def is_managed_by_other_launcher(entry: UninstallEntry) -> bool:
    """Steam registers its games as "Steam App <id>" with a ``steam://uninstall`` command."""
    return entry.key.lower().startswith("steam app ") or "steam://uninstall" in entry.uninstall_string.lower()


_EXE_IN_COMMAND = re.compile(r'^\s*(?:"([^"]+?\.exe)"|(\S+?\.exe))', re.IGNORECASE)


def exe_from_command(command: str) -> Path | None:
    """The program in a command line such as ``"C:\\x\\setup.exe" /IU``."""
    match = _EXE_IN_COMMAND.match(command or "")
    if not match:
        return None
    return Path(match.group(1) or match.group(2))


def expand_vars(ctx: SystemContext, text: str) -> str:
    """Replace ``%LOCALAPPDATA%`` and the like, as Windows does in registry paths."""
    return re.sub(r"%([^%]+)%", lambda m: ctx.env.get(m.group(1).upper(), m.group(0)), text or "")


def protocol_exe(ctx: SystemContext, scheme: str) -> Path | None:
    """The program a launcher registered for its ``scheme://`` links."""
    command = reg_str(ctx.registry, f"HKCR\\{scheme}\\shell\\open\\command", "")
    return exe_from_command(expand_vars(ctx, command))


def exe_candidates(folder: str | Path | None, *names: str) -> list[Path]:
    if not folder:
        return []
    base = Path(str(folder).strip('"'))
    return [base / name for name in names]
