"""Encrypting saved logins with a key tied to this computer.

The key comes from the computer's own id (Windows MachineGuid), so a vault
file copied to another PC is useless, and it stays the same across reboots.
That matters in clubs: with Shadow Defender or Deep Freeze the system disk
is rolled back on every reboot, and Windows' own per-user keys (DPAPI),
which are rotated and kept on that disk, could vanish with it.

Construction: SHAKE-256 keystream (key, random nonce) XOR the data, then an
HMAC-SHA256 tag over everything; tampering or a wrong computer is detected.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import socket
import sys

_MAGIC = b"GUPDATER-V2\n"
_PLAIN = b"GUPDATER-NOT-ENCRYPTED\n"  # written by 0.3.0 off Windows (tests); still readable


class SecretError(Exception):
    pass


def machine_id() -> str:
    override = os.environ.get("GUPDATER_MACHINE_ID")
    if override:
        return override
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                return str(winreg.QueryValueEx(key, "MachineGuid")[0])
        except OSError:
            pass
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            return open(path, encoding="ascii").read().strip()
        except OSError:
            continue
    return socket.gethostname()


def _keys() -> tuple[bytes, bytes]:
    secret = hashlib.sha256(b"GUpdater club login v2|" + machine_id().encode()).digest()
    return (hmac.new(secret, b"encrypt", hashlib.sha256).digest(),
            hmac.new(secret, b"authenticate", hashlib.sha256).digest())


def _xor(data: bytes, stream: bytes) -> bytes:
    if not data:
        return b""
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(len(data), "big")


def protect(data: bytes) -> bytes:
    enc_key, mac_key = _keys()
    nonce = os.urandom(16)
    cipher = _xor(data, hashlib.shake_256(enc_key + nonce).digest(len(data)))
    tag = hmac.new(mac_key, _MAGIC + nonce + cipher, hashlib.sha256).digest()
    return _MAGIC + nonce + tag + cipher


def unprotect(blob: bytes) -> bytes:
    if blob.startswith(_MAGIC):
        body = blob[len(_MAGIC):]
        nonce, tag, cipher = body[:16], body[16:48], body[48:]
        enc_key, mac_key = _keys()
        expected = hmac.new(mac_key, _MAGIC + nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise SecretError("сохранённый вход сделан на другом компьютере или повреждён — запомните вход заново")
        return _xor(cipher, hashlib.shake_256(enc_key + nonce).digest(len(cipher)))
    if blob.startswith(_PLAIN):
        return blob[len(_PLAIN):]
    if sys.platform == "win32":
        return _dpapi_decrypt(blob)  # vaults written by 0.3.0
    raise SecretError("неизвестный формат сохранённого входа — запомните вход заново")


def _dpapi_decrypt(blob: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def make(raw: bytes):
        buffer = ctypes.create_string_buffer(raw, len(raw))
        return DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    source, _keep1 = make(blob)
    entropy, _keep2 = make(b"GUpdater club login v1")
    out = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(entropy), None, None,
                                                    0x1, ctypes.byref(out)):
        raise SecretError("не удалось прочитать сохранённый вход — запомните вход заново")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)
