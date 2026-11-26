"""Common code for launcher detectors."""

from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Iterable

from gupdater.core.context import SystemContext, UninstallEntry
from gupdater.core.models import LauncherScan


class Launcher(ABC):
    id: ClassVar[str]
    name: ClassVar[str]
    process_names: ClassVar[tuple[str, ...]] = ()

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
