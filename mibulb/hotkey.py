"""System-wide keyboard shortcuts (Windows only).

Shortcuts are stored as text like "Ctrl+Alt+L" and registered with the
Windows RegisterHotKey API on a dedicated thread that runs a message loop.
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

MODIFIERS = [("Ctrl", MOD_CONTROL), ("Alt", MOD_ALT), ("Shift", MOD_SHIFT), ("Win", MOD_WIN)]

# Windows virtual-key codes for keys that can be used in a shortcut.
KEY_NAMES: dict[int, str] = {
    **{code: chr(code) for code in range(0x41, 0x5B)},  # A-Z
    **{code: chr(code) for code in range(0x30, 0x3A)},  # 0-9
    **{0x70 + i: f"F{i + 1}" for i in range(24)},  # F1-F24
    **{0x60 + i: f"Num{i}" for i in range(10)},  # numpad 0-9
    0x20: "Space",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2D: "Insert",
    0x2E: "Delete",
    0x13: "Pause",
}
KEY_CODES = {name.lower(): code for code, name in KEY_NAMES.items()}

# Keys that make sense on their own, without Ctrl/Alt/Win (nothing else uses them).
STANDALONE_KEYS = {0x7C + i for i in range(12)}  # F13-F24


def supported() -> bool:
    return sys.platform == "win32"


class ShortcutError(ValueError):
    pass


def parse(text: str) -> tuple[int, int]:
    """Parse "Ctrl+Alt+L" into (modifiers, virtual-key code)."""
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        raise ShortcutError("Empty shortcut")
    modifiers = 0
    names = {name.lower(): flag for name, flag in MODIFIERS}
    for part in parts[:-1]:
        flag = names.get(part.lower())
        if flag is None:
            raise ShortcutError(f"Unknown modifier {part!r}")
        modifiers |= flag
    key = KEY_CODES.get(parts[-1].lower())
    if key is None:
        raise ShortcutError(f"Unknown key {parts[-1]!r}")
    validate(modifiers, key)
    return modifiers, key


def validate(modifiers: int, key: int) -> None:
    if key not in KEY_NAMES:
        raise ShortcutError("That key can't be used in a shortcut.")
    if not modifiers & (MOD_CONTROL | MOD_ALT | MOD_WIN) and key not in STANDALONE_KEYS:
        raise ShortcutError("Use Ctrl, Alt or Win together with the key, so normal typing isn't blocked.")


def format_shortcut(modifiers: int, key: int) -> str:
    names = [name for name, flag in MODIFIERS if modifiers & flag]
    return "+".join(names + [KEY_NAMES[key]])


class HotkeyManager:
    """Registers a set of shortcuts and calls back with the action name when one is pressed."""

    def __init__(self, callback: Callable[[str], None]):
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id = 0

    def apply(self, bindings: dict[str, str]) -> dict[str, str]:
        """Replace all registered shortcuts. Returns {action: problem} for ones that failed."""
        self.stop()
        problems: dict[str, str] = {}
        parsed: list[tuple[str, int, int]] = []
        for action, text in bindings.items():
            if not text:
                continue
            try:
                modifiers, key = parse(text)
            except ShortcutError as exc:
                problems[action] = str(exc)
                continue
            parsed.append((action, modifiers, key))
        if not parsed or not supported():
            return problems

        ready = threading.Event()

        def run() -> None:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            ids: dict[int, str] = {}
            for number, (action, modifiers, key) in enumerate(parsed, start=1):
                if user32.RegisterHotKey(None, number, modifiers | MOD_NOREPEAT, key):
                    ids[number] = action
                else:
                    problems[action] = "Already used by Windows or another app."
            ready.set()
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam in ids:
                    self._callback(ids[msg.wParam])
            for number in ids:
                user32.UnregisterHotKey(None, number)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        ready.wait(2)
        return problems

    def stop(self) -> None:
        if self._thread is None:
            return
        import ctypes

        ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(2)
        self._thread = None


def typed_character(modifiers: int, key: int, layout: int | None = None) -> str | None:
    """The character this combination types on the current keyboard layout, if any.

    On many layouts Ctrl+Alt works as AltGr (Ctrl+Alt+L types "ł" on Polish
    keyboards), so a global shortcut on it would stop that character from
    being typed.
    """
    if not supported() or not (modifiers & MOD_CONTROL and modifiers & MOD_ALT) or modifiers & MOD_WIN:
        return None
    import ctypes

    user32 = ctypes.windll.user32
    user32.GetKeyboardLayout.restype = ctypes.c_void_p
    user32.ToUnicodeEx.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_char_p, ctypes.c_wchar_p, ctypes.c_int,
                                   ctypes.c_uint, ctypes.c_void_p]
    hkl = layout if layout is not None else user32.GetKeyboardLayout(0)
    state = (ctypes.c_ubyte * 256)()
    for vk in (0x11, 0x12, 0xA2, 0xA4):  # Ctrl, Alt, left Ctrl, left Alt held
        state[vk] = 0x80
    if modifiers & MOD_SHIFT:
        state[0x10] = state[0xA0] = 0x80
    buffer = ctypes.create_unicode_buffer(8)
    scan = user32.MapVirtualKeyExW(key, 0, ctypes.c_void_p(hkl))
    # Flag 4: don't change the keyboard state (Windows 10 1607 and later)
    count = user32.ToUnicodeEx(key, scan, ctypes.cast(state, ctypes.c_char_p), buffer, len(buffer), 4, hkl)
    if count < 0:
        # A dead key (e.g. an accent waiting for the next letter): clear it and still report it.
        user32.ToUnicodeEx(0x20, 0x39, ctypes.cast((ctypes.c_ubyte * 256)(), ctypes.c_char_p), buffer,
                           len(buffer), 4, hkl)
        return "´"
    text = buffer.value[:count] if count > 0 else ""
    return text if text and text.isprintable() else None


def pressed_modifiers() -> int:
    """Which of Ctrl/Alt/Shift/Win are held right now (Windows only)."""
    import ctypes

    state = ctypes.windll.user32.GetKeyState
    held = lambda vk: state(vk) & 0x8000  # noqa: E731
    modifiers = 0
    if held(0x11):
        modifiers |= MOD_CONTROL
    if held(0x12):
        modifiers |= MOD_ALT
    if held(0x10):
        modifiers |= MOD_SHIFT
    if held(0x5B) or held(0x5C):
        modifiers |= MOD_WIN
    return modifiers


MODIFIER_KEYS = {0x10, 0x11, 0x12, 0x5B, 0x5C, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5}
