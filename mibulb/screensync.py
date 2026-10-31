"""Screen sync: the bulb follows the main colour on your screen.

A background thread grabs the main screen a few times a second, shrinks it,
and picks a "vibrant average" colour: colourful pixels count much more than
grey or dark ones, so a red health bar or a sunset sky wins over a dark UI.

Measured on a Mi Smart LED Bulb Essential: it accepted 4 commands per second
for 30 seconds without refusing any, so updates are sent about 3 times a
second, each with a short fade so the changes look smooth.
"""

from __future__ import annotations

import colorsys
import threading
import time
from typing import Callable

UPDATE_SECONDS = 0.33
FADE_MS = 300
# Don't bother the bulb with changes you wouldn't notice.
MIN_COLOR_CHANGE = 18  # distance in RGB
MIN_BRIGHTNESS_CHANGE = 6  # percent


def dominant_color(image) -> tuple[int, int] | None:
    """Return (rgb, brightness percent) for a screenshot, or None for an (almost) black frame.

    Exclusive-fullscreen games can show up as black frames; None means "keep the last colour".
    """
    small = image.convert("RGB").resize((32, 18))
    # get_flattened_data replaces getdata in newer Pillow (getdata goes away in Pillow 14)
    pixels = list(getattr(small, "get_flattened_data", small.getdata)())
    total_weight = r_sum = g_sum = b_sum = 0.0
    luminance = 0.0
    for r, g, b in pixels:
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        luminance += 0.2126 * r + 0.7152 * g + 0.0722 * b
        weight = (s * s) * v + 0.002  # colourful, bright pixels count most
        total_weight += weight
        r_sum += r * weight
        g_sum += g * weight
        b_sum += b * weight
    luminance /= len(pixels) * 255
    if luminance < 0.02:
        return None
    r, g, b = r_sum / total_weight, g_sum / total_weight, b_sum / total_weight
    h, s, _v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if s < 0.12:
        rgb = 0xFFFFFF  # a grey screen: plain white light
    else:
        # Full value (brightness is set separately) and a little extra saturation.
        rr, gg, bb = colorsys.hsv_to_rgb(h, min(1.0, s * 1.35), 1.0)
        rgb = (round(rr * 255) << 16) | (round(gg * 255) << 8) | round(bb * 255)
    brightness = max(5, min(100, round(15 + luminance * 140)))
    return max(1, rgb), brightness


def color_distance(a: int, b: int) -> float:
    ar, ag, ab = a >> 16, (a >> 8) & 0xFF, a & 0xFF
    br, bg, bb = b >> 16, (b >> 8) & 0xFF, b & 0xFF
    return ((ar - br) ** 2 + (ag - bg) ** 2 + (ab - bb) ** 2) ** 0.5


def grab_screen(bbox: tuple[int, int, int, int] | None = None):
    """The main screen, or the part of the desktop in bbox (left, top, right, bottom)."""
    from PIL import ImageGrab

    if bbox is None:
        return ImageGrab.grab()
    return ImageGrab.grab(bbox=bbox, all_screens=True)


def monitors() -> list[dict]:
    """The PC's screens, main screen first: [{"name", "bbox", "primary"}]. Windows only."""
    import sys

    if sys.platform != "win32":
        return [{"name": "Main screen", "bbox": None, "primary": True}]
    import ctypes
    from ctypes import wintypes

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    found: list[dict] = []
    MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                         ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(hmonitor, _hdc, _rect, _data):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        ctypes.windll.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info))
        r = info.rcMonitor
        found.append({"bbox": (r.left, r.top, r.right, r.bottom), "primary": bool(info.dwFlags & 1),
                      "size": f"{r.right - r.left}×{r.bottom - r.top}"})
        return True

    ctypes.windll.user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
    found.sort(key=lambda m: (not m["primary"], m["bbox"][0], m["bbox"][1]))
    for number, monitor in enumerate(found, 1):
        monitor["name"] = (f"Main screen ({monitor['size']})" if monitor["primary"]
                           else f"Screen {number} ({monitor['size']})")
    return found or [{"name": "Main screen", "bbox": None, "primary": True}]


class ScreenSync:
    """Calls send(rgb, brightness_or_None) whenever the screen's colour changes noticeably."""

    def __init__(self, send: Callable[[int, int | None], None], match_brightness: bool = True,
                 grab: Callable[[], object] | None = None, interval: float = UPDATE_SECONDS):
        self._send = send
        self._grab = grab or grab_screen
        self.match_brightness = match_brightness
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last: tuple[int, int] | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(2)
        self._thread = None

    def step(self) -> bool:
        """Grab one frame and send it if it changed enough. Returns True if something was sent."""
        try:
            found = dominant_color(self._grab())
        except Exception:
            return False  # e.g. the screen is locked
        if found is None:
            return False
        rgb, brightness = found
        if self.last is not None:
            last_rgb, last_brightness = self.last
            color_changed = color_distance(rgb, last_rgb) >= MIN_COLOR_CHANGE
            brightness_changed = self.match_brightness and abs(brightness - last_brightness) >= MIN_BRIGHTNESS_CHANGE
            if not color_changed and not brightness_changed:
                return False
            send_brightness = brightness if brightness_changed else None
        else:
            send_brightness = brightness if self.match_brightness else None
        self.last = (rgb, brightness if send_brightness is not None or self.last is None else self.last[1])
        self._send(rgb, send_brightness)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            self.step()
            self._stop.wait(max(0.0, self.interval - (time.monotonic() - started)))
