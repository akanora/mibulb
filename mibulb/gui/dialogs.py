"""The Xiaomi sign-in window and the schedule editor."""

from __future__ import annotations

import io
import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from .. import automation
from ..cloud import Cancelled, CloudDevice, QrLogin, XiaomiCloud
from .common import BG, ERROR, Image, ImageTk, MUTED, PANEL, Post, run_in_thread, TEXT

if TYPE_CHECKING:
    from .app import App


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

        self._targets = [("", "The lights picked in the window"), ("all", "All lights")]
        self._targets += [(b.id, b.name) for b in app.cfg.usable_bulbs]
        self.target = ttk.Combobox(body, state="readonly", width=34, values=[label for _v, label in self._targets])
        current_target = schedule.target if schedule else ""
        self.target.current(next((i for i, (v, _l) in enumerate(self._targets) if v == current_target), 0))
        if len(app.cfg.usable_bulbs) > 1:
            ttk.Label(body, text="Which light", style="Section.TLabel").pack(anchor="w", pady=(12, 0))
            self.target.pack(anchor="w", pady=(4, 0))

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
        target = self._targets[max(0, self.target.current())][0]
        self.result = automation.Schedule(self._id, time, days, action, self._enabled, target)
        self.destroy()
