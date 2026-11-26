"""The text report written after every autopilot run."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Sequence

from gupdater import __version__
from gupdater.autopilot.engine import LauncherRun, Outcome, format_duration
from gupdater.core.models import format_size

_SUMMARY_ORDER = (
    (Outcome.UPDATED, "обновлено"),
    (Outcome.NOTHING, "обновлять нечего"),
    (Outcome.NOT_FINISHED, "обновилось не всё"),
    (Outcome.TIMEOUT, "не дождался"),
    (Outcome.FAILED, "ошибок"),
    (Outcome.SKIPPED, "пропущено"),
    (Outcome.STOPPED, "остановлено"),
)


def summary_line(runs: Sequence[LauncherRun]) -> str:
    counts = Counter(r.outcome for r in runs if r.outcome)
    parts = [f"{label} {counts[o]}" for o, label in _SUMMARY_ORDER if counts[o]]
    return " · ".join(parts) or "ничего не запускалось"


def build_run_report(
    runs: Sequence[LauncherRun], log_lines: Sequence[str], started: float, finished: float, computer: str, note: str = ""
) -> str:
    fmt = "%Y-%m-%d %H:%M"
    lines = [
        f"GUpdater {__version__} — автопилот",
        f"Компьютер: {computer}",
        f"Начало: {time.strftime(fmt, time.localtime(started))}, конец: {time.strftime(fmt, time.localtime(finished))}"
        f" ({format_duration(finished - started)})",
        f"Итог: {summary_line(runs)}",
    ]
    if note:
        lines.append(note)
    lines.append("")
    for run in runs:
        head = f"[{run.outcome.text if run.outcome else 'Не запускался'}] {run.name}"
        details = []
        if run.duration_s and run.outcome not in (Outcome.SKIPPED, None):
            details.append(format_duration(run.duration_s))
        if run.written_bytes >= 1024 * 1024:
            details.append(f"записано на диск ≈{format_size(run.written_bytes)}")
        if run.message:
            details.append(run.message)
        lines.append(head + (" — " + ", ".join(details) if details else ""))
        lines += [f"    {change}" for change in run.changes]
    lines += ["", "--- Журнал ---", *log_lines]
    return "\n".join(lines) + "\n"


def save_run_report(text: str, folder: Path, started: float) -> Path:
    path = folder / f"автопилот-{time.strftime('%Y%m%d-%H%M%S', time.localtime(started))}.txt"
    path.write_text(text, encoding="utf-8-sig")
    return path


def latest_report(folder: Path) -> Path | None:
    reports = sorted(folder.glob("автопилот-*.txt"))
    return reports[-1] if reports else None
