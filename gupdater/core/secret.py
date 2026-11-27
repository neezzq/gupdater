"""Encrypting saved logins so that only this Windows user on this PC can read them.

Windows does the work (DPAPI, the same protection browsers use for saved
passwords). Other systems get a clearly marked plain wrapper, used only by
tests and the demo; GUpdater's real use is Windows.
"""

from __future__ import annotations

import sys

_ENTROPY = b"GUpdater club login v1"
_PLAIN = b"GUPDATER-NOT-ENCRYPTED\n"


class SecretError(Exception):
    pass


def protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return _PLAIN + data
    return _dpapi(data, encrypt=True)


def unprotect(blob: bytes) -> bytes:
    if sys.platform != "win32":
        if not blob.startswith(_PLAIN):
            raise SecretError("файл зашифрован на другом компьютере")
        return blob[len(_PLAIN):]
    return _dpapi(blob, encrypt=False)


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(raw: bytes):
        buffer = ctypes.create_string_buffer(raw, len(raw))
        return DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    source, _keep1 = blob(data)
    entropy, _keep2 = blob(_ENTROPY)
    out = DATA_BLOB()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if encrypt:
        ok = crypt32.CryptProtectData(ctypes.byref(source), "GUpdater", ctypes.byref(entropy), None, None, flags, ctypes.byref(out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, ctypes.byref(entropy), None, None, flags, ctypes.byref(out))
    if not ok:
        raise SecretError(
            "не удалось " + ("зашифровать" if encrypt else "расшифровать")
            + " сохранённый вход (он сохранён другим пользователем Windows или на другом ПК)"
        )
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)
