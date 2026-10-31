"""A system-wide keyboard shortcut (Windows only), e.g. Ctrl+Alt+L to toggle the light."""

from __future__ import annotations

import sys
import threading
from typing import Callable

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

DEFAULT_LABEL = "Ctrl+Alt+L"
DEFAULT_MODIFIERS = MOD_CONTROL | MOD_ALT
DEFAULT_KEY = ord("L")


def supported() -> bool:
    return sys.platform == "win32"


class GlobalHotkey:
    """Registers a hotkey on its own thread, which runs a Windows message loop."""

    def __init__(self, callback: Callable[[], None], modifiers: int = DEFAULT_MODIFIERS, key: int = DEFAULT_KEY):
        self._callback = callback
        self._modifiers = modifiers
        self._key = key
        self._thread_id = 0
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Return False if the shortcut is already taken by another app."""
        ready = threading.Event()
        result = {"ok": False}

        def run() -> None:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._thread_id = kernel32.GetCurrentThreadId()
            result["ok"] = bool(user32.RegisterHotKey(None, 1, self._modifiers | MOD_NOREPEAT, self._key))
            ready.set()
            if not result["ok"]:
                return
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self._callback()
            user32.UnregisterHotKey(None, 1)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        ready.wait(2)
        return result["ok"]

    def stop(self) -> None:
        if self._thread is None:
            return
        import ctypes

        ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(2)
        self._thread = None
