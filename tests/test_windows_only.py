"""Checks that need real Windows (they run in the GitHub build)."""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_vaults_from_0_3_0_written_with_dpapi_still_open():
    import ctypes
    from ctypes import wintypes

    from gupdater.core.secret import unprotect

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def make(raw):
        buffer = ctypes.create_string_buffer(raw, len(raw))
        return DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    source, keep1 = make(b"old club token")
    entropy, keep2 = make(b"GUpdater club login v1")
    out = DATA_BLOB()
    assert ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source), "GUpdater", ctypes.byref(entropy),
                                                  None, None, 1, ctypes.byref(out))
    blob = ctypes.string_at(out.pbData, out.cbData)
    assert unprotect(blob) == b"old club token"


def test_machine_key_uses_the_windows_machine_guid(monkeypatch):
    from gupdater.core import secret

    monkeypatch.delenv("GUPDATER_MACHINE_ID", raising=False)
    guid = secret.machine_id()
    assert len(guid) == 36 and guid.count("-") == 4
    assert secret.unprotect(secret.protect(b"x" * 100_000)) == b"x" * 100_000


def test_registry_writes_and_login_swap(tmp_path):
    import winreg

    from gupdater.core.registry import REG_BINARY, REG_SZ, WinRegistry
    from gupdater.logins import SessionSpec, apply, capture

    key = r"HKCU\Software\GUpdaterCITest"
    reg = WinRegistry()
    try:
        reg.set_value(key, "AutoLoginUser", REG_SZ, "club")
        reg.set_value(key, "Token", REG_BINARY, b"\x01\x02")
        spec = SessionSpec(registry_values=((key, "AutoLoginUser"), (key, "Token")))
        club = capture(spec, reg)
        reg.set_value(key, "AutoLoginUser", REG_SZ, "player")
        reg.delete_value(key, "Token")
        apply(club, reg)
        assert reg.typed_values(key) == {"AutoLoginUser": (REG_SZ, "club"), "Token": (REG_BINARY, b"\x01\x02")}
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\GUpdaterCITest")
