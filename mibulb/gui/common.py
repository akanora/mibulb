"""Colours, the background worker and small helpers shared by the windows."""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from collections import OrderedDict
from tkinter import ttk
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
           "run_in_thread", "make_icon_image", "work_area", "Image", "ImageTk", "pystray", "ScrollFrame",
           "fit_to_screen"]

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


class ScrollFrame(ttk.Frame):
    """A frame whose content scrolls when the window is smaller than it.

    Put widgets in .inner. The scrollbar only shows when needed, and the mouse
    wheel scrolls while the pointer is over the area.
    """

    def __init__(self, master: tk.Misc, padding: Any = 0):
        super().__init__(master)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=padding)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self._scrolled)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._content_changed)
        self.canvas.bind("<Configure>", self._resized)
        self.bind("<Enter>", lambda _e: self.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda _e: self.unbind_all("<MouseWheel>"))

    def _content_changed(self, _event: object = None) -> None:
        # Ask for room for all the content; the window decides how much it really gets.
        self.canvas.configure(scrollregion=self.canvas.bbox("all"),
                              width=self.inner.winfo_reqwidth(), height=self.inner.winfo_reqheight())

    def _resized(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=max(event.width, self.inner.winfo_reqwidth()))

    def _scrolled(self, first: str, last: str) -> None:
        self.bar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.bar.pack_forget()
        elif not self.bar.winfo_ismapped():
            self.bar.pack(side="right", fill="y", before=self.canvas)

    def _wheel(self, event: tk.Event) -> None:
        first, last = self.canvas.yview()
        if first > 0.0 or last < 1.0:
            self.canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")

    def scroll_to(self, widget: tk.Widget) -> None:
        """Scroll so that widget is visible."""
        self.update_idletasks()
        total = max(1, self.inner.winfo_height())
        self.canvas.yview_moveto(max(0.0, (widget.winfo_rooty() - self.inner.winfo_rooty() - 20) / total))


def fit_to_screen(window: tk.Misc, min_size: tuple[int, int] = (360, 320)) -> None:
    """Open a window no bigger than the free screen area (the rest scrolls), and let it be resized."""
    window.update_idletasks()
    left, top, right, bottom = work_area()
    width = min(window.winfo_reqwidth(), right - left - 40)
    height = min(window.winfo_reqheight(), bottom - top - 60)
    x = min(max(window.winfo_x(), left + 10), right - width - 10)
    y = min(max(window.winfo_y(), top + 10), bottom - height - 40)
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.minsize(*min_size)
    window.resizable(True, True)
