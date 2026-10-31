"""Colours, the background worker and small helpers shared by the windows."""

from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from typing import Any, Callable


try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
try:
    import pystray
except ImportError:  # the tray icon is optional
    pystray = None
if Image is None:
    pystray = None


# Shared with the other window modules
__all__ = ["ACCENT", "BG", "ERROR", "MUTED", "PANEL", "TEXT", "PRESET_COLORS", "PRESET_WHITES", "Post", "Worker",
           "run_in_thread", "make_icon_image", "work_area", "Image", "ImageTk", "pystray"]

BG = "#1e1f24"
PANEL = "#2a2c33"
TEXT = "#e8e8ea"
MUTED = "#9a9ca5"
ACCENT = "#f5c542"
ERROR = "#ff6b6b"

PRESET_COLORS = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759", "#00c7be", "#007aff", "#af52de", "#ff2d55"]
PRESET_WHITES = [("Warm", 2700), ("Neutral", 4000), ("Daylight", 6500)]

Post = Callable[[Callable[[], None]], None]


class Worker:
    """Runs bulb commands on a background thread so the window never freezes.

    Commands are keyed: queueing a new command with the same key replaces the
    pending one, so dragging a slider only sends the latest value.
    """

    def __init__(self, on_result: Post):
        self._pending: OrderedDict[str, tuple[Callable[[], Any], Callable[[Any], None] | None]] = OrderedDict()
        self._cond = threading.Condition()
        self._on_result = on_result
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, key: str, func: Callable[[], Any], done: Callable[[Any], None] | None = None) -> None:
        with self._cond:
            self._pending.pop(key, None)
            self._pending[key] = (func, done)
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._pending:
                    self._cond.wait()
                _key, (func, done) = self._pending.popitem(last=False)
            try:
                result: Any = func()
            except Exception as exc:  # reported in the status bar
                result = exc
            if done is not None:
                self._on_result(lambda d=done, r=result: d(r))


def run_in_thread(post: Post, func: Callable[[], Any], done: Callable[[Any], None]) -> None:
    """Run func on a new thread and hand its result (or exception) to done on the Tk thread."""

    def work() -> None:
        try:
            result: Any = func()
        except Exception as exc:
            result = exc
        post(lambda: done(result))

    threading.Thread(target=work, daemon=True).start()


def make_icon_image(on: bool = True, size: int = 64) -> "Image.Image":
    from ..icon import draw_logo

    return draw_logo(size, on)


def work_area() -> tuple[int, int, int, int]:
    """The desktop minus the taskbar (left, top, right, bottom) on the main screen."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, 1280, 720
