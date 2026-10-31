"""Desktop window and system-tray icon for controlling the bulb.

    common.py      colours, the background worker, helpers
    app.py         main window, tray icon, startup (main)
    settings.py    settings window (Bulbs, App, Shortcuts, Automation tabs)
    quickpanel.py  pop-up from the tray icon
    dialogs.py     Xiaomi sign-in and schedule editor
"""

from .app import App, main
from .common import ACCENT, BG, ERROR, MUTED, PANEL, TEXT, Worker, make_icon_image, run_in_thread, work_area
from .dialogs import QrLoginDialog, ScheduleDialog
from .quickpanel import QuickPanel
from .settings import SettingsDialog

__all__ = ["App", "main", "QrLoginDialog", "ScheduleDialog", "QuickPanel", "SettingsDialog", "Worker",
           "make_icon_image", "run_in_thread", "work_area", "ACCENT", "BG", "ERROR", "MUTED", "PANEL", "TEXT"]
