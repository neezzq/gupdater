"""The parts of the autopilot that touch the real computer.

The engine only talks to a ``System``; tests give it a fake one with a
simulated clock and simulated launchers.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence

_WINDOWS = sys.platform == "win32"
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    name: str            # lower-case, e.g. "steam.exe"
    exe: str | None      # full path, when readable
    create_time: float   # seconds since the epoch
    # Bytes read / written so far (disk and network), None when not readable.
    read_bytes: int | None = None
    write_bytes: int | None = None


class System(Protocol):
    def now(self) -> float:
        """Monotonic seconds."""

    def wall_time(self) -> float:
        """Seconds since the epoch."""

    def sleep(self, seconds: float, stop: threading.Event) -> bool:
        """Wait; False if ``stop`` was set meanwhile."""

    def start(self, command: Sequence[str]) -> None:
        """Start a program and do not wait for it (raises OSError)."""

    def processes(self) -> list[ProcInfo]:
        ...

    def close(self, names: Iterable[str], force: bool) -> None:
        """Ask processes to quit (force: kill them)."""

    def idle_seconds(self) -> float | None:
        """Time since the last mouse/keyboard input, None if unknown."""


def clean_child_env() -> dict[str, str]:
    """Environment for programs we start, without GUpdater's own runtime settings.

    A frozen GUpdater.exe runs from a temporary folder with its own Qt; a
    launcher built on Qt (Battle.net, EA app) must not pick that Qt up, and a
    new GUpdater.exe must start as a fresh program.
    """
    env = dict(os.environ)
    bundle = getattr(sys, "_MEIPASS", None)
    for key in list(env):
        upper = key.upper()
        if upper.startswith(("_PYI_", "_MEIPASS")) or upper in ("QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
            del env[key]
    if bundle and "PATH" in env:
        bundle_norm = os.path.normcase(os.path.normpath(bundle))
        env["PATH"] = os.pathsep.join(
            p for p in env["PATH"].split(os.pathsep) if not os.path.normcase(os.path.normpath(p)).startswith(bundle_norm)
        )
    if getattr(sys, "frozen", False):
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def start_detached(command: Sequence[str]) -> None:
    kwargs: dict = {"env": clean_child_env(), "close_fds": True, "stdin": subprocess.DEVNULL,
                    "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if _WINDOWS:
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(list(command), **kwargs)


class RealSystem:
    def now(self) -> float:
        return time.monotonic()

    def wall_time(self) -> float:
        return time.time()

    def sleep(self, seconds: float, stop: threading.Event) -> bool:
        return not stop.wait(seconds)

    def start(self, command: Sequence[str]) -> None:
        start_detached(command)

    def processes(self) -> list[ProcInfo]:
        import psutil

        result = []
        for proc in psutil.process_iter(["pid", "name", "exe", "create_time"]):
            info = proc.info
            if not info.get("name"):
                continue
            try:
                counters = proc.io_counters()
                read, written = counters.read_bytes, counters.write_bytes
            except (psutil.Error, AttributeError, OSError):
                read = written = None
            result.append(
                ProcInfo(
                    pid=info["pid"],
                    name=info["name"].lower(),
                    exe=info.get("exe"),
                    create_time=info.get("create_time") or 0.0,
                    read_bytes=read,
                    write_bytes=written,
                )
            )
        return result

    def close(self, names: Iterable[str], force: bool) -> None:
        names = {n.lower() for n in names}
        if _WINDOWS:
            for name in names:
                command = ["taskkill", "/IM", name] + (["/F", "/T"] if force else [])
                subprocess.run(command, capture_output=True, creationflags=CREATE_NO_WINDOW, check=False)
            return
        import psutil

        for proc in psutil.process_iter(["name"]):
            if (proc.info.get("name") or "").lower() in names:
                try:
                    proc.kill() if force else proc.terminate()
                except psutil.Error:
                    pass

    def idle_seconds(self) -> float | None:
        if not _WINDOWS:
            return None
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        now_ms = ctypes.windll.kernel32.GetTickCount()
        return ((now_ms - info.dwTime) & 0xFFFFFFFF) / 1000.0
