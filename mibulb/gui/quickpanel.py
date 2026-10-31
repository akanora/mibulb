"""The quick panel that opens from the tray icon."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Callable

from ..bulb import MAX_KELVIN, MIN_KELVIN, BulbState
from .common import BG, MUTED, PANEL, PRESET_COLORS, TEXT, work_area

if TYPE_CHECKING:
    from .app import App


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
