"""Notice when the PC is locked/unlocked or goes to sleep/wakes up (Windows only).

A hidden window on its own thread receives WM_WTSSESSION_CHANGE (lock and
unlock) and WM_POWERBROADCAST (sleep and resume) and reports them as
"lock", "unlock", "suspend" and "resume".
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8
PBT_APMSUSPEND = 0x4
PBT_APMRESUMESUSPEND = 0x7
PBT_APMRESUMEAUTOMATIC = 0x12

EVENTS = {
    (WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK): "lock",
    (WM_WTSSESSION_CHANGE, WTS_SESSION_UNLOCK): "unlock",
    (WM_POWERBROADCAST, PBT_APMSUSPEND): "suspend",
    (WM_POWERBROADCAST, PBT_APMRESUMESUSPEND): "resume",
    (WM_POWERBROADCAST, PBT_APMRESUMEAUTOMATIC): "resume",
}


def supported() -> bool:
    return sys.platform == "win32"


class PcEventWatcher:
    def __init__(self, callback: Callable[[str], None]):
        self._callback = callback
        self._thread: threading.Thread | None = None
        self.hwnd = None

    def start(self) -> bool:
        if not supported():
            return False
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self._thread.start()
        ready.wait(3)
        return bool(self.hwnd)

    def _run(self, ready: threading.Event) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        wtsapi32 = ctypes.windll.wtsapi32
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        def wndproc(hwnd, msg, wparam, lparam):
            event = EVENTS.get((msg, wparam))
            if event:
                try:
                    self._callback(event)
                except Exception:
                    pass
                if msg == WM_POWERBROADCAST:
                    return 1
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wndproc)  # keep a reference so it isn't garbage collected
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = f"MiBulbPcEvents{id(self)}"
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinstance
        wc.lpszClassName = class_name
        if not user32.RegisterClassW(ctypes.byref(wc)):
            ready.set()
            return
        # A hidden top-level window: message-only windows don't get power broadcasts.
        hwnd = user32.CreateWindowExW(0, class_name, "Mi Bulb events", 0, 0, 0, 0, 0, None, None, hinstance, None)
        if not hwnd:
            ready.set()
            return
        wtsapi32.WTSRegisterSessionNotification(hwnd, 0)  # this session only
        self.hwnd = hwnd
        ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        wtsapi32.WTSUnRegisterSessionNotification(hwnd)
        user32.UnregisterClassW(class_name, hinstance)

    def stop(self) -> None:
        if self.hwnd and self._thread is not None:
            import ctypes

            ctypes.windll.user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            self._thread.join(2)
        self._thread = None
        self.hwnd = None
