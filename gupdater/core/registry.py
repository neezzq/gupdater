"""Read-only access to the Windows registry.

Paths are written the usual way, e.g. ``HKLM\\SOFTWARE\\Valve\\Steam``.
``WinRegistry`` reads the real registry; ``DictRegistry`` is an in-memory
stand-in used by tests and by the demo mode; ``NullRegistry`` is what other
operating systems get.
"""

from __future__ import annotations

import sys
from typing import Any, Mapping, Protocol

_HIVE_ALIASES = {
    "HKLM": "HKEY_LOCAL_MACHINE",
    "HKCU": "HKEY_CURRENT_USER",
    "HKCR": "HKEY_CLASSES_ROOT",
    "HKU": "HKEY_USERS",
}


def split_hive(path: str) -> tuple[str, str]:
    """Split ``HKLM\\A\\B`` into (``HKEY_LOCAL_MACHINE``, ``A\\B``)."""
    parts = [p for p in path.replace("/", "\\").split("\\") if p]
    if not parts:
        return "", ""
    hive = _HIVE_ALIASES.get(parts[0].upper(), parts[0].upper())
    return hive, "\\".join(parts[1:])


class Registry(Protocol):
    def subkeys(self, path: str) -> list[str]:
        """Names of the direct subkeys of ``path`` (empty if it does not exist)."""

    def values(self, path: str) -> dict[str, Any]:
        """Values of ``path`` by name; the default value has the name ``""``."""


def reg_value(registry: Registry, path: str, name: str, default: Any = None) -> Any:
    """One value, looked up case-insensitively like Windows does."""
    wanted = name.lower()
    for key, value in registry.values(path).items():
        if key.lower() == wanted:
            return value
    return default


def reg_str(registry: Registry, path: str, name: str) -> str:
    value = reg_value(registry, path, name)
    return "" if value is None else str(value).strip()


class NullRegistry:
    """A registry with nothing in it (non-Windows hosts)."""

    def subkeys(self, path: str) -> list[str]:
        return []

    def values(self, path: str) -> dict[str, Any]:
        return {}


class DictRegistry:
    """In-memory registry: ``{"HKLM\\Software\\X": {"Name": "value"}}``."""

    def __init__(self, data: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        # normalized lower-case path -> (path with original case, values)
        self._keys: dict[str, tuple[str, dict[str, Any]]] = {}
        for path, values in (data or {}).items():
            self.set(path, values)

    @staticmethod
    def _canonical(path: str) -> str:
        hive, rest = split_hive(path)
        return f"{hive}\\{rest}" if rest else hive

    def set(self, path: str, values: Mapping[str, Any] | None = None) -> None:
        canonical = self._canonical(path)
        parts = canonical.split("\\")
        # Make sure every parent key exists too, as in a real registry.
        for depth in range(1, len(parts) + 1):
            sub = "\\".join(parts[:depth])
            self._keys.setdefault(sub.lower(), (sub, {}))
        self._keys[canonical.lower()][1].update(values or {})

    def subkeys(self, path: str) -> list[str]:
        base = self._canonical(path).lower()
        depth = base.count("\\") + 1
        names: dict[str, str] = {}
        for norm, (original, _) in self._keys.items():
            if norm.startswith(base + "\\"):
                child = original.split("\\")[depth]
                names.setdefault(child.lower(), child)
        return sorted(names.values(), key=str.lower)

    def values(self, path: str) -> dict[str, Any]:
        entry = self._keys.get(self._canonical(path).lower())
        return dict(entry[1]) if entry else {}


class WinRegistry:
    """The real Windows registry (64-bit view, read-only)."""

    def __init__(self) -> None:
        import winreg  # only exists on Windows

        self._winreg = winreg
        self._hives = {
            "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
            "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
            "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
            "HKEY_USERS": winreg.HKEY_USERS,
        }

    def _open(self, path: str):
        hive, sub = split_hive(path)
        root = self._hives.get(hive)
        if root is None:
            return None
        access = self._winreg.KEY_READ | self._winreg.KEY_WOW64_64KEY
        try:
            return self._winreg.OpenKey(root, sub, 0, access)
        except OSError:
            return None

    def subkeys(self, path: str) -> list[str]:
        key = self._open(path)
        if key is None:
            return []
        names = []
        with key:
            index = 0
            while True:
                try:
                    names.append(self._winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
        return names

    def values(self, path: str) -> dict[str, Any]:
        key = self._open(path)
        if key is None:
            return {}
        result: dict[str, Any] = {}
        with key:
            index = 0
            while True:
                try:
                    name, data, _type = self._winreg.EnumValue(key, index)
                except OSError:
                    break
                result[name] = data
                index += 1
        return result


def system_registry() -> Registry:
    return WinRegistry() if sys.platform == "win32" else NullRegistry()
