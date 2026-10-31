"""Desktop window and system-tray icon for controlling the bulb."""

from __future__ import annotations

import io
import os
import queue
import threading
import tkinter as tk
import webbrowser
from collections import OrderedDict
from tkinter import colorchooser, messagebox, ttk
from typing import Any, Callable

from . import __version__, hotkey, startup, updates
from . import config as config_mod
from .bulb import MAX_KELVIN, MIN_KELVIN, MODE_COLOR, Bulb, BulbState
from .cloud import Cancelled, CloudDevice, QrLogin, XiaomiCloud
from .miio import DeviceUnreachable, MiIOError, discover, find_ip

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


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: "App", cfg: config_mod.Config, post: Post, tab: str = "bulb"):
        super().__init__(parent)
        self.title("Mi Bulb settings")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.result: config_mod.Config | None = None
        self._cfg = cfg
        self._post = post
        self._did = cfg.did
        self._cloud_devices: list[CloudDevice] = []
        self._app = parent

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        body = ttk.Frame(notebook, padding=16)
        body.columnconfigure(1, weight=1)
        app_tab = ttk.Frame(notebook, padding=16)
        keys_tab = ttk.Frame(notebook, padding=16)
        notebook.add(body, text="Bulb")
        notebook.add(app_tab, text="App")
        notebook.add(keys_tab, text="Shortcuts")
        self._capturing: str | None = None
        self._build_app_tab(app_tab)
        self._build_shortcuts_tab(keys_tab)
        notebook.select({"app": app_tab, "shortcuts": keys_tab}.get(tab, body))

        ttk.Label(body, text="Find your bulb automatically", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            body,
            text="Sign in by scanning a QR code with the Xiaomi Home app. Your bulbs and their tokens are filled in for you.",
            style="Muted.TLabel",
            wraplength=380,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Button(body, text="Sign in with Xiaomi", style="Accent.TButton", command=self._cloud_login).grid(
            row=2, column=0, sticky="w"
        )
        self.cloud_pick = ttk.Combobox(body, state="readonly", width=40)
        self.cloud_pick.grid(row=2, column=1, sticky="we", padx=(8, 0))
        self.cloud_pick.bind("<<ComboboxSelected>>", self._pick_cloud)
        self.cloud_pick.set("No devices yet")

        ttk.Separator(body).grid(row=3, column=0, columnspan=2, sticky="we", pady=14)
        ttk.Label(body, text="Or enter it manually", style="Muted.TLabel").grid(row=4, column=0, columnspan=2, sticky="w")

        self.name_var = tk.StringVar(value=cfg.name)
        self.ip_var = tk.StringVar(value=cfg.ip)
        self.token_var = tk.StringVar(value=cfg.token)

        for row, (label, var, show) in enumerate(
            [("Name", self.name_var, ""), ("IP address", self.ip_var, ""), ("Token", self.token_var, "•")], start=5
        ):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4)
            entry = ttk.Entry(body, textvariable=var, width=40, show=show)
            entry.grid(row=row, column=1, sticky="we", pady=4, padx=(8, 0))
        self.token_entry = entry

        self.show_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Show token", variable=self.show_token, command=self._toggle_token).grid(
            row=8, column=1, sticky="w", padx=(8, 0)
        )

        self.scan_button = ttk.Button(body, text="Scan network", command=self._scan)
        self.scan_button.grid(row=9, column=0, sticky="w", pady=4)
        self.found = ttk.Combobox(body, state="readonly", width=40)
        self.found.grid(row=9, column=1, sticky="we", pady=4, padx=(8, 0))
        self.found.bind("<<ComboboxSelected>>", self._pick_found)

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

        section("Updates")
        self.updates_var = tk.BooleanVar(value=self._app.cfg.check_updates)
        ttk.Checkbutton(tab, text="Check for a new version when Mi Bulb starts",
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
        ttk.Button(row, text="Forget this bulb", command=self._forget).pack(side="left", padx=(8, 0))

    def _toggle_startup(self) -> None:
        try:
            if self.startup_var.get():
                startup.enable()
            else:
                startup.disable()
        except OSError as exc:
            self.startup_var.set(startup.is_enabled())
            messagebox.showerror("Start with Windows", f"Could not change the setting: {exc}", parent=self)

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
        for row, (action, label, _default) in enumerate(config_mod.SHORTCUT_ACTIONS):
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
        for other, label, _default in config_mod.SHORTCUT_ACTIONS:
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
        else:
            self._app.show_update(result)
            self.update_status.configure(text=f"Version {result.version} is available. Click to open.",
                                         foreground=ACCENT, cursor="hand2")
            self.update_status.bind("<Button-1>", lambda _e: webbrowser.open(result.url))

    def _open_data_folder(self) -> None:
        folder = config_mod.find_config_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(folder)
        else:
            webbrowser.open(folder.as_uri())

    def _forget(self) -> None:
        if not messagebox.askyesno(
            "Forget this bulb",
            "Remove the bulb's name, IP address and token from this PC?\n\n"
            "You can add it again any time with 'Sign in with Xiaomi'.",
            parent=self,
        ):
            return
        self._app.forget_bulb()
        self._cfg = self._app.cfg
        self.ip_var.set("")
        self.token_var.set("")
        self.name_var.set(self._cfg.name)
        self._did = ""

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
            self.cloud_pick.set("No devices found on this account")
            return
        self.cloud_pick.configure(values=[d.label for d in self._cloud_devices])
        self.cloud_pick.current(0)
        self._pick_cloud()

    def _pick_cloud(self, _event: object = None) -> None:
        index = self.cloud_pick.current()
        if index < 0:
            return
        device = self._cloud_devices[index]
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
        self.found.set(values[0] if values else "No miIO devices found")
        self._pick_found()

    def _save(self) -> None:
        ip = self.ip_var.get().strip()
        token = self.token_var.get().strip()
        if not ip and not token:
            self.destroy()  # nothing to save, e.g. after "Forget this bulb"
            return
        if not ip or len(token) != 32:
            messagebox.showerror("Bulb settings", "Enter the bulb's IP address and its 32-character token.", parent=self)
            return
        self.result = config_mod.Config(
            ip=ip,
            token=token,
            name=self.name_var.get().strip() or "Light",
            did=self._did,
            properties=self._cfg.properties,
            hotkey=self._app.cfg.hotkey,
            check_updates=self._app.cfg.check_updates,
            shortcuts=self._app.cfg.shortcuts,
        )
        self.destroy()


class App(tk.Tk):
    def __init__(self, start_minimized: bool = False):
        super().__init__()
        self.title("Mi Bulb")
        self.configure(bg=BG)
        self.resizable(False, False)
        self._setup_style()

        self.cfg = config_mod.load()
        self.bulb: Bulb | None = None
        self.bulb_state: BulbState | None = None
        self._syncing = False  # True while updating widgets from the bulb's state
        self._ui_calls: queue.Queue[Callable[[], None]] = queue.Queue()
        self.worker = Worker(self._ui_calls.put)
        self.tray = None
        self.hotkeys = hotkey.HotkeyManager(lambda action: self._ui_calls.put(lambda: self.run_shortcut(action)))
        self.shortcut_problems: dict[str, str] = {}
        self._settings_open = False

        self._build()
        self._apply_config()
        self._poll_ui_calls()
        self._start_tray()
        self.apply_shortcuts()
        try:
            startup.repair()
        except OSError:
            pass
        if self.cfg.check_updates:
            run_in_thread(self._ui_calls.put, updates.check,
                          lambda r: self.show_update(r) if isinstance(r, updates.Update) else None)

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
        ttk.Button(header, text="⚙", width=3, command=self.open_settings).pack(side="right")
        ttk.Button(header, text="⟳", width=3, command=self.refresh).pack(side="right", padx=(0, 6))

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
        swatches = tk.Frame(colors, bg=PANEL)
        swatches.pack(fill="x", pady=(10, 0))
        for color in PRESET_COLORS:
            swatch = tk.Label(swatches, bg=color, width=3, height=1, cursor="hand2")
            swatch.pack(side="left", expand=True, padx=2)
            swatch.bind("<Button-1>", lambda _e, c=color: self._set_color(c))

        self.status_label = ttk.Label(root, text="", style="Muted.TLabel")
        self.status_label.pack(fill="x", pady=(12, 0))
        # Shown only when a newer release exists
        self.update_label = ttk.Label(root, text="", style="Muted.TLabel", foreground=ACCENT, cursor="hand2")

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
        self.title_label.configure(text=self.cfg.name)
        self.title(f"{self.cfg.name} – Mi Bulb")
        if self.cfg.is_complete:
            try:
                self.bulb = Bulb(self.cfg.ip, self.cfg.token, properties=self.cfg.properties)
            except MiIOError as exc:
                self.bulb = None
                self._set_status(str(exc), error=True)
                return
            self.refresh()
        else:
            self.bulb = None
            self._set_status("Not configured – open settings (⚙) to add your bulb.")

    def _run(self, key: str, func: Callable[[Bulb], Any], refresh: bool = False, retry: bool = True) -> None:
        bulb = self.bulb
        if bulb is None:
            self._set_status("Not configured – open settings (⚙) to add your bulb.", error=True)
            return

        def done(result: Any) -> None:
            if isinstance(result, DeviceUnreachable) and retry and self.cfg.did.isdigit():
                self._relocate(lambda: self._run(key, func, refresh, retry=False), str(result))
            elif isinstance(result, Exception):
                self._set_status(str(result), error=True)
            elif isinstance(result, BulbState):
                self._show_state(result)
            elif refresh:
                self.refresh()
            else:
                self._set_status(f"Connected to {self.cfg.ip}")

        self.worker.submit(key, lambda: func(bulb), done)

    def _relocate(self, then: Callable[[], None], error: str) -> None:
        """The bulb stopped answering: look for it on the network by device id, in case its IP changed."""
        self._set_status("Bulb not answering, searching the network…")

        def done(ip: Any) -> None:
            if isinstance(ip, str) and ip != self.cfg.ip:
                self.cfg.ip = ip
                config_mod.save(self.cfg)
                self.bulb = Bulb(self.cfg.ip, self.cfg.token, properties=self.cfg.properties)
                then()
            else:
                self._set_status(error, error=True)

        self.worker.submit("relocate", lambda: find_ip(int(self.cfg.did)), done)

    def refresh(self) -> None:
        self._run("status", lambda b: b.status())

    def toggle(self) -> None:
        self._run("power", lambda b: b.toggle(), refresh=True)

    def turn(self, on: bool) -> None:
        self._run("power", lambda b: b.turn_on() if on else b.turn_off(), refresh=True)

    def _on_brightness(self, value: int) -> None:
        self._run("brightness", lambda b: b.set_brightness(value))

    def _on_kelvin(self, value: int) -> None:
        self._run("colour", lambda b: b.set_color_temperature(value))

    def _set_kelvin(self, kelvin: int) -> None:
        self._sync_slider(self.kelvin_label, kelvin)
        self._run("colour", lambda b: b.set_color_temperature(kelvin), refresh=True)

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
        self.power_button.configure(
            text="On" if state.on else "Off", style="PowerOn.TButton" if state.on else "Power.TButton"
        )
        self._sync_slider(self.brightness_label, state.brightness)
        self._sync_slider(self.kelvin_label, state.color_temperature)
        self.color_swatch.configure(bg=state.color_hex if state.mode == MODE_COLOR else "#ffffff")
        mode = "colour" if state.mode == MODE_COLOR else "white"
        self._set_status(f"Connected to {self.cfg.ip} · {mode} mode")
        if self.tray is not None:
            self.tray.icon = make_icon_image(state.on)
            self.tray.title = f"{self.cfg.name}: {'on' if state.on else 'off'}"

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
        if dialog.result is not None:
            self.cfg = dialog.result
            path = config_mod.save(self.cfg)
            self._set_status(f"Saved settings to {path}")
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
        elif action == "window":
            self.show()

    def _step_brightness(self, delta: int) -> None:
        # The slider holds the latest value, so quick repeated presses add up.
        value = max(1, min(100, self.brightness.get() + delta))
        self._sync_slider(self.brightness_label, value)
        self._run("brightness", lambda b: b.set_brightness(value))

    def show_update(self, update: updates.Update) -> None:
        self.update_label.configure(text=f"Mi Bulb {update.version} is available. Click to download.")
        self.update_label.bind("<Button-1>", lambda _e: webbrowser.open(update.url))
        self.update_label.pack(fill="x", pady=(4, 0))

    def forget_bulb(self) -> None:
        self.cfg = config_mod.forget_bulb(self.cfg)
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

        menu = pystray.Menu(
            pystray.MenuItem("Toggle", lambda: post(self.toggle), default=True),
            pystray.MenuItem("Turn on", lambda: post(lambda: self.turn(True))),
            pystray.MenuItem("Turn off", lambda: post(lambda: self.turn(False))),
            pystray.MenuItem("Brightness", pystray.Menu(*[
                pystray.MenuItem(f"{level}%", action(self._tray_brightness, level))
                for level in (100, 75, 50, 25, 10)
            ])),
            pystray.MenuItem("White", pystray.Menu(*[
                pystray.MenuItem(name, action(self._set_kelvin, kelvin))
                for name, kelvin in PRESET_WHITES
            ])),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open window", lambda: post(self.show)),
            pystray.MenuItem("Settings…", lambda: post(lambda: self.open_settings("app"))),
            pystray.MenuItem("Quit", lambda: post(self.quit_app)),
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

    def _tray_brightness(self, percent: int) -> None:
        self._sync_slider(self.brightness_label, percent)
        self._run("brightness", lambda b: b.set_brightness(percent), refresh=True)

    def quit_app(self) -> None:
        self.after_cancel(self._poll_id)
        self.hotkeys.stop()
        if self.tray is not None:
            self.tray.stop()
        self.destroy()


def main(start_minimized: bool = False) -> None:
    from .single_instance import InstanceServer, notify_existing

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
