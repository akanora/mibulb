"""Start Mi Bulb (in the tray) when you sign in to Windows.

Uses the per-user Run key, which is also what the installer's "start with
Windows" option writes, so the setting and the installer always agree.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Mi Bulb"


def supported() -> bool:
    return sys.platform == "win32"


def _legacy_shortcut() -> Path:
    # v0.2.0's installer put a shortcut in the Startup folder instead.
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Mi Bulb.lnk"


def launch_command() -> str:
    if getattr(sys, "frozen", False):  # the PyInstaller exe
        return f'"{sys.executable}" --minimized'
    # From source: pythonw avoids a console window.
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else python
    script = Path(__file__).resolve().parent.parent / "run_gui.py"
    if script.exists():
        return f'"{exe}" "{script}" --minimized'
    return f'"{exe}" -m mibulb --minimized'


def _read() -> str | None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, VALUE_NAME)[0]
    except OSError:
        return None


def is_enabled() -> bool:
    if not supported():
        return False
    return _read() is not None or _legacy_shortcut().exists()


def enable() -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, launch_command())
    _remove_legacy_shortcut()


def disable() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass
    _remove_legacy_shortcut()


def repair() -> None:
    """If startup is on but points at an exe that no longer exists (e.g. a moved portable exe), fix it."""
    if not supported():
        return
    command = _read()
    if command is None or not command.startswith('"'):
        return
    target = command[1:].split('"', 1)[0]
    if not Path(target).exists():
        enable()


def _remove_legacy_shortcut() -> None:
    try:
        _legacy_shortcut().unlink()
    except OSError:
        pass
