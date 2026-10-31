"""Desktop window and system-tray icon for controlling the bulb."""

from __future__ import annotations

import io
import os
import queue
import sys
import threading
import tkinter as tk
import webbrowser
from collections import OrderedDict
from datetime import datetime
from tkinter import colorchooser, messagebox, simpledialog, ttk
from typing import Any, Callable

from . import __version__, automation, hotkey, i18n, pcevents, screensync, startup, updates
from .i18n import t
from . import config as config_mod
from .bulb import MAX_KELVIN, MIN_KELVIN, MODE_COLOR, Bulb, BulbGroup, BulbState
from .cloud import Cancelled, CloudDevice, QrLogin, XiaomiCloud
from .scenes import Scene
from .miio import MiIOError, discover, find_ip

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    Image = None
try:
    import pystray
except ImportError:  # the tray icon is optional
    pystray = None
if Image is None:
    pystray = None

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
    from .icon import draw_logo

    return draw_logo(size, on)


class QrLoginDialog(tk.Toplevel):
    """Shows a Xiaomi QR code, waits for it to be scanned, then lists devices."""

    def __init__(self, parent: tk.Misc, post: Post):
        super().__init__(parent)
        self.title("Sign in with Xiaomi")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.devices: list[CloudDevice] | None = None
        self._post = post
        self._login = QrLogin()
        self._photo = None
        self._login_url = ""

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Open the Xiaomi Home app on your phone, tap the scan icon (top right of the home screen) "
            "and scan this code.",
            wraplength=300,
        ).pack(fill="x")
        self.qr_label = tk.Label(body, bg="#ffffff", width=36, height=16, text="Loading…")
        self.qr_label.pack(pady=12)
        self.status = ttk.Label(body, text="Contacting Xiaomi…", style="Muted.TLabel", wraplength=300)
        self.status.pack(fill="x")
        ttk.Label(
            body,
            text="Your password is never entered here. Only your bulbs' IPs and tokens are saved.",
            style="Muted.TLabel",
            wraplength=300,
        ).pack(fill="x", pady=(6, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right")
        self.link_button = ttk.Button(buttons, text="Open in browser", command=self._open_link, state="disabled")
        self.link_button.pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.bind("<Escape>", lambda _e: self.close())
        self.grab_set()
        run_in_thread(self._post, self._start, self._qr_ready)

    def _start(self):
        qr = self._login.start()
        return qr, self._login.fetch_image(qr)

    def _qr_ready(self, result: Any) -> None:
        if not self.winfo_exists():
            return
        if isinstance(result, Exception):
            self._fail(result)
            return
        qr, png = result
        self._login_url = qr.login_url
        self.link_button.configure(state="normal" if qr.login_url else "disabled")
        if Image is not None:
            image = Image.open(io.BytesIO(png)).convert("RGB").resize((260, 260))
            self._photo = ImageTk.PhotoImage(image)
            self.qr_label.configure(image=self._photo, width=260, height=260, text="")
        else:
            self.qr_label.configure(text="Install Pillow to show the QR code,\nor use 'Open in browser'.")
        self.status.configure(text="Waiting for you to scan the code…")
        run_in_thread(self._post, lambda: self._login.wait(qr), self._signed_in)

    def _signed_in(self, result: Any) -> None:
        if isinstance(result, Cancelled) or not self.winfo_exists():
            return
        if isinstance(result, Exception):
            self._fail(result)
            return
        self.status.configure(text="Signed in. Reading your devices from every region…", foreground=MUTED)
        run_in_thread(self._post, lambda: XiaomiCloud(result).all_devices(), self._got_devices)

    def _got_devices(self, result: Any) -> None:
        if not self.winfo_exists():
            return
        if isinstance(result, Exception):
            self._fail(result)
            return
        self.devices = result
        self.destroy()

    def _fail(self, error: Exception) -> None:
        self.status.configure(text=str(error), foreground=ERROR)

    def _open_link(self) -> None:
        if self._login_url:
            webbrowser.open(self._login_url)

    def close(self) -> None:
        self._login.cancel()
        self.destroy()


def work_area() -> tuple[int, int, int, int]:
    """The desktop minus the taskbar (left, top, right, bottom) on the main screen."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            return rect.left, rect.top, rect.right, rect.bottom
    return 0, 0, 1280, 720


class QuickPanel(tk.Toplevel):
    """A small pop-up above the tray icon, like the Windows volume flyout."""

    WIDTH = 300

    def __init__(self, app: "App"):
        super().__init__(app)
        self._app = app
        self._syncing = False
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#3a3d46")  # 1 px border around the panel

        body = tk.Frame(self, bg=BG, padx=14, pady=12)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        top = tk.Frame(body, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text=app.cfg.display_name, bg=BG, fg=TEXT, font=("Segoe UI Semibold", 11)).pack(side="left")
        self.power = ttk.Button(top, text="Power", width=6, command=app.toggle)
        self.power.pack(side="right")

        self.brightness = self._scale(body, "Brightness", 1, 100, lambda v: app._quick_brightness(v))
        self.kelvin = self._scale(body, "White", MIN_KELVIN, MAX_KELVIN, lambda v: app._quick_kelvin(v))

        swatches = tk.Frame(body, bg=BG)
        swatches.pack(fill="x", pady=(10, 0))
        for color in PRESET_COLORS:
            swatch = tk.Label(swatches, bg=color, width=2, height=1, cursor="hand2")
            swatch.pack(side="left", expand=True, padx=1)
            swatch.bind("<Button-1>", lambda _e, c=color: app._set_color(c))

        if app.cfg.scenes:
            scenes = tk.Frame(body, bg=BG)
            scenes.pack(fill="x", pady=(10, 0))
            for column in range(3):
                scenes.columnconfigure(column, weight=1, uniform="scene")
            for index, scene in enumerate(app.cfg.scenes[:6]):
                chip = tk.Label(scenes, text=scene.name, bg=PANEL, fg=TEXT, font=("Segoe UI", 9), pady=4,
                                cursor="hand2", highlightthickness=0)
                chip.grid(row=index // 3, column=index % 3, sticky="we", padx=1, pady=1)
                chip.bind("<Button-1>", lambda _e, sc=scene: app.apply_scene(sc))
                chip.bind("<Enter>", lambda _e, c=chip: c.configure(bg="#474a55"))
                chip.bind("<Leave>", lambda _e, c=chip: c.configure(bg=PANEL))

        footer = tk.Frame(body, bg=BG)
        footer.pack(fill="x", pady=(10, 0))
        link = tk.Label(footer, text="Open Mi Bulb", bg=BG, fg=MUTED, font=("Segoe UI", 9), cursor="hand2")
        link.pack(side="left")
        link.bind("<Button-1>", lambda _e: (self.close(), app.show()))
        timer = tk.Label(footer, text="⏾ Sleep 30 min", bg=BG, fg=MUTED, font=("Segoe UI", 9), cursor="hand2")
        timer.pack(side="right")
        timer.bind("<Button-1>", lambda _e: app.start_sleep_timer(30))

        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<FocusOut>", lambda _e: self.after(150, self._close_if_unfocused))
        if app.bulb_state is not None:
            self.show_state(app.bulb_state)
        self._place()
        self.after(10, self.focus_force)

    def _scale(self, parent: tk.Misc, title: str, lo: int, hi: int, on_change: Callable[[int], None]) -> ttk.Scale:
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(10, 0))
        tk.Label(row, text=title, bg=BG, fg=MUTED, font=("Segoe UI", 9), width=10, anchor="w").pack(side="left")

        def changed(raw: str) -> None:
            if not self._syncing:
                on_change(int(float(raw)))

        scale = ttk.Scale(row, from_=lo, to=hi, orient="horizontal", command=changed)
        scale.pack(side="left", fill="x", expand=True)
        return scale

    def show_state(self, state: BulbState) -> None:
        self._syncing = True
        try:
            self.power.configure(text="On" if state.on else "Off",
                                 style="Accent.TButton" if state.on else "TButton")
            self.brightness.set(state.brightness)
            self.kelvin.set(state.color_temperature)
        finally:
            self._syncing = False

    def _place(self) -> None:
        self.update_idletasks()
        left, top, right, bottom = work_area()
        height = self.winfo_reqheight()
        self.geometry(f"{self.WIDTH}x{height}+{right - self.WIDTH - 12}+{bottom - height - 12}")

    def _close_if_unfocused(self) -> None:
        if not self.winfo_exists():
            return
        focused = self.focus_get()
        if focused is None or not str(focused).startswith(str(self)):
            self.close()

    def close(self) -> None:
        if self.winfo_exists():
            self.destroy()
        if self._app.quick_panel is self:
            self._app.quick_panel = None


class ScheduleDialog(tk.Toplevel):
    """Add or edit one schedule: a time, weekdays and an action."""

    def __init__(self, parent: tk.Misc, app: "App", schedule: automation.Schedule | None):
        super().__init__(parent)
        self.title("Schedule")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.result: automation.Schedule | None = None
        self._id = schedule.id if schedule else automation.new_id()
        self._enabled = schedule.enabled if schedule else True
        hour, minute = (schedule.time if schedule else "07:00").split(":")

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Time", style="Section.TLabel").pack(anchor="w")
        row = ttk.Frame(body)
        row.pack(anchor="w", pady=(4, 12))
        self.hour = tk.StringVar(value=hour)
        self.minute = tk.StringVar(value=minute)
        for var, top in ((self.hour, 23), (self.minute, 59)):
            spin = tk.Spinbox(row, from_=0, to=top, textvariable=var, width=3, format="%02.0f", wrap=True,
                              font=("Segoe UI", 12), bg=PANEL, fg=TEXT, buttonbackground=PANEL,
                              insertbackground=TEXT, relief="flat", justify="center")
            spin.pack(side="left")
            if var is self.hour:
                ttk.Label(row, text=" : ", font=("Segoe UI", 12)).pack(side="left")

        ttk.Label(body, text="Days", style="Section.TLabel").pack(anchor="w")
        days = ttk.Frame(body)
        days.pack(anchor="w", pady=(4, 0))
        chosen = schedule.days if schedule else automation.EVERY_DAY
        self.day_vars = [tk.BooleanVar(value=i in chosen) for i in range(7)]
        for i, name in enumerate(automation.DAY_NAMES):
            ttk.Checkbutton(days, text=name, variable=self.day_vars[i]).pack(side="left", padx=(0, 6))
        quick = ttk.Frame(body)
        quick.pack(anchor="w", pady=(6, 12))
        for label, picked in (("Every day", automation.EVERY_DAY), ("Weekdays", automation.WEEKDAYS),
                              ("Weekends", automation.WEEKEND)):
            ttk.Button(quick, text=label, command=lambda p=picked: self._pick_days(p)).pack(side="left", padx=(0, 6))

        ttk.Label(body, text="Do this", style="Section.TLabel").pack(anchor="w")
        self._actions = [("on", "Turn on"), ("off", "Turn off")]
        self._actions += [(f"sunrise:{m}", f"Sunrise wake-up ({m} min)") for m in automation.SUNRISE_MINUTES]
        self._actions += [(f"scene:{sc.id}", f"Scene: {sc.name}") for sc in app.cfg.scenes]
        self.action = ttk.Combobox(body, state="readonly", width=34, values=[label for _a, label in self._actions])
        self.action.pack(anchor="w", pady=(4, 0))
        current = schedule.action if schedule else "on"
        index = next((i for i, (a, _l) in enumerate(self._actions) if a == current), 0)
        self.action.current(index)

        self.error = ttk.Label(body, text="", style="Muted.TLabel", foreground=ERROR)
        self.error.pack(anchor="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=self._save).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _pick_days(self, days: list[int]) -> None:
        for i, var in enumerate(self.day_vars):
            var.set(i in days)

    def _save(self) -> None:
        try:
            time = automation.normalise_time(f"{self.hour.get()}:{self.minute.get()}")
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return
        days = [i for i, var in enumerate(self.day_vars) if var.get()]
        if not days:
            self.error.configure(text="Pick at least one day.")
            return
        action = self._actions[max(0, self.action.current())][0]
        self.result = automation.Schedule(self._id, time, days, action, self._enabled)
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: "App", cfg: config_mod.Config, post: Post, tab: str = "bulb"):
        super().__init__(parent)
        self.title("Mi Bulb settings")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.changed = False
        self._post = post
        self._did = ""
        self._editing: str | None = None  # id of the bulb shown in the detail fields
        self._cloud_devices: list[CloudDevice] = []
        self._app = parent

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        body = ttk.Frame(notebook, padding=16)
        app_tab = ttk.Frame(notebook, padding=16)
        keys_tab = ttk.Frame(notebook, padding=16)
        auto_tab = ttk.Frame(notebook, padding=16)
        notebook.add(body, text=t("Bulbs"))
        notebook.add(app_tab, text=t("App"))
        notebook.add(keys_tab, text=t("Shortcuts"))
        notebook.add(auto_tab, text=t("Automation"))
        self._capturing: str | None = None
        self._build_app_tab(app_tab)
        self._build_shortcuts_tab(keys_tab)
        self._build_automation_tab(auto_tab)
        notebook.select({"app": app_tab, "shortcuts": keys_tab, "automation": auto_tab}.get(tab, body))

        self._build_bulbs_tab(body)

        buttons = ttk.Frame(self, padding=(16, 12, 16, 16))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Save bulb", style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Label(buttons, text="App options are saved as you change them.", style="Muted.TLabel").pack(side="left")

        self.bind("<Return>", lambda _e: None if self._capturing else self._save())
        self.bind("<Escape>", lambda _e: self._end_capture() if self._capturing else self.destroy())
        self.bind("<KeyPress>", self._capture_key)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.grab_set()

    def _toggle_token(self) -> None:
        self.token_entry.configure(show="" if self.show_token.get() else "•")

    # ---- Bulbs tab ----------------------------------------------------------

    def _build_bulbs_tab(self, body: ttk.Frame) -> None:
        cfg = self._app.cfg
        body.columnconfigure(1, weight=1)
        ttk.Label(body, text="Your bulbs", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        listing = ttk.Frame(body)
        listing.grid(row=1, column=0, columnspan=2, sticky="we", pady=(6, 0))
        self.bulb_list = tk.Listbox(listing, height=4, bg=PANEL, fg=TEXT, selectbackground=ACCENT,
                                    selectforeground=BG, highlightthickness=0, borderwidth=0, activestyle="none",
                                    font=("Segoe UI", 10), exportselection=False)
        self.bulb_list.pack(side="left", fill="both", expand=True)
        self.bulb_list.bind("<<ListboxSelect>>", self._pick_bulb)
        side = ttk.Frame(listing)
        side.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(side, text="New", command=self._new_bulb).pack(fill="x")
        ttk.Button(side, text="Remove", command=self._remove_bulb).pack(fill="x", pady=(4, 0))

        ttk.Separator(body).grid(row=2, column=0, columnspan=2, sticky="we", pady=12)
        ttk.Label(body, text="Find bulbs automatically", style="Section.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Sign in by scanning a QR code with the Xiaomi Home app. "
                             "Your bulbs and their tokens are filled in for you.",
                  style="Muted.TLabel", wraplength=400).grid(row=4, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Button(body, text="Sign in with Xiaomi", style="Accent.TButton", command=self._cloud_login).grid(
            row=5, column=0, sticky="w")
        self.cloud_pick = ttk.Combobox(body, state="readonly", width=40)
        self.cloud_pick.grid(row=5, column=1, sticky="we", padx=(8, 0))
        self.cloud_pick.bind("<<ComboboxSelected>>", self._pick_cloud)
        self.cloud_pick.set(t("No devices yet"))
        self.add_all_button = ttk.Button(body, text="Add all lights from my account", command=self._add_all_cloud,
                                         state="disabled")
        self.add_all_button.grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        ttk.Separator(body).grid(row=7, column=0, columnspan=2, sticky="we", pady=12)
        ttk.Label(body, text="Bulb details (or enter them yourself)", style="Section.TLabel").grid(
            row=8, column=0, columnspan=2, sticky="w")
        self.name_var = tk.StringVar()
        self.ip_var = tk.StringVar()
        self.token_var = tk.StringVar()
        for row, (label, var, show) in enumerate(
            [("Name", self.name_var, ""), ("IP address", self.ip_var, ""), ("Token", self.token_var, "•")], start=9
        ):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4)
            entry = ttk.Entry(body, textvariable=var, width=40, show=show)
            entry.grid(row=row, column=1, sticky="we", pady=4, padx=(8, 0))
        self.token_entry = entry
        self.show_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Show token", variable=self.show_token, command=self._toggle_token).grid(
            row=12, column=1, sticky="w", padx=(8, 0))
        self.scan_button = ttk.Button(body, text="Scan network", command=self._scan)
        self.scan_button.grid(row=13, column=0, sticky="w", pady=4)
        self.found = ttk.Combobox(body, state="readonly", width=40)
        self.found.grid(row=13, column=1, sticky="we", pady=4, padx=(8, 0))
        self.found.bind("<<ComboboxSelected>>", self._pick_found)
        self.saved_label = ttk.Label(body, text="", style="Muted.TLabel")
        self.saved_label.grid(row=14, column=0, columnspan=2, sticky="w", pady=(6, 0))

        current = cfg.current_bulbs or cfg.bulbs
        self._editing = current[0].id if current else None
        self._refresh_bulb_list()
        self._load_bulb(cfg.bulb(self._editing) if self._editing else None)

    def _refresh_bulb_list(self) -> None:
        self.bulb_list.delete(0, "end")
        for index, info in enumerate(self._app.cfg.bulbs):
            self.bulb_list.insert("end", f"  {info.name}    {info.ip or 'no IP yet'}")
            if info.id == self._editing:
                self.bulb_list.selection_set(index)
        if not self._app.cfg.bulbs:
            self.bulb_list.insert("end", "  No bulbs yet: sign in with Xiaomi below")

    def _load_bulb(self, info: config_mod.BulbInfo | None) -> None:
        self.name_var.set(info.name if info else "")
        self.ip_var.set(info.ip if info else "")
        self.token_var.set(info.token if info else "")
        self._did = info.did if info else ""
        self.saved_label.configure(text="")

    def _pick_bulb(self, _event: object = None) -> None:
        selection = self.bulb_list.curselection()
        if not selection or selection[0] >= len(self._app.cfg.bulbs):
            return
        info = self._app.cfg.bulbs[selection[0]]
        self._editing = info.id
        self._load_bulb(info)

    def _new_bulb(self) -> None:
        self._editing = None
        self.bulb_list.selection_clear(0, "end")
        self._load_bulb(None)
        self.saved_label.configure(text="Fill in the details below, or sign in with Xiaomi, then click Save bulb.")

    def _remove_bulb(self) -> None:
        selection = self.bulb_list.curselection()
        cfg = self._app.cfg
        if not selection or selection[0] >= len(cfg.bulbs):
            return
        info = cfg.bulbs[selection[0]]
        if not messagebox.askyesno("Remove bulb", f"Remove {info.name} from Mi Bulb?", parent=self):
            return
        cfg.bulbs.remove(info)
        if cfg.selected == info.id:
            cfg.selected = ""
        self._bulbs_changed()
        self._editing = cfg.bulbs[0].id if cfg.bulbs else None
        self._refresh_bulb_list()
        self._load_bulb(cfg.bulb(self._editing) if self._editing else None)

    def _bulbs_changed(self) -> None:
        self.changed = True
        config_mod.save(self._app.cfg)
        self._app._apply_config()

    # ---- App tab ----------------------------------------------------------

    def _build_app_tab(self, tab: ttk.Frame) -> None:
        def section(text: str) -> None:
            ttk.Label(tab, text=text, style="Section.TLabel").pack(anchor="w", pady=(12, 4))

        ttk.Label(tab, text=f"Mi Bulb {__version__}", style="Title.TLabel").pack(anchor="w")

        section("Startup")
        self.startup_var = tk.BooleanVar(value=startup.is_enabled())
        box = ttk.Checkbutton(tab, text="Start Mi Bulb in the tray when I sign in to Windows",
                              variable=self.startup_var, command=self._toggle_startup)
        box.pack(anchor="w")
        if not startup.supported():
            box.configure(state="disabled")

        section("Tray icon")
        self.tray_click_var = tk.StringVar(value=self._app.cfg.tray_click)
        for value, text in (("panel", "Left-click opens the quick panel"), ("toggle", "Left-click toggles the light")):
            ttk.Radiobutton(tab, text=text, value=value, variable=self.tray_click_var,
                            command=self._set_tray_click).pack(anchor="w")

        section("Language")
        self.language_var = tk.StringVar(value=self._app.cfg.language)
        row = self._language_row = ttk.Frame(tab)
        row.pack(fill="x")
        for value, text in [("auto", "Automatic (Windows language)")] + list(i18n.LANGUAGES.items()):
            ttk.Radiobutton(row, text=text, value=value, variable=self.language_var,
                            command=self._set_language).pack(side="left", padx=(0, 12))
        self.language_note = ttk.Frame(tab)
        ttk.Label(self.language_note, text="Restart Mi Bulb to use the new language.",
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(self.language_note, text="Restart now", command=self._app.restart).pack(side="left", padx=(8, 0))

        section("Screen sync")
        self.sync_brightness_var = tk.BooleanVar(value=self._app.cfg.sync_brightness)
        ttk.Checkbutton(tab, text="Also follow how bright the screen is", variable=self.sync_brightness_var,
                        command=self._set_sync_brightness).pack(anchor="w")
        ttk.Label(tab, text="Works with windowed and borderless games. Exclusive fullscreen games may not "
                            "be captured; the light then keeps its last colour.",
                  style="Muted.TLabel", wraplength=420).pack(anchor="w")

        section("Updates")
        self.updates_var = tk.BooleanVar(value=self._app.cfg.check_updates)
        ttk.Checkbutton(tab, text="Install new versions automatically (checked when Mi Bulb starts)",
                        variable=self.updates_var, command=self._toggle_updates).pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(4, 0))
        self.update_button = ttk.Button(row, text="Check now", command=self._check_updates)
        self.update_button.pack(side="left")
        self.update_status = ttk.Label(row, text="", style="Muted.TLabel")
        self.update_status.pack(side="left", padx=(8, 0))

        section("Your data")
        folder = config_mod.find_config_path().parent
        ttk.Label(tab, text=f"Settings and your bulb's token are stored in\n{folder}",
                  style="Muted.TLabel", wraplength=380).pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Open folder", command=self._open_data_folder).pack(side="left")
        ttk.Button(row, text="Forget all bulbs", command=self._forget).pack(side="left", padx=(8, 0))

    def _toggle_startup(self) -> None:
        try:
            if self.startup_var.get():
                startup.enable()
            else:
                startup.disable()
        except OSError as exc:
            self.startup_var.set(startup.is_enabled())
            messagebox.showerror("Start with Windows", f"Could not change the setting: {exc}", parent=self)

    # ---- Automation tab ---------------------------------------------------

    def _build_automation_tab(self, tab: ttk.Frame) -> None:
        def section(text: str) -> None:
            ttk.Label(tab, text=text, style="Section.TLabel").pack(anchor="w", pady=(0, 4))

        section("Follow the PC")
        self.lock_off_var = tk.BooleanVar(value=self._app.cfg.lock_off)
        self.unlock_on_var = tk.BooleanVar(value=self._app.cfg.unlock_on)
        for text, var in (("Turn the light off when I lock the PC or it goes to sleep", self.lock_off_var),
                          ("Turn it back on when I return (only if Mi Bulb turned it off)", self.unlock_on_var)):
            box = ttk.Checkbutton(tab, text=text, variable=var, command=self._toggle_follow_pc)
            box.pack(anchor="w")
            if not pcevents.supported():
                box.configure(state="disabled")

        ttk.Label(tab, text="Schedule", style="Section.TLabel").pack(anchor="w", pady=(16, 4))
        self.schedule_list = ttk.Frame(tab)
        self.schedule_list.pack(fill="x")
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="+ Add schedule", command=self._add_schedule).pack(side="left")
        ttk.Label(tab, text="Schedules run while Mi Bulb is running (it can stay in the tray). "
                            "A sunrise starts at the set time and reaches full brightness at the end.",
                  style="Muted.TLabel", wraplength=420).pack(anchor="w", pady=(10, 0))
        self._render_schedules()

    def _toggle_follow_pc(self) -> None:
        self._app.cfg.lock_off = self.lock_off_var.get()
        self._app.cfg.unlock_on = self.unlock_on_var.get()
        config_mod.save(self._app.cfg)

    def _render_schedules(self) -> None:
        for child in self.schedule_list.winfo_children():
            child.destroy()
        if not self._app.cfg.schedules:
            ttk.Label(self.schedule_list, text="No schedules yet.", style="Muted.TLabel").pack(anchor="w")
        for schedule in sorted(self._app.cfg.schedules, key=lambda sc: sc.time):
            row = ttk.Frame(self.schedule_list)
            row.pack(fill="x", pady=1)
            var = tk.BooleanVar(value=schedule.enabled)
            text = (f"{schedule.time}   {automation.describe_days(schedule.days)}   →   "
                    f"{self._app.describe_action(schedule.action)}")
            ttk.Checkbutton(row, text=text, variable=var,
                            command=lambda sc=schedule, v=var: self._enable_schedule(sc, v.get())).pack(side="left")
            ttk.Button(row, text="✕", width=3, command=lambda sc=schedule: self._delete_schedule(sc)).pack(side="right")
            ttk.Button(row, text="Edit", command=lambda sc=schedule: self._edit_schedule(sc)).pack(side="right", padx=4)

    def _enable_schedule(self, schedule: automation.Schedule, enabled: bool) -> None:
        schedule.enabled = enabled
        config_mod.save(self._app.cfg)

    def _delete_schedule(self, schedule: automation.Schedule) -> None:
        self._app.cfg.schedules = [sc for sc in self._app.cfg.schedules if sc.id != schedule.id]
        config_mod.save(self._app.cfg)
        self._render_schedules()

    def _add_schedule(self) -> None:
        self._edit_schedule(None)

    def _edit_schedule(self, schedule: automation.Schedule | None) -> None:
        dialog = ScheduleDialog(self, self._app, schedule)
        self.wait_window(dialog)
        self.grab_set()
        if dialog.result is None:
            return
        others = [sc for sc in self._app.cfg.schedules if sc.id != dialog.result.id]
        self._app.cfg.schedules = others + [dialog.result]
        config_mod.save(self._app.cfg)
        self._render_schedules()

    # ---- Shortcuts tab ----------------------------------------------------

    def _build_shortcuts_tab(self, tab: ttk.Frame) -> None:
        self.shortcuts_var = tk.BooleanVar(value=self._app.cfg.hotkey)
        box = ttk.Checkbutton(tab, text="Use keyboard shortcuts (they work in any app)",
                              variable=self.shortcuts_var, command=self._toggle_shortcuts)
        box.pack(anchor="w")
        if not hotkey.supported():
            box.configure(state="disabled")

        grid = ttk.Frame(tab)
        grid.pack(fill="x", pady=(12, 0))
        grid.columnconfigure(2, weight=1)
        self._key_buttons: dict[str, ttk.Button] = {}
        self._key_status: dict[str, ttk.Label] = {}
        self._shortcut_rows = [(action, label) for action, label, _default in config_mod.SHORTCUT_ACTIONS]
        self._shortcut_rows += [(f"scene:{scene.id}", f"Scene: {scene.name}") for scene in self._app.cfg.scenes]
        for row, (action, label) in enumerate(self._shortcut_rows):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", pady=2)
            button = ttk.Button(grid, width=22, command=lambda a=action: self._start_capture(a))
            button.grid(row=row, column=1, sticky="w", padx=(12, 8), pady=2)
            status = ttk.Label(grid, text="", style="Muted.TLabel")
            status.grid(row=row, column=2, sticky="w")
            self._key_buttons[action] = button
            self._key_status[action] = status

        ttk.Label(
            tab,
            text="Click a shortcut, then press the keys you want. Esc cancels, Backspace clears it.\n"
            "On some keyboard layouts Ctrl+Alt+<key> also types a special character (AltGr). "
            "If a character stops working, pick a different shortcut.",
            style="Muted.TLabel",
            wraplength=420,
        ).pack(anchor="w", pady=(12, 8))
        ttk.Button(tab, text="Reset to defaults", command=self._reset_shortcuts).pack(anchor="w")
        self._refresh_shortcuts()

    def _refresh_shortcuts(self, message: tuple[str, str] | None = None) -> None:
        enabled = self._app.cfg.hotkey and hotkey.supported()
        for action, button in self._key_buttons.items():
            text = self._app.cfg.shortcuts.get(action, "")
            button.configure(text=text or "Not set", state="normal" if enabled else "disabled")
            problem = self._app.shortcut_problems.get(action) if enabled and text else None
            self._key_status[action].configure(text=problem or "", foreground=ERROR)
        if message:
            action, text = message
            self._key_status[action].configure(text=text, foreground=ERROR)

    def _toggle_shortcuts(self) -> None:
        self._app.set_shortcuts_enabled(self.shortcuts_var.get())
        self._refresh_shortcuts()

    def _reset_shortcuts(self) -> None:
        self._end_capture(apply=False)
        self._app.reset_shortcuts()
        self._refresh_shortcuts()

    def _start_capture(self, action: str) -> None:
        self._end_capture(apply=False)
        self._capturing = action
        # Registered shortcuts would swallow the keys, so pause them while recording.
        self._app.suspend_shortcuts()
        self._key_buttons[action].configure(text="Press keys…")
        self._key_status[action].configure(text="Esc to cancel", foreground=MUTED)
        self.focus_set()  # keep Space/Enter away from the buttons

    def _capture_key(self, event: tk.Event) -> str | None:
        action = self._capturing
        if action is None:
            return None
        key = event.keycode  # the Windows virtual-key code
        if key in hotkey.MODIFIER_KEYS:
            return "break"
        modifiers = hotkey.pressed_modifiers()
        if key == 0x1B and not modifiers:  # Esc
            self._end_capture()
            return "break"
        if key in (0x08, 0x2E) and not modifiers:  # Backspace / Delete clear it
            self._app.set_shortcut(action, "")
            self._end_capture()
            return "break"
        try:
            hotkey.validate(modifiers, key)
        except hotkey.ShortcutError as exc:
            self._key_status[action].configure(text=str(exc), foreground=ERROR)
            return "break"
        text = hotkey.format_shortcut(modifiers, key)
        for other, label in self._shortcut_rows:
            if other != action and self._app.cfg.shortcuts.get(other) == text:
                self._key_status[action].configure(text=f"{text} is already used for {label}.", foreground=ERROR)
                return "break"
        self._app.set_shortcut(action, text)
        self._end_capture()
        return "break"

    def _end_capture(self, apply: bool = True) -> None:
        if self._capturing is None:
            return
        self._capturing = None
        if apply:
            self._app.apply_shortcuts()
        self._refresh_shortcuts()

    def destroy(self) -> None:
        if self._capturing is not None:
            self._capturing = None
            self._app.apply_shortcuts()
        super().destroy()

    def _set_language(self) -> None:
        self._app.cfg.language = self.language_var.get()
        config_mod.save(self._app.cfg)
        if i18n.resolve(self._app.cfg.language) != i18n.current():
            self.language_note.pack(anchor="w", pady=(4, 0), after=self._language_row)
        else:
            self.language_note.pack_forget()

    def _set_sync_brightness(self) -> None:
        self._app.cfg.sync_brightness = self.sync_brightness_var.get()
        config_mod.save(self._app.cfg)
        if self._app.screen_sync is not None:
            self._app.screen_sync.match_brightness = self._app.cfg.sync_brightness

    def _set_tray_click(self) -> None:
        self._app.cfg.tray_click = self.tray_click_var.get()
        config_mod.save(self._app.cfg)

    def _toggle_updates(self) -> None:
        self._app.cfg.check_updates = self.updates_var.get()
        config_mod.save(self._app.cfg)

    def _check_updates(self) -> None:
        self.update_button.configure(state="disabled")
        self.update_status.configure(text="Checking…", foreground=MUTED)
        run_in_thread(self._post, updates.check, self._update_result)

    def _update_result(self, result: Any) -> None:
        if not self.winfo_exists():
            return
        self.update_button.configure(state="normal")
        if isinstance(result, Exception):
            self.update_status.configure(text="Couldn't reach GitHub.", foreground=ERROR)
        elif result is None:
            self.update_status.configure(text="You have the latest version.", foreground=MUTED)
        elif updates.is_installed():
            self.update_status.configure(text=f"Installing version {result.version}…", foreground=ACCENT)
            self.update_button.configure(state="disabled")
            self._app.start_update(result, automatic=False, on_status=self._update_progress)
        else:
            self._app.show_update(result)
            self.update_status.configure(text=f"Version {result.version} is available. Click to download.",
                                         foreground=ACCENT, cursor="hand2")
            self.update_status.bind("<Button-1>", lambda _e: webbrowser.open(result.url))

    def _update_progress(self, text: str, error: bool) -> None:
        if self.winfo_exists():
            self.update_status.configure(text=text, foreground=ERROR if error else ACCENT)
            if error:
                self.update_button.configure(state="normal")

    def _open_data_folder(self) -> None:
        folder = config_mod.find_config_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(folder)
        else:
            webbrowser.open(folder.as_uri())

    def _forget(self) -> None:
        if not messagebox.askyesno(
            "Forget all bulbs",
            "Remove every bulb's name, IP address and token from this PC?\n\n"
            "You can add them again any time with 'Sign in with Xiaomi'.",
            parent=self,
        ):
            return
        self._app.forget_bulbs()
        self.changed = True
        self._editing = None
        self._refresh_bulb_list()
        self._load_bulb(None)

    # ---- Xiaomi account -------------------------------------------------

    def _cloud_login(self) -> None:
        dialog = QrLoginDialog(self, self._post)
        self.wait_window(dialog)
        self.grab_set()
        if dialog.devices is None:
            return
        lights = [d for d in dialog.devices if d.is_light]
        # Show lights first, but keep everything in case the model isn't recognised.
        self._cloud_devices = lights + [d for d in dialog.devices if not d.is_light]
        if not self._cloud_devices:
            self.cloud_pick.configure(values=[])
            self.cloud_pick.set(t("No devices found on this account"))
            return
        self.cloud_pick.configure(values=[d.label for d in self._cloud_devices])
        self.cloud_pick.current(0)
        self._pick_cloud()
        self.add_all_button.configure(state="normal" if lights else "disabled",
                                      text=f"Add all {len(lights)} lights from my account" if len(lights) > 1
                                      else "Add all lights from my account")

    def _pick_cloud(self, _event: object = None) -> None:
        index = self.cloud_pick.current()
        if index < 0:
            return
        device = self._cloud_devices[index]
        # Already added? Then this updates that bulb instead of adding it twice.
        existing = next((b for b in self._app.cfg.bulbs if b.did and b.did == device.did), None)
        self._editing = existing.id if existing else None
        self._refresh_bulb_list()
        if existing is None:
            self.bulb_list.selection_clear(0, "end")
        self.name_var.set(device.name)
        self.ip_var.set(device.ip)
        self.token_var.set(device.token)
        self._did = device.did
        if not device.ip and device.did.isdigit():
            # The cloud doesn't always know the IP; ask the local network instead.
            self.ip_var.set("")
            run_in_thread(self._post, lambda: find_ip(int(device.did)), self._found_ip)

    def _found_ip(self, ip: Any) -> None:
        if self.winfo_exists() and isinstance(ip, str) and not self.ip_var.get():
            self.ip_var.set(ip)

    def _add_all_cloud(self) -> None:
        cfg = self._app.cfg
        added = 0
        for device in self._cloud_devices:
            if not device.is_light:
                continue
            existing = next((b for b in cfg.bulbs if b.did and b.did == device.did), None)
            if existing is not None:
                existing.token = device.token
                existing.ip = device.ip or existing.ip
                info = existing
            else:
                info = config_mod.BulbInfo(config_mod.new_bulb_id(), device.name, device.ip, device.token, device.did)
                cfg.bulbs.append(info)
                added += 1
            if not info.ip and info.did.isdigit():
                run_in_thread(self._post, lambda d=int(info.did): find_ip(d),
                              lambda ip, i=info: self._fill_ip(i, ip))
        if len(cfg.usable_bulbs) > 1 and not cfg.selected:
            cfg.selected = config_mod.ALL
        self._bulbs_changed()
        self._editing = cfg.bulbs[0].id if cfg.bulbs else None
        self._refresh_bulb_list()
        self.saved_label.configure(text=f"Added {added} new light(s). Pick one or All lights from the name "
                                        "at the top of the main window.")

    def _fill_ip(self, info: config_mod.BulbInfo, ip: Any) -> None:
        if isinstance(ip, str) and not info.ip:
            info.ip = ip
            self._bulbs_changed()
            if self.winfo_exists():
                self._refresh_bulb_list()

    # ---- local network --------------------------------------------------

    def _pick_found(self, _event: object = None) -> None:
        choice = self.found.get()
        if "device id" in choice:
            self.ip_var.set(choice.split()[0])

    def _scan(self) -> None:
        self.scan_button.configure(state="disabled", text="Scanning…")
        run_in_thread(self._post, discover, self._scan_done)

    def _scan_done(self, devices: Any) -> None:
        if not self.winfo_exists():
            return
        self.scan_button.configure(state="normal", text="Scan network")
        if isinstance(devices, Exception):
            devices = []
        values = [f"{ip}  (device id {did})" for ip, did in devices]
        self.found.configure(values=values)
        self.found.set(values[0] if values else t("No miIO devices found"))
        self._pick_found()

    def _save(self) -> None:
        ip = self.ip_var.get().strip()
        token = self.token_var.get().strip()
        if not ip and not token and self._editing is None:
            self.destroy()  # nothing to save
            return
        if not ip or len(token) != 32:
            messagebox.showerror("Bulb settings", "Enter the bulb's IP address and its 32-character token.", parent=self)
            return
        cfg = self._app.cfg
        name = self.name_var.get().strip() or "Light"
        info = cfg.bulb(self._editing) if self._editing else None
        if info is None and self._did:
            info = next((b for b in cfg.bulbs if b.did == self._did), None)
        if info is None:
            info = config_mod.BulbInfo(config_mod.new_bulb_id())
            cfg.bulbs.append(info)
        info.name, info.ip, info.token, info.did = name, ip, token, self._did
        self._editing = info.id
        self._bulbs_changed()
        self._refresh_bulb_list()
        self.saved_label.configure(text=f"Saved {name}.")


class App(tk.Tk):
    def __init__(self, start_minimized: bool = False):
        cfg = config_mod.load()
        i18n.set_language(i18n.resolve(cfg.language))
        i18n.install_tk()
        super().__init__()
        self.title("Mi Bulb")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._setup_style()

        self.cfg = cfg
        self.bulb: Bulb | None = None
        self.bulb_state: BulbState | None = None
        self._syncing = False  # True while updating widgets from the bulb's state
        self._ui_calls: queue.Queue[Callable[[], None]] = queue.Queue()
        self.worker = Worker(self._ui_calls.put)
        self.tray = None
        self.hotkeys = hotkey.HotkeyManager(lambda action: self._ui_calls.put(lambda: self.run_shortcut(action)))
        self.shortcut_problems: dict[str, str] = {}
        self._updating = False
        self._settings_open = False
        self._program: dict | None = None  # running sleep timer or sunrise
        self.quick_panel: QuickPanel | None = None
        self.screen_sync: screensync.ScreenSync | None = None
        self._schedules_fired: set[tuple[str, str]] = set()
        self._off_by_pc = False
        self._last_pc_event = ("", 0.0)
        self.pc_watcher = pcevents.PcEventWatcher(lambda event: self._ui_calls.put(lambda: self._on_pc_event(event)))

        self._build()
        self._apply_config()
        self._poll_ui_calls()
        self._start_tray()
        self.apply_shortcuts()
        self.pc_watcher.start()
        self._schedule_tick()
        try:
            startup.repair()
        except OSError:
            pass
        if self.cfg.check_updates:
            run_in_thread(self._ui_calls.put, updates.check, self._startup_update)

        if Image is not None:
            self._icons = [ImageTk.PhotoImage(make_icon_image(size=n)) for n in (64, 32, 16)]
            self.iconphoto(True, *self._icons)
        if start_minimized and self.tray is not None:
            self.withdraw()
        if not self.cfg.is_complete:
            self.after(200, self.open_settings)

    # ---- layout -------------------------------------------------------

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 14))
        style.configure("Section.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 10))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 6), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", TEXT)])
        style.configure("TButton", background=PANEL, foreground=TEXT, borderwidth=0, padding=(10, 6))
        style.map("TButton", background=[("active", "#3a3d46"), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#1e1f24")
        style.map("Accent.TButton", background=[("active", "#ffd966")])
        style.configure("Power.TButton", font=("Segoe UI Semibold", 12), padding=(10, 12))
        style.configure("PowerOn.TButton", font=("Segoe UI Semibold", 12), padding=(10, 12), background=ACCENT, foreground="#1e1f24")
        style.map("PowerOn.TButton", background=[("active", "#ffd966")])
        style.configure("TRadiobutton", background=BG, foreground=TEXT, indicatorbackground=PANEL,
                        indicatorforeground="#1e1f24", indicatormargin=(0, 0, 8, 0))
        style.map("TRadiobutton", background=[("active", BG)],
                  indicatorbackground=[("selected", ACCENT), ("active", "#3a3d46")])
        style.configure("TCheckbutton", background=BG, foreground=TEXT, indicatorbackground=PANEL,
                        indicatorforeground="#1e1f24", indicatormargin=(0, 0, 8, 0))
        style.map("TCheckbutton", background=[("active", BG)],
                  indicatorbackground=[("selected", ACCENT), ("active", "#3a3d46")])
        style.configure("Horizontal.TScale", background=PANEL, troughcolor="#3a3d46")
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=TEXT)

    def _build(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root)
        header.pack(fill="x")
        self.title_label = ttk.Label(header, text="Light", style="Title.TLabel")
        self.title_label.pack(side="left")
        self.title_label.bind("<Button-1>", self._bulb_menu)
        ttk.Button(header, text="⚙", width=3, command=self.open_settings).pack(side="right")
        ttk.Button(header, text="⟳", width=3, command=self.refresh).pack(side="right", padx=(0, 6))
        self.timer_button = ttk.Button(header, text="⏾", width=3, command=self._timer_menu)
        self.timer_button.pack(side="right", padx=(0, 6))

        self.power_button = ttk.Button(root, text="Power", style="Power.TButton", command=self.toggle)
        self.power_button.pack(fill="x", pady=(12, 12))

        self.brightness = tk.IntVar(value=50)
        self.brightness_label = self._slider(
            root, "Brightness", self.brightness, 1, 100, lambda v: f"{v}%", self._on_brightness
        )

        self.kelvin = tk.IntVar(value=4000)
        self.kelvin_label = self._slider(
            root, "White temperature", self.kelvin, MIN_KELVIN, MAX_KELVIN, lambda v: f"{v} K", self._on_kelvin
        )
        whites = ttk.Frame(root)
        whites.pack(fill="x", pady=(0, 12))
        for name, kelvin in PRESET_WHITES:
            ttk.Button(whites, text=name, command=lambda k=kelvin: self._set_kelvin(k)).pack(
                side="left", expand=True, fill="x", padx=2
            )

        colors = ttk.Frame(root, style="Panel.TFrame", padding=12)
        colors.pack(fill="x")
        top = ttk.Frame(colors, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Colour", style="Panel.TLabel").pack(side="left")
        self.color_swatch = tk.Label(top, width=3, bg="#ffffff", relief="flat")
        self.color_swatch.pack(side="right")
        ttk.Button(top, text="Pick…", command=self.pick_color).pack(side="right", padx=(0, 8))
        self.sync_button = ttk.Button(top, text="Screen sync", command=self.toggle_screen_sync)
        self.sync_button.pack(side="right", padx=(0, 8))
        swatches = tk.Frame(colors, bg=PANEL)
        swatches.pack(fill="x", pady=(10, 0))
        for color in PRESET_COLORS:
            swatch = tk.Label(swatches, bg=color, width=3, height=1, cursor="hand2")
            swatch.pack(side="left", expand=True, padx=2)
            swatch.bind("<Button-1>", lambda _e, c=color: self._set_color(c))

        scenes = ttk.Frame(root, style="Panel.TFrame", padding=12)
        scenes.pack(fill="x", pady=(8, 0))
        top = ttk.Frame(scenes, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text="Scenes", style="Panel.TLabel").pack(side="left")
        ttk.Button(top, text="+ Save current", command=self.save_current_scene).pack(side="right")
        self.scenes_grid = tk.Frame(scenes, bg=PANEL)
        self.scenes_grid.pack(fill="x", pady=(10, 0))
        ttk.Label(scenes, text="Click to apply · right-click to update, rename or delete",
                  style="PanelMuted.TLabel").pack(anchor="w", pady=(8, 0))
        self._render_scenes()

        self.status_label = ttk.Label(root, text="", style="Muted.TLabel")
        self.status_label.pack(fill="x", pady=(12, 0))
        # Shown only when a newer release exists
        self.update_label = ttk.Label(root, text="", style="Muted.TLabel", foreground=ACCENT, cursor="hand2")
        # Shown while a sleep timer or sunrise runs; click to cancel
        self.program_label = ttk.Label(root, text="", style="Muted.TLabel", foreground=ACCENT, cursor="hand2")
        self.program_label.bind("<Button-1>", lambda _e: self._stop_running())

        self.protocol("WM_DELETE_WINDOW", self.hide_or_quit)
        self.bind("<space>", lambda _e: self.toggle())

    def _slider(self, parent, title, var, lo, hi, fmt, on_change) -> ttk.Label:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=12)
        frame.pack(fill="x", pady=(0, 8))
        top = ttk.Frame(frame, style="Panel.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text=title, style="Panel.TLabel").pack(side="left")
        value_label = ttk.Label(top, text=fmt(var.get()), style="PanelMuted.TLabel")
        value_label.pack(side="right")

        def changed(raw: str) -> None:
            value = int(float(raw))
            var.set(value)
            value_label.configure(text=fmt(value))
            if not self._syncing:
                on_change(value)

        scale = ttk.Scale(frame, from_=lo, to=hi, orient="horizontal", length=320, command=changed)
        scale.pack(fill="x", pady=(8, 0))
        value_label.scale = scale  # kept so _show_state can move the slider
        value_label.fmt = fmt
        return value_label

    # ---- bulb commands --------------------------------------------------

    def _apply_config(self) -> None:
        name = self.cfg.display_name
        several = len(self.cfg.usable_bulbs) > 1
        self.title_label.configure(text=f"{name} ▾" if several else name, cursor="hand2" if several else "")
        self.title(f"{name} – Mi Bulb")
        if self.tray is not None:
            self.tray.update_menu()
        if self.cfg.is_complete:
            try:
                self.bulb = BulbGroup(self.cfg.current_bulbs, on_moved=self._bulb_moved)
            except MiIOError as exc:
                self.bulb = None
                self._set_status(str(exc), error=True)
                return
            self.refresh()
        else:
            self.bulb = None
            self._set_status("Not configured – open settings (⚙) to add your bulb.")

    def _run(self, key: str, func: Callable[[Bulb], Any], refresh: bool = False, manual: bool = True) -> None:
        if manual and key != "status":
            # You took over, so stop a timer, sunrise or screen sync.
            if self._program is not None:
                self.cancel_program(quiet=True)
            if self.screen_sync is not None:
                self.stop_screen_sync(quiet=True)
        bulb = self.bulb
        if bulb is None:
            self._set_status("Not configured – open settings (⚙) to add your bulb.", error=True)
            return

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self._set_status(str(result), error=True)
            elif isinstance(result, BulbState):
                self._show_state(result)
            elif refresh:
                self.refresh()
            else:
                self._set_status(f"Connected to {self._target_text()}")

        self.worker.submit(key, lambda: func(bulb), done)

    def _target_text(self) -> str:
        current = self.cfg.current_bulbs
        return current[0].ip if len(current) == 1 else f"{len(current)} lights"

    def _bulb_moved(self, info: config_mod.BulbInfo) -> None:
        # Called from the worker thread when a bulb was found at a new IP.
        def save() -> None:
            config_mod.save(self.cfg)
            self._set_status(f"Found {info.name} at its new address {info.ip}.")

        self._ui_calls.put(save)

    def _bulb_menu(self, _event: object = None) -> None:
        usable = self.cfg.usable_bulbs
        if len(usable) < 2:
            return
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT, activebackground=ACCENT, activeforeground=BG,
                       selectcolor=ACCENT)
        choice = tk.StringVar(value=self.cfg.selected or usable[0].id)
        menu.add_radiobutton(label="All lights", value=config_mod.ALL, variable=choice,
                             command=lambda: self.select_bulb(config_mod.ALL))
        menu.add_separator()
        for info in usable:
            menu.add_radiobutton(label=info.name, value=info.id, variable=choice,
                                 command=lambda i=info.id: self.select_bulb(i))
        menu._choice = choice  # keep the variable alive while the menu is open
        menu.tk_popup(self.title_label.winfo_rootx(), self.title_label.winfo_rooty() + self.title_label.winfo_height())

    def select_bulb(self, bulb_id: str) -> None:
        self.cfg.selected = bulb_id
        config_mod.save(self.cfg)
        self._apply_config()

    def refresh(self) -> None:
        self._run("status", lambda b: b.status())

    def toggle(self) -> None:
        self._run("power", lambda b: b.toggle(), refresh=True)

    def turn(self, on: bool, manual: bool = True) -> None:
        self._run("power", lambda b: b.turn_on() if on else b.turn_off(), refresh=True, manual=manual)

    def _on_brightness(self, value: int) -> None:
        self._run("brightness", lambda b: b.set_brightness(value))

    def _on_kelvin(self, value: int) -> None:
        self._run("colour", lambda b: b.set_color_temperature(value))

    def _set_kelvin(self, kelvin: int) -> None:
        self._sync_slider(self.kelvin_label, kelvin)
        self._run("colour", lambda b: b.set_color_temperature(kelvin), refresh=True)

    # ---- scenes ---------------------------------------------------------------

    def _render_scenes(self) -> None:
        for child in self.scenes_grid.winfo_children():
            child.destroy()
        chip_bg, chip_hover = "#3a3d46", "#474a55"
        columns = 3
        for column in range(columns):
            self.scenes_grid.columnconfigure(column, weight=1, uniform="scene")
        for index, scene in enumerate(self.cfg.scenes):
            chip = tk.Frame(self.scenes_grid, bg=chip_bg, cursor="hand2")
            chip.grid(row=index // columns, column=index % columns, sticky="we", padx=2, pady=2)
            swatch = tk.Label(chip, bg=scene.swatch, width=2)
            swatch.pack(side="left", fill="y")
            name = tk.Label(chip, text=scene.name, bg=chip_bg, fg=TEXT, font=("Segoe UI", 9), anchor="w",
                            padx=6, pady=5)
            name.pack(side="left", fill="x", expand=True)
            for widget in (chip, swatch, name):
                widget.bind("<Button-1>", lambda _e, sc=scene: self.apply_scene(sc))
                widget.bind("<Button-3>", lambda e, sc=scene: self._scene_menu(e, sc))
            for widget in (chip, name):
                widget.bind("<Enter>", lambda _e, w=(chip, name): [x.configure(bg=chip_hover) for x in w])
                widget.bind("<Leave>", lambda _e, w=(chip, name): [x.configure(bg=chip_bg) for x in w])
        if not self.cfg.scenes:
            tk.Label(self.scenes_grid, text="No scenes yet", bg=PANEL, fg=MUTED,
                     font=("Segoe UI", 9)).grid(row=0, column=0, columnspan=columns, sticky="w")

    def _scenes_changed(self) -> None:
        config_mod.save(self.cfg)
        self._render_scenes()
        if self.tray is not None:
            self.tray.update_menu()

    def apply_scene(self, scene: Scene) -> None:
        if scene.is_color:
            self.color_swatch.configure(bg=scene.swatch)
            self._run("colour", lambda b: b.apply_scene(scene.brightness, rgb=scene.color), refresh=True)
        else:
            self._sync_slider(self.kelvin_label, scene.kelvin)
            self._run("colour", lambda b: b.apply_scene(scene.brightness, kelvin=scene.kelvin), refresh=True)
        self._sync_slider(self.brightness_label, scene.brightness)

    def apply_scene_id(self, scene_id: str) -> None:
        scene = next((sc for sc in self.cfg.scenes if sc.id == scene_id), None)
        if scene is not None:
            self.apply_scene(scene)

    def _with_current_state(self, then: Callable[[BulbState], None]) -> None:
        """Read the bulb fresh (sliders may have moved since the last refresh), then continue."""
        bulb = self.bulb
        if bulb is None:
            self._set_status("Add your bulb first (⚙).", error=True)
            return

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self._set_status(str(result), error=True)
            else:
                self._show_state(result)
                then(result)

        self.worker.submit("status", bulb.status, done)

    def save_current_scene(self) -> None:
        def ask(state: BulbState) -> None:
            name = simpledialog.askstring("Save scene", "Name for this scene:", parent=self)
            if name and name.strip():
                self.cfg.scenes.append(Scene.from_state(name.strip()[:30], state))
                self._scenes_changed()
                self._set_status(f"Saved scene \"{name.strip()}\". Give it a shortcut in settings.")

        self._with_current_state(ask)

    def _scene_menu(self, event: tk.Event, scene: Scene) -> None:
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT, activebackground=ACCENT, activeforeground=BG)
        menu.add_command(label="Apply", command=lambda: self.apply_scene(scene))
        menu.add_command(label="Update to current light", command=lambda: self._update_scene(scene))
        menu.add_command(label="Rename…", command=lambda: self._rename_scene(scene))
        menu.add_command(label="Set shortcut…", command=lambda: self.open_settings("shortcuts"))
        menu.add_separator()
        menu.add_command(label="Delete", command=lambda: self._delete_scene(scene))
        menu.tk_popup(event.x_root, event.y_root)

    def _update_scene(self, scene: Scene) -> None:
        def update(state: BulbState) -> None:
            fresh = Scene.from_state(scene.name, state)
            fresh.id = scene.id
            self.cfg.scenes = [fresh if sc.id == scene.id else sc for sc in self.cfg.scenes]
            self._scenes_changed()
            self._set_status(f"Updated scene \"{scene.name}\".")

        self._with_current_state(update)

    def _rename_scene(self, scene: Scene) -> None:
        name = simpledialog.askstring("Rename scene", "New name:", initialvalue=scene.name, parent=self)
        if name and name.strip():
            scene.name = name.strip()[:30]
            self._scenes_changed()

    def _delete_scene(self, scene: Scene) -> None:
        if not messagebox.askyesno("Delete scene", f"Delete the scene \"{scene.name}\"?", parent=self):
            return
        self.cfg.scenes = [sc for sc in self.cfg.scenes if sc.id != scene.id]
        had_shortcut = self.cfg.shortcuts.pop(f"scene:{scene.id}", "")
        self._scenes_changed()
        if had_shortcut:
            self.apply_shortcuts()

    def _set_color(self, hex_color: str) -> None:
        self.color_swatch.configure(bg=hex_color)
        rgb = int(hex_color.lstrip("#"), 16)
        self._run("colour", lambda b: b.set_color(rgb), refresh=True)

    def pick_color(self) -> None:
        initial = self.bulb_state.color_hex if self.bulb_state else "#ffffff"
        _rgb, hex_color = colorchooser.askcolor(color=initial, title="Pick a colour", parent=self)
        if hex_color:
            self._set_color(hex_color)

    # ---- state display -------------------------------------------------

    def _sync_slider(self, label: ttk.Label, value: int) -> None:
        self._syncing = True
        try:
            label.scale.set(value)
            label.configure(text=label.fmt(value))
        finally:
            self._syncing = False

    def _show_state(self, state: BulbState) -> None:
        self.bulb_state = state
        if self.quick_panel is not None and self.quick_panel.winfo_exists():
            self.quick_panel.show_state(state)
        self.power_button.configure(
            text="On" if state.on else "Off", style="PowerOn.TButton" if state.on else "Power.TButton"
        )
        self._sync_slider(self.brightness_label, state.brightness)
        self._sync_slider(self.kelvin_label, state.color_temperature)
        self.color_swatch.configure(bg=state.color_hex if state.mode == MODE_COLOR else "#ffffff")
        mode = "colour" if state.mode == MODE_COLOR else "white"
        self._set_status(f"Connected to {self._target_text()} · {mode} mode")
        if self.tray is not None:
            self.tray.icon = make_icon_image(state.on)
            self.tray.title = t(f"{self.cfg.display_name}: {'on' if state.on else 'off'}")

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status_label.configure(text=text, foreground=ERROR if error else MUTED)

    def open_settings(self, tab: str = "bulb") -> None:
        self.show()
        if self._settings_open:
            return
        self._settings_open = True
        try:
            dialog = SettingsDialog(self, self.cfg, self._ui_calls.put, tab=tab)
            self.wait_window(dialog)
        finally:
            self._settings_open = False
        if dialog.changed:
            self._apply_config()

    # ---- app options ------------------------------------------------------

    def apply_shortcuts(self) -> None:
        bindings = self.cfg.shortcuts if self.cfg.hotkey else {}
        self.shortcut_problems = self.hotkeys.apply(bindings)

    def suspend_shortcuts(self) -> None:
        self.hotkeys.stop()

    def set_shortcuts_enabled(self, enabled: bool) -> None:
        self.cfg.hotkey = enabled
        config_mod.save(self.cfg)
        self.apply_shortcuts()

    def set_shortcut(self, action: str, text: str) -> None:
        self.cfg.shortcuts[action] = text
        config_mod.save(self.cfg)

    def reset_shortcuts(self) -> None:
        self.cfg.shortcuts = dict(config_mod.DEFAULT_SHORTCUTS)
        config_mod.save(self.cfg)
        self.apply_shortcuts()

    def run_shortcut(self, action: str) -> None:
        whites = {"warm": 2700, "neutral": 4000, "daylight": 6500}
        if action == "toggle":
            self.toggle()
        elif action in ("on", "off"):
            self.turn(action == "on")
        elif action in ("brighter", "dimmer"):
            self._step_brightness(10 if action == "brighter" else -10)
        elif action in whites:
            self._set_kelvin(whites[action])
        elif action.startswith("scene:"):
            self.apply_scene_id(action.split(":", 1)[1])
        elif action == "window":
            self.show()
        elif action == "screen_sync":
            self.toggle_screen_sync()
        elif action == "sleep":
            if self._program and self._program["name"] == "sleep":
                self.cancel_program()
            else:
                self.start_sleep_timer(30)

    def _step_brightness(self, delta: int) -> None:
        # The slider holds the latest value, so quick repeated presses add up.
        value = max(1, min(100, self.brightness.get() + delta))
        self._sync_slider(self.brightness_label, value)
        self._run("brightness", lambda b: b.set_brightness(value))

    def show_update(self, update: updates.Update) -> None:
        self.update_label.configure(text=f"Mi Bulb {update.version} is available. Click to download.",
                                    foreground=ACCENT)
        self.update_label.bind("<Button-1>", lambda _e: webbrowser.open(update.url))
        self.update_label.pack(fill="x", pady=(4, 0))

    def _startup_update(self, result: Any) -> None:
        if not isinstance(result, updates.Update):
            return  # up to date, or offline: try again next start
        if updates.is_installed() and result.version != self.cfg.skipped_update:
            self.start_update(result, automatic=True)
        else:
            self.show_update(result)

    def start_update(self, update: updates.Update, automatic: bool,
                     on_status: Callable[[str, bool], None] | None = None) -> None:
        """Download, verify and run the installer, then quit so it can replace the app."""
        if self._updating:
            return
        self._updating = True

        def status(text: str, error: bool = False) -> None:
            self.update_label.configure(text=text, foreground=ERROR if error else ACCENT)
            self.update_label.unbind("<Button-1>")
            self.update_label.pack(fill="x", pady=(4, 0))
            if on_status is not None:
                on_status(text, error)

        def progress(percent: int) -> None:
            self._ui_calls.put(lambda: status(f"Downloading Mi Bulb {update.version}… {percent}%"))

        def downloaded(result: Any) -> None:
            if isinstance(result, Exception):
                self._updating = False
                status(f"Update failed: {result}", error=True)
                return
            status(f"Installing Mi Bulb {update.version}. It will reopen by itself.")
            minimized = self.state() == "withdrawn"
            try:
                updates.launch_installer(result, minimized)
            except OSError:
                # Usually the admin prompt was cancelled. Don't ask again on every start.
                self._updating = False
                if automatic:
                    self.cfg.skipped_update = update.version
                    config_mod.save(self.cfg)
                status(f"Update to {update.version} was cancelled. Use Settings → App → Check now to retry.",
                       error=True)
                return
            # The installer waits for this copy to close before replacing it.
            self.after(500, self.quit_app)

        status(f"Downloading Mi Bulb {update.version}…")
        run_in_thread(self._ui_calls.put, lambda: updates.download(update, progress), downloaded)

    def forget_bulbs(self) -> None:
        self.cfg = config_mod.forget_bulbs(self.cfg)
        config_mod.save(self.cfg)
        self.bulb_state = None
        self.power_button.configure(text="Power", style="Power.TButton")
        self._apply_config()
        if self.tray is not None:
            self.tray.icon = make_icon_image(False)
            self.tray.title = "Mi Bulb"

    # ---- window & tray --------------------------------------------------

    def _poll_ui_calls(self) -> None:
        # Background threads hand work to Tk through this queue, since Tk
        # widgets may only be touched from the main thread.
        while True:
            try:
                self._ui_calls.get_nowait()()
            except queue.Empty:
                break
        self._poll_id = self.after(50, self._poll_ui_calls)

    def _start_tray(self) -> None:
        if pystray is None:
            return
        post = self._ui_calls.put

        def action(func: Callable[[int], None], value: int) -> Callable[[], None]:
            # pystray only accepts callbacks with at most two parameters.
            return lambda: post(lambda: func(value))

        def scene_action(scene_id: str) -> Callable[[], None]:
            return lambda: post(lambda: self.apply_scene_id(scene_id))

        def light_item(bulb_id: str, name: str) -> "pystray.MenuItem":
            return pystray.MenuItem(name, lambda: post(lambda: self.select_bulb(bulb_id)), radio=True,
                                    checked=lambda _item: (self.cfg.selected or "") == bulb_id
                                    or (not self.cfg.selected and self.cfg.usable_bulbs
                                        and self.cfg.usable_bulbs[0].id == bulb_id))

        def light_items():
            yield light_item(config_mod.ALL, t("All lights"))
            yield pystray.Menu.SEPARATOR
            for info in self.cfg.usable_bulbs:
                yield light_item(info.id, info.name)

        menu = pystray.Menu(
            # Left-clicking the icon runs the default item: the quick panel or toggle (see settings).
            pystray.MenuItem(t("Quick panel"), lambda: post(self._tray_click), default=True, visible=False),
            pystray.MenuItem(t("Light"), pystray.Menu(light_items),
                             visible=lambda _item: len(self.cfg.usable_bulbs) > 1),
            pystray.MenuItem(t("Toggle"), lambda: post(self.toggle)),
            pystray.MenuItem(t("Turn on"), lambda: post(lambda: self.turn(True))),
            pystray.MenuItem(t("Turn off"), lambda: post(lambda: self.turn(False))),
            pystray.MenuItem(t("Brightness"), pystray.Menu(*[
                pystray.MenuItem(f"{level}%", action(self._tray_brightness, level))
                for level in (100, 75, 50, 25, 10)
            ])),
            pystray.MenuItem(t("White"), pystray.Menu(*[
                pystray.MenuItem(t(name), action(self._set_kelvin, kelvin))
                for name, kelvin in PRESET_WHITES
            ])),
            # A callable menu is rebuilt each time it opens, so it follows scene edits.
            pystray.MenuItem(t("Scenes"), pystray.Menu(lambda: (
                pystray.MenuItem(t(scene.name), scene_action(scene.id)) for scene in self.cfg.scenes
            ))),
            pystray.MenuItem(t("Screen sync"), lambda: post(self.toggle_screen_sync),
                             checked=lambda _item: self.screen_sync is not None),
            pystray.MenuItem(t("Sleep timer"), pystray.Menu(
                *[pystray.MenuItem(t(f"Off in {m} min"), action(self.start_sleep_timer, m))
                  for m in automation.SLEEP_TIMER_MINUTES],
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(t("Cancel timer"), lambda: post(self.cancel_program)),
            )),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(t("Open window"), lambda: post(self.show)),
            pystray.MenuItem(t("Settings…"), lambda: post(lambda: self.open_settings("app"))),
            pystray.MenuItem(t("Quit"), lambda: post(self.quit_app)),
        )
        self.tray = pystray.Icon("mibulb", make_icon_image(True), "Mi Bulb", menu)
        self.tray.run_detached()

    def show(self) -> None:
        self.deiconify()
        self.lift()
        # Windows won't let a background app steal focus, but a brief
        # "always on top" brings the window to the front reliably.
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def hide_or_quit(self) -> None:
        if self.tray is not None:
            self.withdraw()
        else:
            self.quit_app()

    # ---- automation: sleep timer, sunrise, schedules, follow the PC -----------

    def _timer_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT, activebackground=ACCENT, activeforeground=BG)
        for minutes in automation.SLEEP_TIMER_MINUTES:
            menu.add_command(label=f"Sleep timer: off in {minutes} min",
                             command=lambda m=minutes: self.start_sleep_timer(m))
        menu.add_separator()
        for minutes in automation.SUNRISE_MINUTES:
            menu.add_command(label=f"Sunrise now ({minutes} min)", command=lambda m=minutes: self.start_sunrise(m))
        if self._program is not None:
            menu.add_separator()
            menu.add_command(label="Cancel timer", command=self.cancel_program)
        menu.add_separator()
        menu.add_command(label="Schedules…", command=lambda: self.open_settings("automation"))
        x = self.timer_button.winfo_rootx()
        y = self.timer_button.winfo_rooty() + self.timer_button.winfo_height()
        menu.tk_popup(x, y)

    def start_sleep_timer(self, minutes: float) -> None:
        start = self.bulb_state.brightness if self.bulb_state else self.brightness.get()
        steps = automation.plan_sleep_timer(minutes, start)
        self._start_program("sleep", f"Sleep timer: off at {{end}}", steps, finish=lambda: self.turn(False, manual=False))

    def start_sunrise(self, minutes: float) -> None:
        steps = automation.plan_sunrise(minutes)
        self._start_program("sunrise", "Sunrise: full brightness at {end}", steps, finish=self.refresh)

    def _start_program(self, name: str, label: str, steps: list, finish: Callable[[], None]) -> None:
        self.cancel_program(quiet=True)
        started = datetime.now()
        end = datetime.fromtimestamp(started.timestamp() + steps[-1].at)
        self._program = {"name": name, "steps": steps, "index": 0, "start": started.timestamp(),
                         "finish": finish, "after": None, "label": label.format(end=end.strftime("%H:%M"))}
        self.program_label.configure(text=f"{self._program['label']}  ·  click to cancel")
        self.program_label.pack(fill="x", pady=(4, 0))
        self._program_step()

    def _program_step(self) -> None:
        program = self._program
        if program is None:
            return
        step = program["steps"][program["index"]]
        first = program["index"] == 0
        if step.kelvin is not None:
            self._run("program", lambda b: b.apply_scene(step.brightness, kelvin=step.kelvin), manual=False)
        elif first:
            pass  # a sleep timer starts from the current brightness
        else:
            self._run("program", lambda b: b.set_brightness(step.brightness), manual=False)
        self._sync_slider(self.brightness_label, step.brightness)
        if step.kelvin is not None:
            self._sync_slider(self.kelvin_label, step.kelvin)

        program["index"] += 1
        if program["index"] >= len(program["steps"]):
            finish = program["finish"]
            self._program = None
            self.program_label.pack_forget()
            finish()
            return
        wait = program["start"] + program["steps"][program["index"]].at - datetime.now().timestamp()
        program["after"] = self.after(max(0, int(wait * 1000)), self._program_step)

    def cancel_program(self, quiet: bool = False) -> None:
        program = self._program
        if program is None:
            return
        self._program = None
        if program["after"] is not None:
            self.after_cancel(program["after"])
        self.program_label.pack_forget()
        if not quiet:
            self._set_status("Timer cancelled.")

    def _stop_running(self) -> None:
        if self.screen_sync is not None:
            self.stop_screen_sync()
        else:
            self.cancel_program()

    def toggle_screen_sync(self) -> None:
        if self.screen_sync is not None:
            self.stop_screen_sync()
        else:
            self.start_screen_sync()

    def start_screen_sync(self) -> None:
        if self.bulb is None:
            self._set_status("Add your bulb first (⚙).", error=True)
            return
        self.cancel_program(quiet=True)
        self._run("power", lambda b: b.turn_on(), manual=False)

        def send(rgb: int, brightness: int | None) -> None:
            # Called from the capture thread; the worker keeps only the newest pending update.
            self._ui_calls.put(lambda: self._run(
                "sync", lambda b: b.sync_color(rgb, brightness, screensync.FADE_MS), manual=False))

        self.screen_sync = screensync.ScreenSync(send, match_brightness=self.cfg.sync_brightness)
        self.screen_sync.start()
        self.sync_button.configure(text="Stop sync", style="Accent.TButton")
        self.program_label.configure(text="Screen sync is on  ·  click to stop")
        self.program_label.pack(fill="x", pady=(4, 0))
        if self.tray is not None:
            self.tray.update_menu()

    def stop_screen_sync(self, quiet: bool = False) -> None:
        if self.screen_sync is None:
            return
        self.screen_sync.stop()
        self.screen_sync = None
        self.sync_button.configure(text="Screen sync", style="TButton")
        if self._program is None:
            self.program_label.pack_forget()
        if self.tray is not None:
            self.tray.update_menu()
        if not quiet:
            self._set_status("Screen sync stopped.")
            self.refresh()

    def _schedule_tick(self) -> None:
        now = datetime.now()
        minute = now.strftime("%Y-%m-%d %H:%M")
        for schedule in self.cfg.schedules:
            key = (schedule.id, minute)
            if schedule.due(now) and key not in self._schedules_fired:
                self._schedules_fired.add(key)
                self.run_schedule_action(schedule.action)
        # Forget old entries so the set stays small.
        self._schedules_fired = {k for k in self._schedules_fired if k[1] == minute}
        self._tick_id = self.after(15000, self._schedule_tick)

    def run_schedule_action(self, action: str) -> None:
        minutes = automation.sunrise_minutes(action)
        if minutes is not None:
            self.start_sunrise(minutes)
        elif action in ("on", "off"):
            self.turn(action == "on")
        elif action.startswith("scene:"):
            self.apply_scene_id(action.split(":", 1)[1])

    def describe_action(self, action: str) -> str:
        minutes = automation.sunrise_minutes(action)
        if minutes is not None:
            return f"Sunrise wake-up ({minutes} min)"
        if action == "on":
            return "Turn on"
        if action == "off":
            return "Turn off"
        if action.startswith("scene:"):
            scene = next((sc for sc in self.cfg.scenes if sc.id == action[6:]), None)
            return f"Scene: {scene.name}" if scene else "Scene (deleted)"
        return action

    def _on_pc_event(self, event: str) -> None:
        # Resume often arrives twice (automatic + user); ignore repeats within 10 s.
        now = datetime.now().timestamp()
        if self._last_pc_event[0] == event and now - self._last_pc_event[1] < 10:
            return
        self._last_pc_event = (event, now)
        if event in ("lock", "suspend"):
            self.stop_screen_sync(quiet=True)  # nothing to follow on a locked screen
        if event in ("lock", "suspend") and self.cfg.lock_off:
            if self.bulb_state is None or self.bulb_state.on:
                self._off_by_pc = True
                self.cancel_program(quiet=True)
                self.turn(False)
        elif event in ("unlock", "resume") and self.cfg.unlock_on and self._off_by_pc:
            self._off_by_pc = False
            # After sleep the network needs a moment to come back.
            self.after(4000 if event == "resume" else 0, lambda: self.turn(True))

    def toggle_quick_panel(self) -> None:
        if self.quick_panel is not None and self.quick_panel.winfo_exists():
            self.quick_panel.close()
            return
        self.quick_panel = QuickPanel(self)
        if self.bulb is not None:
            self.refresh()

    def _quick_brightness(self, value: int) -> None:
        self._sync_slider(self.brightness_label, value)
        self._on_brightness(value)

    def _quick_kelvin(self, value: int) -> None:
        self._sync_slider(self.kelvin_label, value)
        self._on_kelvin(value)

    def _tray_click(self) -> None:
        if self.cfg.tray_click == "toggle":
            self.toggle()
        else:
            self.toggle_quick_panel()

    def _tray_brightness(self, percent: int) -> None:
        self._sync_slider(self.brightness_label, percent)
        self._run("brightness", lambda b: b.set_brightness(percent), refresh=True)

    def restart(self) -> None:
        """Start a fresh copy (it waits for this one to close), then quit."""
        import subprocess

        if getattr(sys, "frozen", False):
            command = [sys.executable, "--restarted"]
        else:
            command = [sys.executable, "-m", "mibulb", "--restarted"]
        if self.state() == "withdrawn":
            command.append("--minimized")
        subprocess.Popen(command, close_fds=True)
        self.quit_app()

    def quit_app(self) -> None:
        self.after_cancel(self._poll_id)
        self.after_cancel(self._tick_id)
        self.cancel_program(quiet=True)
        self.stop_screen_sync(quiet=True)
        self.hotkeys.stop()
        self.pc_watcher.stop()
        if self.tray is not None:
            self.tray.stop()
        self.destroy()


def main(start_minimized: bool = False, restarted: bool = False) -> None:
    import time

    from .single_instance import InstanceServer, notify_existing

    if restarted:
        # Started by "Restart now": give the old copy a moment to close.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and notify_existing(show=False):
            time.sleep(0.25)

    # Already running? Bring that window forward instead of opening a second one.
    # A --minimized launch (e.g. at Windows startup) just exits quietly.
    if notify_existing(show=not start_minimized):
        return

    app = App(start_minimized=start_minimized)
    server = InstanceServer(lambda: app._ui_calls.put(app.show))
    try:
        app.mainloop()
    finally:
        server.close()
