"""Pick a colour from anywhere on the screen (an eyedropper).

A screenshot of the whole desktop is shown full-screen; you click the pixel
you want, or press Esc to cancel. The click is mapped back to the
screenshot's pixels, so it is right even with Windows display scaling.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable

from .common import Image, ImageTk


def virtual_screen() -> tuple[int, int, int, int]:
    """(left, top, width, height) of the whole desktop, in this window's coordinates."""
    if sys.platform == "win32":
        import ctypes

        metric = ctypes.windll.user32.GetSystemMetrics
        return metric(76), metric(77), metric(78), metric(79)  # SM_X/YVIRTUALSCREEN, SM_CX/CYVIRTUALSCREEN
    return 0, 0, 1920, 1080


def pixel_for(x: int, y: int, window_size: tuple[int, int], image_size: tuple[int, int]) -> tuple[int, int]:
    """Map a click in the full-screen window to a pixel in the screenshot (they differ with display scaling)."""
    (ww, wh), (iw, ih) = window_size, image_size
    return min(iw - 1, max(0, int(x * iw / max(1, ww)))), min(ih - 1, max(0, int(y * ih / max(1, wh))))


class ScreenColorPicker(tk.Toplevel):
    def __init__(self, master: tk.Misc, on_pick: Callable[[str], None], on_cancel: Callable[[], None],
                 screenshot=None):
        super().__init__(master)
        from PIL import ImageGrab

        self._on_pick = on_pick
        self._on_cancel = on_cancel
        self._image = screenshot if screenshot is not None else ImageGrab.grab(all_screens=True)
        self._image = self._image.convert("RGB")
        left, top, width, height = virtual_screen()
        self._size = (width, height)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{width}x{height}+{left}+{top}")
        self.canvas = tk.Canvas(self, width=width, height=height, highlightthickness=0, cursor="crosshair", bd=0)
        self.canvas.pack()
        shown = self._image.resize((width, height)) if self._image.size != (width, height) else self._image
        self._photo = ImageTk.PhotoImage(shown)
        self.canvas.create_image(0, 0, image=self._photo, anchor="nw")
        # A small loupe that follows the mouse with the colour under it
        self._swatch = self.canvas.create_rectangle(0, 0, 0, 0, outline="#ffffff", width=2)
        self._label = self.canvas.create_text(0, 0, text="", fill="#ffffff", anchor="nw", font=("Segoe UI", 10, "bold"))
        self.canvas.bind("<Motion>", self._move)
        self.canvas.bind("<Button-1>", self._click)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.canvas.bind("<Button-3>", lambda _e: self._cancel())
        self.after(50, self.focus_force)

    def color_at(self, x: int, y: int) -> str:
        px, py = pixel_for(x, y, self._size, self._image.size)
        r, g, b = self._image.getpixel((px, py))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _move(self, event: tk.Event) -> None:
        color = self.color_at(event.x, event.y)
        x, y = event.x + 18, event.y + 18
        self.canvas.coords(self._swatch, x, y, x + 36, y + 36)
        self.canvas.itemconfigure(self._swatch, fill=color)
        self.canvas.coords(self._label, x + 42, y + 10)
        self.canvas.itemconfigure(self._label, text=color)

    def _cancel(self) -> None:
        self.destroy()
        self._on_cancel()

    def _click(self, event: tk.Event) -> None:
        color = self.color_at(event.x, event.y)
        self.destroy()
        self._on_pick(color)


__all__ = ["ScreenColorPicker", "pixel_for", "virtual_screen", "Image"]
