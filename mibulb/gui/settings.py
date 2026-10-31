"""The settings window: bulbs, app options, shortcuts and automation."""

from __future__ import annotations

import os
import socket
import tkinter as tk
from datetime import datetime
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Any, Callable

from .. import __version__, api, automation, effects, hotkey, i18n, pcevents, screensync, startup, updates
from .. import config as config_mod
from ..cloud import CloudDevice
from ..i18n import t
from ..miio import discover, find_ip
from .common import ACCENT, BG, ERROR, MUTED, PANEL, Post, ScrollFrame, TEXT, fit_to_screen, run_in_thread
from .dialogs import QrLoginDialog, ScheduleDialog

if TYPE_CHECKING:
    from .app import App


def _local_ip() -> str | None:
    """This PC's address on the local network (no traffic is sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.168.1.1", 9))  # picks the network interface; nothing is sent over UDP connect
            return probe.getsockname()[0]
    except OSError:
        return None


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: "App", cfg: config_mod.Config, post: Post, tab: str = "bulb"):
        super().__init__(parent)
        self.title("Mi Bulb settings")
        self.configure(bg=BG)
        self.transient(parent)
        self.changed = False
        self._post = post
        self._did = ""
        self._editing: str | None = None  # id of the bulb shown in the detail fields
        self._cloud_devices: list[CloudDevice] = []
        self._app = parent

        # Buttons first, at the bottom, so they stay visible however small the window gets.
        buttons = ttk.Frame(self, padding=(16, 12, 16, 16))
        buttons.pack(side="bottom", fill="x")
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Save bulb", style="Accent.TButton", command=self._save).pack(side="right")
        ttk.Label(buttons, text="App options are saved as you change them.", style="Muted.TLabel").pack(side="left")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        # Each tab scrolls when it doesn't fit (the Shortcuts tab grows with every scene and effect).
        pages = {name: ScrollFrame(notebook, padding=16) for name in ("bulb", "app", "shortcuts", "automation")}
        for name, label in (("bulb", "Bulbs"), ("app", "App"), ("shortcuts", "Shortcuts"),
                            ("automation", "Automation")):
            notebook.add(pages[name], text=t(label))
        self.pages = pages
        body, app_tab = pages["bulb"].inner, pages["app"].inner
        keys_tab, auto_tab = pages["shortcuts"].inner, pages["automation"].inner
        self._capturing: str | None = None
        self._build_app_tab(app_tab)
        self._build_shortcuts_tab(keys_tab)
        self._build_automation_tab(auto_tab)
        notebook.select(pages.get(tab, pages["bulb"]))

        self._build_bulbs_tab(body)
        fit_to_screen(self, min_size=(480, 360))

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
        screens = screensync.monitors()
        if len(screens) > 1:
            row = ttk.Frame(tab)
            row.pack(anchor="w", pady=(4, 0))
            ttk.Label(row, text="Screen to follow").pack(side="left")
            self.monitor_pick = ttk.Combobox(row, state="readonly", width=26, values=[m["name"] for m in screens])
            self.monitor_pick.current(min(self._app.cfg.sync_monitor, len(screens) - 1))
            self.monitor_pick.pack(side="left", padx=(8, 0))
            self.monitor_pick.bind("<<ComboboxSelected>>", self._set_monitor)
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
        row = ttk.Frame(tab)
        row.pack(fill="x", pady=(6, 0))
        ttk.Button(row, text="Export settings…", command=self._export).pack(side="left")
        ttk.Button(row, text="Import settings…", command=self._import).pack(side="left", padx=(8, 0))

        self._build_api(tab, section)

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

        self._build_warmth(tab)

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

    def _build_warmth(self, tab: ttk.Frame) -> None:
        cfg = self._app.cfg
        ttk.Label(tab, text="Evening warmth", style="Section.TLabel").pack(anchor="w", pady=(16, 4))
        self.warmth_var = tk.BooleanVar(value=cfg.warmth)
        ttk.Checkbutton(tab, text="Make white light warmer in the evening", variable=self.warmth_var,
                        command=self._save_warmth).pack(anchor="w")
        row = ttk.Frame(tab)
        row.pack(anchor="w", pady=(4, 0))
        starts = ["Sunset"] + [f"{h}:00" for h in range(17, 23)]
        ends = ["21:00", "22:00", "22:30", "23:00", "23:30", "00:00", "01:00"]
        ttk.Label(row, text="From").pack(side="left")
        self.warmth_start = ttk.Combobox(row, state="readonly", width=8, values=starts)
        self.warmth_start.set(t("Sunset") if cfg.warmth_start == "sunset" else cfg.warmth_start)
        self.warmth_start.pack(side="left", padx=4)
        ttk.Label(row, text="to").pack(side="left")
        self.warmth_end = ttk.Combobox(row, state="readonly", width=6, values=ends)
        self.warmth_end.set(cfg.warmth_end)
        self.warmth_end.pack(side="left", padx=4)
        ttk.Label(row, text="ending at").pack(side="left")
        self.warmth_kelvin = ttk.Combobox(row, state="readonly", width=7,
                                          values=[f"{k} K" for k in automation.WARMTH_KELVIN_CHOICES])
        self.warmth_kelvin.set(f"{cfg.warmth_kelvin} K")
        self.warmth_kelvin.pack(side="left", padx=4)
        for box in (self.warmth_start, self.warmth_end, self.warmth_kelvin):
            box.bind("<<ComboboxSelected>>", lambda _e: self._save_warmth())

        row = ttk.Frame(tab)
        row.pack(anchor="w", pady=(4, 0))
        ttk.Label(row, text="Your location (for sunset)").pack(side="left")
        self.location_var = tk.StringVar(value=cfg.location)
        entry = ttk.Entry(row, textvariable=self.location_var, width=18)
        entry.pack(side="left", padx=4)
        entry.bind("<FocusOut>", lambda _e: self._save_warmth())
        entry.bind("<Return>", lambda _e: self._save_warmth())
        self.sunset_label = ttk.Label(tab, text="", style="Muted.TLabel", wraplength=420)
        self.sunset_label.pack(anchor="w")
        self._show_sunset()

    def _save_warmth(self) -> None:
        cfg = self._app.cfg
        cfg.warmth = self.warmth_var.get()
        start = self.warmth_start.get()
        cfg.warmth_start = "sunset" if start in ("Sunset", t("Sunset")) else start
        cfg.warmth_end = self.warmth_end.get()
        cfg.warmth_kelvin = int(self.warmth_kelvin.get().split()[0])
        cfg.location = self.location_var.get().strip()
        config_mod.save(cfg)
        self._show_sunset()

    def _show_sunset(self) -> None:
        location = automation.parse_location(self._app.cfg.location)
        if location is None:
            text = ("Latitude and longitude, e.g. 41.01, 28.98 for Istanbul. Only used to work out sunset, "
                    "on this PC. Without it, Sunset means 20:00.")
        else:
            today = automation.sunset(location[0], location[1], datetime.now().date())
            text = f"Sunset today: {today.strftime('%H:%M')}" if today else "No sunset today at this location."
        self.sunset_label.configure(text=text)

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
            if schedule.target:
                text = f"{text}   ({self._app.describe_target(schedule.target)})"
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
        self._shortcut_rows += [(f"effect:{effect.id}", f"Effect: {effect.name}") for effect in effects.EFFECTS]
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
            if problem:
                self._key_status[action].configure(text=problem, foreground=ERROR)
                continue
            typed = None
            if text:
                try:
                    typed = hotkey.typed_character(*hotkey.parse(text))
                except hotkey.ShortcutError:
                    pass
            self._key_status[action].configure(
                text=f"On your keyboard this also types {typed}" if typed else "", foreground=ACCENT)
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

    def _set_monitor(self, _event: object = None) -> None:
        self._app.cfg.sync_monitor = max(0, self.monitor_pick.current())
        config_mod.save(self._app.cfg)

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

    # ---- local API ------------------------------------------------------------

    def _build_api(self, tab: ttk.Frame, section: Callable[[str], None]) -> None:
        cfg = self._app.cfg
        section("Local API (Stream Deck, scripts, Home Assistant)")
        self.api_var = tk.BooleanVar(value=cfg.api_enabled)
        self.api_lan_var = tk.BooleanVar(value=cfg.api_lan)
        ttk.Checkbutton(tab, text="Let other apps control Mi Bulb through a web address with a key",
                        variable=self.api_var, command=self._save_api).pack(anchor="w")
        ttk.Checkbutton(tab, text="Also from other devices on my network (Windows may ask about the firewall)",
                        variable=self.api_lan_var, command=self._save_api).pack(anchor="w")
        self.api_details = ttk.Frame(tab)
        self.api_url = ttk.Entry(self.api_details, width=52)
        self.api_url.pack(side="left")
        ttk.Button(self.api_details, text="Copy", command=self._copy_api_url).pack(side="left", padx=(6, 0))
        ttk.Button(self.api_details, text="New key", command=self._new_api_key).pack(side="left", padx=(6, 0))
        self.api_note = ttk.Label(tab, text="", style="Muted.TLabel", wraplength=420)
        self._show_api()

    def _save_api(self) -> None:
        cfg = self._app.cfg
        cfg.api_enabled = self.api_var.get()
        cfg.api_lan = self.api_lan_var.get()
        config_mod.save(cfg)
        self._app.apply_api()
        self._show_api()

    def _new_api_key(self) -> None:
        self._app.cfg.api_key = api.new_key()
        config_mod.save(self._app.cfg)
        self._app.apply_api()
        self._show_api()

    def _api_example(self) -> str:
        cfg = self._app.cfg
        host = "127.0.0.1" if not cfg.api_lan else (_local_ip() or "THIS-PC")
        return f"http://{host}:{cfg.api_port}/api/toggle?key={cfg.api_key}"

    def _show_api(self) -> None:
        cfg = self._app.cfg
        if cfg.api_enabled and cfg.api_key:
            self.api_url.configure(state="normal")
            self.api_url.delete(0, "end")
            self.api_url.insert(0, self._api_example())
            self.api_url.configure(state="readonly")
            self.api_details.pack(anchor="w", pady=(4, 0))
            note = self._app.api_problem or ("Replace toggle with on, off, status, brightness?value=40, "
                                             "scene?name=Relax and more (see the README). Keep the key private.")
            self.api_note.configure(text=note, foreground=ERROR if self._app.api_problem else MUTED)
            self.api_note.pack(anchor="w")
        else:
            self.api_details.pack_forget()
            self.api_note.pack_forget()

    def _copy_api_url(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._api_example())

    # ---- export / import -------------------------------------------------------

    def _export(self) -> None:
        if not messagebox.askokcancel(
            "Export settings",
            "The exported file includes your bulbs' tokens in readable form, so it works on another PC. "
            "Keep it somewhere private.",
            parent=self,
        ):
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export settings", defaultextension=".json",
                                            initialfile="mibulb-settings.json",
                                            filetypes=[("Mi Bulb settings", "*.json")])
        if path:
            config_mod.export(self._app.cfg, Path(path))
            messagebox.showinfo("Export settings", f"Saved to {path}", parent=self)

    def _import(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Import settings",
                                          filetypes=[("Mi Bulb settings", "*.json"), ("All files", "*.*")])
        if not path:
            return
        imported = config_mod.load(Path(path))
        problems = list(config_mod.load_problems)
        if not messagebox.askyesno(
            "Import settings",
            f"Replace your current settings with the ones in {Path(path).name}? "
            f"It has {len(imported.bulbs)} bulb(s) and {len(imported.scenes)} scene(s)."
            + ("\n\n" + " ".join(problems) if problems else ""),
            parent=self,
        ):
            return
        self._app.import_settings(imported)
        self.changed = True
        self.destroy()

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
