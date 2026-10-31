"""The main window, tray icon and app startup."""

from __future__ import annotations

import math
import queue
import sys
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from tkinter import colorchooser, messagebox, simpledialog, ttk
from typing import Any, Callable

from .. import api, automation, effects, hotkey, i18n, musicsync, pcevents, screensync, startup, updates
from .. import config as config_mod
from ..bulb import MAX_KELVIN, MIN_KELVIN, MODE_COLOR, MODE_WHITE, Bulb, BulbGroup, BulbState
from ..i18n import t
from ..miio import MiIOError
from ..scenes import Scene
from .common import ACCENT, BG, ERROR, Image, ImageTk, make_icon_image, MUTED, PANEL, PRESET_COLORS, PRESET_WHITES, pystray, run_in_thread, TEXT, Worker
from .quickpanel import QuickPanel
from .settings import SettingsDialog


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
        self._effect: str | None = None  # id of the effect playing on the bulb
        self.music_sync: musicsync.MusicSync | None = None
        self.api_server: api.ApiServer | None = None
        self.api_problem: str | None = None
        self._warmth_paused = ""  # evening (date) on which you changed the white yourself
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
        self.apply_api()
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
        if config_mod.load_problems:
            problems = " ".join(config_mod.load_problems)
            self.after(300, lambda: self._set_status(problems, error=True))
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
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=TEXT, arrowcolor=TEXT,
                        selectbackground=PANEL, selectforeground=TEXT, bordercolor="#3a3d46",
                        lightcolor=PANEL, darkcolor=PANEL)
        # The clam theme switches read-only boxes to a light background, which hid the light text.
        style.map("TCombobox",
                  fieldbackground=[("readonly", PANEL), ("disabled", BG)],
                  foreground=[("disabled", MUTED), ("readonly", TEXT)],
                  background=[("active", "#3a3d46"), ("readonly", PANEL)],
                  selectbackground=[("readonly", PANEL)],
                  selectforeground=[("readonly", TEXT)],
                  arrowcolor=[("disabled", MUTED)])
        # The list that drops down is a plain Tk listbox with its own colours.
        self.option_add("*TCombobox*Listbox.background", PANEL)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

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
        self.effects_button = ttk.Button(top, text="Effects ▾", command=self._effects_menu)
        self.effects_button.pack(side="right", padx=(0, 8))
        ttk.Button(top, text="⌖", width=3, command=self.pick_from_screen).pack(side="right", padx=(0, 8))
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

    def _run(self, key: str, func: Callable[[Bulb], Any], refresh: bool = False, manual: bool = True,
             target: str = "") -> None:
        if manual and key != "status":
            # You took over, so stop a timer, sunrise or screen sync.
            if self._program is not None:
                self.cancel_program(quiet=True)
            if self.screen_sync is not None:
                self.stop_screen_sync(quiet=True)
            if self._effect is not None:
                self.stop_effect(quiet=True)
            if self.music_sync is not None:
                self.stop_music_sync(quiet=True)
            if key == "colour":
                # You picked a colour or white yourself: evening warmth leaves it alone until tomorrow.
                self._warmth_paused = self._warmth_day()
        bulb = self._group_for(target) if target else self.bulb
        if bulb is None:
            self._set_status("Not configured – open settings (⚙) to add your bulb.", error=True)
            return

        def done(result: Any) -> None:
            if isinstance(result, Exception):
                self._set_status(str(result), error=True)
            elif isinstance(result, BulbState):
                if not target:
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

    # ---- local API ----------------------------------------------------------------

    def apply_api(self) -> None:
        """Start, restart or stop the local API to match the settings."""
        if self.api_server is not None:
            self.api_server.stop()
            self.api_server = None
        self.api_problem = None
        if not self.cfg.api_enabled:
            return
        if not self.cfg.api_key:
            self.cfg.api_key = api.new_key()
            config_mod.save(self.cfg)
        server = api.ApiServer(self._api_command, self.cfg.api_key, self.cfg.api_port, self.cfg.api_lan)
        try:
            server.start()
        except OSError as exc:
            self.api_problem = f"The local API couldn't start on port {self.cfg.api_port}: {exc}"
            self._set_status(self.api_problem, error=True)
            return
        self.api_server = server

    def _api_command(self, command: str, params: dict[str, str]) -> dict | None:
        """Runs on the API's thread: check the request, then hand the work to the window's thread."""
        post = self._ui_calls.put

        def number(name: str, lo: int, hi: int) -> int:
            try:
                value = int(params.get(name, ""))
            except ValueError:
                raise api.ApiError(400, f"{name} must be a number") from None
            if not lo <= value <= hi:
                raise api.ApiError(400, f"{name} must be between {lo} and {hi}")
            return value

        def find(items, name, label):
            wanted = params.get(name, "").strip().lower()
            for item in items:
                if wanted in (item.id.lower(), item.name.lower(), t(item.name).lower()):
                    return item
            raise api.ApiError(404, f"No {label} called {params.get(name, '')!r}")

        if command == "status":
            state = self.bulb_state
            return {
                "light": self.cfg.display_name,
                "on": state.on if state else None,
                "brightness": state.brightness if state else None,
                "mode": ("colour" if state.mode == MODE_COLOR else "white") if state else None,
                "kelvin": state.color_temperature if state else None,
                "color": state.color_hex if state else None,
                "screen_sync": self.screen_sync is not None,
                "music_sync": self.music_sync is not None,
                "effect": self._effect,
                "scenes": [scene.name for scene in self.cfg.scenes],
                "effects": [effect.id for effect in effects.EFFECTS],
                "lights": ["all"] + [bulb.name for bulb in self.cfg.usable_bulbs],
            }
        if command in ("on", "off"):
            post(lambda: self.turn(command == "on"))
        elif command == "toggle":
            post(self.toggle)
        elif command == "brightness":
            value = params.get("value", "")
            if value in ("up", "down"):
                post(lambda: self._step_brightness(10 if value == "up" else -10))
            else:
                level = number("value", 1, 100)
                post(lambda: self._quick_brightness(level))
        elif command == "white":
            kelvin = number("kelvin", MIN_KELVIN, MAX_KELVIN)
            post(lambda: self._set_kelvin(kelvin))
        elif command == "color":
            hex_text = params.get("hex", "").strip().lstrip("#")
            if len(hex_text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in hex_text):
                raise api.ApiError(400, "hex must look like ff8800")
            post(lambda: self._set_color(f"#{hex_text}"))
        elif command == "scene":
            scene = find(self.cfg.scenes, "name", "scene")
            post(lambda: self.apply_scene(scene))
        elif command == "effect":
            if params.get("name", "").lower() == "stop":
                post(self.stop_effect)
            else:
                effect = find(effects.EFFECTS, "name", "effect")
                post(lambda: self.start_effect(effect.id))
        elif command == "sleep":
            minutes = number("minutes", 0, 600)
            post(self.cancel_program if minutes == 0 else lambda: self.start_sleep_timer(minutes))
        elif command == "screen-sync":
            post(self.toggle_screen_sync)
        elif command == "music-sync":
            post(self.toggle_music_sync)
        elif command == "light":
            if params.get("name", "").lower() in ("all", t("All lights").lower()):
                post(lambda: self.select_bulb(config_mod.ALL))
            else:
                bulb = find(self.cfg.usable_bulbs, "name", "light")
                post(lambda: self.select_bulb(bulb.id))
        else:
            raise api.ApiError(404, f"Unknown command {command!r}; see /api/status")
        return None

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
        elif action == "music_sync":
            self.toggle_music_sync()
        elif action.startswith("effect:"):
            effect_id = action.split(":", 1)[1]
            if self._effect == effect_id:
                self.stop_effect()
            else:
                self.start_effect(effect_id)
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

    def import_settings(self, imported: config_mod.Config) -> None:
        self.cfg = imported
        config_mod.save(self.cfg)
        self.apply_shortcuts()
        self.apply_api()
        self._apply_config()
        self._render_scenes()
        self._set_status("Settings imported.")

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

        def effect_action(effect_id: str) -> Callable[[], None]:
            return lambda: post(lambda: self.start_effect(effect_id))

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
            pystray.MenuItem(t("Effects"), pystray.Menu(
                *[pystray.MenuItem(t(effect.name), effect_action(effect.id),
                                   checked=lambda _item, e=effect.id: self._effect == e)
                  for effect in effects.EFFECTS],
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(t("Stop effect"), lambda: post(self.stop_effect)),
            )),
            pystray.MenuItem(t("Music sync"), lambda: post(self.toggle_music_sync),
                             checked=lambda _item: self.music_sync is not None),
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
        self._start_program("sleep", "Sleep timer: off at {end}", steps, finish=lambda: self.turn(False, manual=False))
        # The bulb also gets its own off-timer, so it still turns off if the PC sleeps or shuts down.
        self._run("off-timer", self._quietly(lambda b: b.set_off_timer(math.ceil(minutes))), manual=False)

    def start_sunrise(self, minutes: float, target: str = "") -> None:
        steps = automation.plan_sunrise(minutes)
        self._start_program("sunrise", "Sunrise: full brightness at {end}", steps, finish=self.refresh,
                            target=target)

    def _start_program(self, name: str, label: str, steps: list, finish: Callable[[], None],
                       target: str = "") -> None:
        self.cancel_program(quiet=True)
        started = datetime.now()
        end = datetime.fromtimestamp(started.timestamp() + steps[-1].at)
        self._program = {"name": name, "steps": steps, "index": 0, "start": started.timestamp(),
                         "finish": finish, "after": None, "label": label.format(end=end.strftime("%H:%M")),
                         "target": target}
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
            self._run("program", lambda b: b.apply_scene(step.brightness, kelvin=step.kelvin), manual=False,
                      target=program["target"])
        elif first:
            pass  # a sleep timer starts from the current brightness
        else:
            self._run("program", lambda b: b.set_brightness(step.brightness), manual=False,
                      target=program["target"])
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
        if program["name"] == "sleep":
            self._run("off-timer", self._quietly(lambda b: b.cancel_off_timer()), manual=False)
        if not quiet:
            self._set_status("Timer cancelled.")

    def _quietly(self, func: Callable[[Bulb], Any]) -> Callable[[Bulb], Any]:
        """For extras that not every bulb has: skip them instead of showing an error."""
        def run(bulb: Bulb) -> Any:
            try:
                return func(bulb)
            except MiIOError as exc:
                if "doesn't support" not in str(exc):
                    raise
                return None

        return run

    # ---- music sync -----------------------------------------------------------

    def toggle_music_sync(self) -> None:
        if self.music_sync is not None:
            self.stop_music_sync()
        else:
            self.start_music_sync()

    def start_music_sync(self) -> None:
        if self.bulb is None:
            self._set_status("Add your bulb first (⚙).", error=True)
            return
        if not musicsync.available():
            self._set_status("Music sync needs the PyAudioWPatch package", error=True)
            return
        self.cancel_program(quiet=True)
        self.stop_screen_sync(quiet=True)
        self.stop_effect(quiet=True)
        self._run("power", lambda b: b.turn_on(), manual=False)

        def send(rgb: int, brightness: int | None) -> None:
            self._ui_calls.put(lambda: self._run(
                "sync", lambda b: b.sync_color(rgb, brightness, musicsync.FADE_MS), manual=False))

        self.music_sync = musicsync.MusicSync(send)
        self.music_sync.start()
        self.program_label.configure(text="Music sync is on  ·  click to stop")
        self.program_label.pack(fill="x", pady=(4, 0))
        self.after(2500, self._check_music_sync)
        if self.tray is not None:
            self.tray.update_menu()

    def _check_music_sync(self) -> None:
        sync = self.music_sync
        if sync is not None and not sync.running and sync.error:
            self.stop_music_sync(quiet=True)
            self._set_status(sync.error, error=True)

    def stop_music_sync(self, quiet: bool = False) -> None:
        if self.music_sync is None:
            return
        self.music_sync.stop()
        self.music_sync = None
        if self._program is None and self.screen_sync is None and self._effect is None:
            self.program_label.pack_forget()
        if self.tray is not None:
            self.tray.update_menu()
        if not quiet:
            self._set_status("Music sync stopped.")
            self.refresh()

    # ---- colour from the screen ------------------------------------------------

    def pick_from_screen(self) -> None:
        """Hide this window, take a screenshot and let you click the colour you want."""
        from .picker import ScreenColorPicker

        was_visible = self.state() != "withdrawn"
        self.withdraw()

        def come_back() -> None:
            if was_visible:
                self.show()

        def picked(color: str) -> None:
            self._set_color(color)
            come_back()

        # Give Windows a moment to hide this window, so it isn't in the screenshot.
        self.after(250, lambda: ScreenColorPicker(self, picked, come_back))

    # ---- effects --------------------------------------------------------------

    def _effects_menu(self) -> None:
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT, activebackground=ACCENT, activeforeground=BG)
        menu.add_command(label="Stop music sync" if self.music_sync else "Music sync", command=self.toggle_music_sync)
        menu.add_separator()
        for effect in effects.EFFECTS:
            menu.add_command(label=effect.name, command=lambda e=effect.id: self.start_effect(e))
        if self._effect is not None:
            menu.add_separator()
            menu.add_command(label="Stop effect", command=self.stop_effect)
        x = self.effects_button.winfo_rootx()
        menu.tk_popup(x, self.effects_button.winfo_rooty() + self.effects_button.winfo_height())

    def start_effect(self, effect_id: str) -> None:
        effect = effects.BY_ID.get(effect_id)
        if effect is None or self.bulb is None:
            return
        self.cancel_program(quiet=True)
        self.stop_screen_sync(quiet=True)
        self._effect = effect_id
        self._run("effect", lambda b: b.start_effect(effect.expression()), manual=False)
        self.program_label.configure(text=f"Effect: {effect.name}  ·  click to stop")
        self.program_label.pack(fill="x", pady=(4, 0))
        if self.tray is not None:
            self.tray.update_menu()

    def stop_effect(self, quiet: bool = False) -> None:
        if self._effect is None:
            return
        self._effect = None
        self._run("effect", lambda b: b.stop_effect(), manual=False, refresh=not quiet)
        if self._program is None and self.screen_sync is None:
            self.program_label.pack_forget()
        if self.tray is not None:
            self.tray.update_menu()

    def _stop_running(self) -> None:
        if self.music_sync is not None:
            self.stop_music_sync()
        elif self._effect is not None:
            self.stop_effect()
        elif self.screen_sync is not None:
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

        screens = screensync.monitors()
        bbox = screens[self.cfg.sync_monitor]["bbox"] if 0 <= self.cfg.sync_monitor < len(screens) else None
        self.stop_music_sync(quiet=True)
        self.screen_sync = screensync.ScreenSync(send, match_brightness=self.cfg.sync_brightness,
                                                 grab=lambda: screensync.grab_screen(bbox))
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
                self.run_schedule_action(schedule.action, schedule.target)
        if now.second < 15:  # about once a minute
            self._warmth_tick()
        # Forget old entries so the set stays small.
        self._schedules_fired = {k for k in self._schedules_fired if k[1] == minute}
        self._tick_id = self.after(15000, self._schedule_tick)

    def run_schedule_action(self, action: str, target: str = "") -> None:
        minutes = automation.sunrise_minutes(action)
        if minutes is not None:
            self.start_sunrise(minutes, target)
        elif action in ("on", "off"):
            on = action == "on"
            self._run("power", lambda b: b.turn_on() if on else b.turn_off(), refresh=True, manual=False,
                      target=target)
        elif action.startswith("scene:"):
            scene = next((sc for sc in self.cfg.scenes if sc.id == action[6:]), None)
            if scene is not None:
                rgb = scene.color if scene.is_color else None
                kelvin = None if scene.is_color else scene.kelvin
                self._run("colour", lambda b: b.apply_scene(scene.brightness, kelvin=kelvin, rgb=rgb),
                          refresh=True, manual=False, target=target)

    def _group_for(self, target: str) -> BulbGroup | None:
        """The bulbs a schedule aims at: "all", one bulb's id, or "" for the ones picked in the window."""
        if not target:
            return self.bulb
        infos = self.cfg.usable_bulbs if target == config_mod.ALL else \
            [b for b in self.cfg.usable_bulbs if b.id == target]
        return BulbGroup(infos, on_moved=self._bulb_moved) if infos else None

    def describe_target(self, target: str) -> str:
        if not target:
            return ""
        if target == config_mod.ALL:
            return "All lights"
        info = self.cfg.bulb(target)
        return info.name if info else "Removed bulb"

    # ---- evening warmth -------------------------------------------------------

    def _warmth_day(self) -> str:
        now = datetime.now()
        return (now if now.hour >= 5 else now - timedelta(days=1)).strftime("%Y-%m-%d")

    def _warmth_tick(self) -> None:
        cfg, state = self.cfg, self.bulb_state
        if not cfg.warmth or self.bulb is None or state is None or not state.on or state.mode != MODE_WHITE:
            return
        if self._program is not None or self.screen_sync is not None or self._effect is not None:
            return
        if self._warmth_paused == self._warmth_day():
            return
        try:
            kelvin = automation.warmth_kelvin(datetime.now(), cfg.warmth_start, cfg.warmth_end, cfg.warmth_kelvin,
                                              automation.parse_location(cfg.location))
        except ValueError:
            return
        if kelvin is None or abs(state.color_temperature - kelvin) < 100:
            return
        self._sync_slider(self.kelvin_label, kelvin)
        self._run("warmth", lambda b: b.set_color_temperature(kelvin), refresh=True, manual=False)

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
            self.stop_music_sync(quiet=True)
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
        self.stop_music_sync(quiet=True)
        self.hotkeys.stop()
        self.pc_watcher.stop()
        if self.api_server is not None:
            self.api_server.stop()
        if self.tray is not None:
            self.tray.stop()
        self.destroy()


def main(start_minimized: bool = False, restarted: bool = False) -> None:
    import time

    from ..single_instance import InstanceServer, notify_existing

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
