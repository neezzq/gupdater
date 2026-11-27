"""Starting GUpdater minimised when Windows signs in (club PCs listen for the console)."""

from __future__ import annotations

from pathlib import Path

from gupdater.core.registry import REG_SZ, WritableRegistry, reg_str

RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "GUpdater Agent"


def command(exe: Path) -> str:
    return f'"{exe}" --agent'


def is_enabled(registry: WritableRegistry, exe: Path) -> bool:
    return reg_str(registry, RUN_KEY, VALUE) == command(exe)


def set_enabled(registry: WritableRegistry, exe: Path, on: bool) -> None:
    if on:
        registry.set_value(RUN_KEY, VALUE, REG_SZ, command(exe))
    else:
        registry.delete_value(RUN_KEY, VALUE)
