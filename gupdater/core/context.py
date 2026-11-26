"""Everything a scan reads about the computer, in one object.

Launcher detectors never touch ``os.environ``, the registry or the process
list directly: they ask a ``SystemContext``. On a real PC it is built by
``SystemContext.detect()``; tests and the demo build one over a temporary
folder with a fake registry.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import sys
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Mapping

from gupdater.core.registry import Registry, reg_str, system_registry

UNINSTALL_ROOTS = (
    r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall",
)


@dataclass(frozen=True)
class UninstallEntry:
    """One program from Windows' "Apps & features" list."""

    key: str
    display_name: str
    publisher: str = ""
    install_location: str = ""
    display_version: str = ""
    uninstall_string: str = ""
    estimated_size_kb: int | None = None

    @property
    def haystack(self) -> str:
        """All text fields, lower-cased, for keyword matching."""
        return " | ".join(
            (self.key, self.display_name, self.publisher, self.install_location, self.uninstall_string)
        ).lower()

    @property
    def size_bytes(self) -> int | None:
        return self.estimated_size_kb * 1024 if self.estimated_size_kb else None


def read_uninstall_entries(registry: Registry) -> list[UninstallEntry]:
    entries: list[UninstallEntry] = []
    seen: set[tuple[str, str]] = set()
    for root in UNINSTALL_ROOTS:
        for key in registry.subkeys(root):
            path = f"{root}\\{key}"
            name = reg_str(registry, path, "DisplayName")
            if not name or (key.lower(), name.lower()) in seen:
                continue
            seen.add((key.lower(), name.lower()))
            size = registry.values(path).get("EstimatedSize")
            entries.append(
                UninstallEntry(
                    key=key,
                    display_name=name,
                    publisher=reg_str(registry, path, "Publisher"),
                    install_location=reg_str(registry, path, "InstallLocation").strip('"'),
                    display_version=reg_str(registry, path, "DisplayVersion"),
                    uninstall_string=reg_str(registry, path, "UninstallString"),
                    estimated_size_kb=size if isinstance(size, int) and size > 0 else None,
                )
            )
    return entries


@dataclass
class SystemContext:
    registry: Registry
    # Environment variables with upper-case names (PROGRAMDATA, LOCALAPPDATA, ...).
    env: Mapping[str, str]
    # Roots of the local fixed disks, e.g. ["C:\\", "D:\\"].
    drives: list[str] = field(default_factory=list)
    # Lower-case names of running processes, e.g. {"steam.exe"}.
    running: frozenset[str] = frozenset()
    is_windows: bool = True
    computer_name: str = ""
    os_name: str = ""

    def env_path(self, name: str, *parts: str) -> Path | None:
        base = self.env.get(name.upper())
        return Path(base, *parts) if base else None

    def drive_paths(self, *parts: str) -> list[Path]:
        return [Path(drive, *parts) for drive in self.drives]

    @cached_property
    def uninstall_entries(self) -> list[UninstallEntry]:
        return read_uninstall_entries(self.registry)

    def is_running(self, *process_names: str) -> bool:
        return any(name.lower() in self.running for name in process_names)

    @classmethod
    def detect(cls) -> "SystemContext":
        env = {k.upper(): v for k, v in os.environ.items()}
        return cls(
            registry=system_registry(),
            env=env,
            drives=_fixed_drives(),
            running=_running_processes(),
            is_windows=sys.platform == "win32",
            computer_name=env.get("COMPUTERNAME") or socket.gethostname(),
            os_name=platform.platform(),
        )


def _fixed_drives() -> list[str]:
    if sys.platform != "win32":
        return ["/"]
    import ctypes

    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    drives = []
    for index in range(26):
        if mask & (1 << index):
            root = f"{chr(ord('A') + index)}:\\"
            if kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                drives.append(root)
    return drives


def _running_processes() -> frozenset[str]:
    try:
        import psutil
    except ImportError:
        return frozenset()
    names = set()
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name")
        if name:
            names.add(name.lower())
    return frozenset(names)


def disk_usage(drive: str) -> tuple[int, int] | None:
    """(total, free) bytes, or None if the disk cannot be read."""
    try:
        usage = shutil.disk_usage(drive)
    except OSError:
        return None
    return usage.total, usage.free
