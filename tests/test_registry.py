import sys

import pytest

from gupdater.core.context import read_uninstall_entries
from gupdater.core.registry import DictRegistry, reg_value, split_hive


def test_split_hive_aliases():
    assert split_hive(r"HKLM\SOFTWARE\Valve") == ("HKEY_LOCAL_MACHINE", r"SOFTWARE\Valve")
    assert split_hive("HKCR") == ("HKEY_CLASSES_ROOT", "")


def test_dict_registry_is_case_insensitive_and_creates_parents():
    reg = DictRegistry({r"HKCU\Software\Valve\Steam": {"SteamPath": "c:/steam"}})
    assert reg_value(reg, r"hkey_current_user\software\valve\steam", "steampath") == "c:/steam"
    assert reg.subkeys(r"HKCU\Software") == ["Valve"]
    assert reg.subkeys(r"HKCU\Software\Valve") == ["Steam"]
    assert reg.values(r"HKCU\Nope") == {}


def test_uninstall_entries_skip_nameless_and_duplicates():
    root = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    wow = r"HKLM\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    reg = DictRegistry({
        rf"{root}\A": {"DisplayName": "Game A", "EstimatedSize": 1024, "InstallLocation": '"D:\\Games\\A"'},
        rf"{wow}\A": {"DisplayName": "Game A"},
        rf"{root}\Hotfix": {},
    })
    entries = read_uninstall_entries(reg)
    assert [e.display_name for e in entries] == ["Game A"]
    assert entries[0].size_bytes == 1024 * 1024
    assert entries[0].install_location == "D:\\Games\\A"


@pytest.mark.skipif(sys.platform != "win32", reason="needs the real Windows registry")
def test_real_windows_registry():
    from gupdater.core.registry import WinRegistry

    reg = WinRegistry()
    assert reg_value(reg, r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductName")
    assert reg.subkeys(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
