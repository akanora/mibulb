"""Keep bulb tokens encrypted at rest (Windows DPAPI).

DPAPI ties the encryption to your Windows account: other accounts on the PC,
or anyone who copies config.json to another PC, can't read the tokens. On
other systems tokens are stored as plain text, as before.
"""

from __future__ import annotations

import base64
import sys

_ENTROPY = b"mibulb-token-v1"  # extra input so other apps' DPAPI blobs can't be swapped in


class SecretError(Exception):
    pass


def supported() -> bool:
    return sys.platform == "win32"


def _blob(data: bytes):
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer, DATA_BLOB


def _call(name: str, data: bytes) -> bytes:
    import ctypes

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    blob_in, _keep_in, DATA_BLOB = _blob(data)
    entropy, _keep_entropy, _ = _blob(_ENTROPY)
    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    if name == "protect":
        ok = crypt32.CryptProtectData(ctypes.byref(blob_in), None, ctypes.byref(entropy), None, None,
                                      CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, ctypes.byref(entropy), None, None,
                                        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise SecretError(f"Windows could not {name} the token (error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(text: str) -> str:
    return base64.b64encode(_call("protect", text.encode("utf-8"))).decode("ascii")


def unprotect(text: str) -> str:
    try:
        raw = base64.b64decode(text)
    except ValueError as exc:
        raise SecretError("The saved token is damaged") from exc
    return _call("unprotect", raw).decode("utf-8")
