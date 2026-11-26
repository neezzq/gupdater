"""Daily automatic run through the Windows Task Scheduler.

The task runs as the signed-in Windows user (only while that user is signed
in), because launchers need the user's desktop and the user's logins.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TASK_NAME = "GUpdater Autopilot"
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
CREATE_NO_WINDOW = 0x08000000


class SchedulerError(Exception):
    pass


def task_command(exe: Path) -> str:
    return f'"{exe}" --autopilot'


def create_args(exe: Path, start_time: str) -> list[str]:
    if not _TIME.match(start_time):
        raise SchedulerError(f"Неверное время «{start_time}», нужно ЧЧ:ММ, например 05:00")
    return ["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", start_time, "/TN", TASK_NAME, "/TR", task_command(exe)]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    if sys.platform != "win32":
        raise SchedulerError("Расписание работает только в Windows")
    try:
        return subprocess.run(
            args, capture_output=True, text=True, encoding="oem", errors="replace",
            creationflags=CREATE_NO_WINDOW, check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SchedulerError(f"Не удалось вызвать планировщик Windows: {exc}") from exc


def create_task(exe: Path, start_time: str) -> None:
    result = _run(create_args(exe, start_time))
    if result.returncode != 0:
        raise SchedulerError((result.stderr or result.stdout).strip() or f"schtasks вернул {result.returncode}")


def delete_task() -> None:
    if task_exists():
        result = _run(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
        if result.returncode != 0:
            raise SchedulerError((result.stderr or result.stdout).strip())


def task_exists() -> bool:
    if sys.platform != "win32":
        return False
    return _run(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0
