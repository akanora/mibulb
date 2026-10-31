"""Desktop window and system-tray icon for controlling the bulb."""

from __future__ import annotations

import io
import queue
import threading
import tkinter as tk
import webbrowser
from collections import OrderedDict
from tkinter import colorchooser, messagebox, ttk
from typing import Any, Callable

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
    def __init__(self, parent: tk.Tk, cfg: config_mod.Config, post: Post):
        super().__init__(parent)
        self.title("Bulb settings")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(parent)
        self.result: config_mod.Config | None = None
        self._cfg = cfg
        self._post = post
        self._did = cfg.did
        self._cloud_devices: list[CloudDevice] = []

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

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

        buttons = ttk.Frame(body)
        buttons.grid(row=10, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Save", style="Accent.TButton", command=self._save).pack(side="right")

        self.bind("<Return>", lambda _e: self._save())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()

    def _toggle_token(self) -> None:
        self.token_entry.configure(show="" if self.show_token.get() else "•")

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
        if not ip or len(token) != 32:
            messagebox.showerror("Bulb settings", "Enter the bulb's IP address and its 32-character token.", parent=self)
            return
        self.result = config_mod.Config(
            ip=ip,
            token=token,
            name=self.name_var.get().strip() or "Light",
            did=self._did,
            properties=self._cfg.properties,
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

        self._build()
        self._apply_config()
        self._poll_ui_calls()
        self._start_tray()

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
        style.configure("TButton", background=PANEL, foreground=TEXT, borderwidth=0, padding=(10, 6))
        style.map("TButton", background=[("active", "#3a3d46"), ("disabled", PANEL)], foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#1e1f24")
        style.map("Accent.TButton", background=[("active", "#ffd966")])
        style.configure("Power.TButton", font=("Segoe UI Semibold", 12), padding=(10, 12))
        style.configure("PowerOn.TButton", font=("Segoe UI Semibold", 12), padding=(10, 12), background=ACCENT, foreground="#1e1f24")
        style.map("PowerOn.TButton", background=[("active", "#ffd966")])
        style.configure("TCheckbutton", background=BG, foreground=TEXT)
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

    def open_settings(self) -> None:
        self.show()
        dialog = SettingsDialog(self, self.cfg, self._ui_calls.put)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.cfg = dialog.result
            path = config_mod.save(self.cfg)
            self._set_status(f"Saved settings to {path}")
            self._apply_config()

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
        menu = pystray.Menu(
            pystray.MenuItem("Toggle", lambda: post(self.toggle), default=True),
            pystray.MenuItem("Turn on", lambda: post(lambda: self.turn(True))),
            pystray.MenuItem("Turn off", lambda: post(lambda: self.turn(False))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open window", lambda: post(self.show)),
            pystray.MenuItem("Quit", lambda: post(self.quit_app)),
        )
        self.tray = pystray.Icon("mibulb", make_icon_image(True), "Mi Bulb", menu)
        self.tray.run_detached()

    def show(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def hide_or_quit(self) -> None:
        if self.tray is not None:
            self.withdraw()
        else:
            self.quit_app()

    def quit_app(self) -> None:
        self.after_cancel(self._poll_id)
        if self.tray is not None:
            self.tray.stop()
        self.destroy()


def main(start_minimized: bool = False) -> None:
    App(start_minimized=start_minimized).mainloop()
