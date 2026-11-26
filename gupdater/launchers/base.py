"""Common code for launcher detectors."""

from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Iterable

from gupdater.core.context import SystemContext, UninstallEntry
from gupdater.core.models import LauncherScan


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
        result.running = self.is_running(ctx)
        result.games.sort(key=lambda g: g.name.lower())
        return result

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


def exe_candidates(folder: str | Path | None, *names: str) -> list[Path]:
    if not folder:
        return []
    base = Path(str(folder).strip('"'))
    return [base / name for name in names]
