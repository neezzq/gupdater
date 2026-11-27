"""Checks that need real Windows (they run in the GitHub build)."""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_dpapi_round_trip_and_no_plain_text():
    from gupdater.core.secret import protect, unprotect

    blob = protect(b"club-token-123")
    assert b"club-token-123" not in blob
    assert unprotect(blob) == b"club-token-123"


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
