"""Loading and saving the bulb's connection settings.

The config file is looked up in this order:
1. the path in the MIBULB_CONFIG environment variable
2. config.json in the current directory
3. %APPDATA%\\mibulb\\config.json (or ~/.config/mibulb/config.json)

The GUI saves new settings to the last location.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from .automation import Schedule
from .scenes import Scene, default_scenes

# Keyboard shortcut actions: (id, label, default shortcut). "" means not set.
# Only combinations unlikely to clash with typing are set by default: on many
# layouts Ctrl+Alt+<letter or digit> types a character (AltGr), so most are
# left for you to choose.
SHORTCUT_ACTIONS = [
    ("toggle", "Toggle light", "Ctrl+Alt+L"),
    ("on", "Turn on", ""),
    ("off", "Turn off", ""),
    ("brighter", "Brighter (+10%)", "Ctrl+Alt+PageUp"),
    ("dimmer", "Dimmer (-10%)", "Ctrl+Alt+PageDown"),
    ("warm", "Warm white", ""),
    ("neutral", "Neutral white", ""),
    ("daylight", "Daylight", ""),
    ("window", "Show Mi Bulb window", ""),
    ("sleep", "Sleep timer (30 min)", ""),
    ("screen_sync", "Screen sync on/off", ""),
]
DEFAULT_SHORTCUTS = {action: default for action, _label, default in SHORTCUT_ACTIONS}


def user_config_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / "mibulb" / "config.json"


def find_config_path() -> Path:
    env = os.environ.get("MIBULB_CONFIG")
    if env:
        return Path(env)
    local = Path.cwd() / "config.json"
    if local.exists():
        return local
    return user_config_path()


ALL = "all"  # "selected" value meaning every bulb at once


@dataclass
class BulbInfo:
    id: str
    name: str = "Light"
    ip: str = ""
    token: str = ""
    did: str = ""  # device id, used to find the bulb again if its IP changes
    properties: dict[str, int] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return bool(self.ip and self.token)

    def to_dict(self) -> dict:
        data = {"id": self.id, "name": self.name, "ip": self.ip, "token": self.token}
        if self.did:
            data["did"] = self.did
        if self.properties:
            data["properties"] = self.properties
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "BulbInfo":
        return cls(
            id=str(data.get("id") or new_bulb_id()),
            name=str(data.get("name") or "Light"),
            ip=str(data.get("ip", "")),
            token=str(data.get("token", "")),
            did=str(data.get("did", "")),
            properties=dict(data.get("properties", {})),
        )


def new_bulb_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Config:
    bulbs: list[BulbInfo] = field(default_factory=list)
    selected: str = ""  # a bulb id, ALL, or "" for the first bulb
    # App preferences (start with Windows lives in the registry, see startup.py)
    hotkey: bool = True  # keyboard shortcuts on/off
    check_updates: bool = True  # check, download and install updates automatically
    skipped_update: str = ""  # a version whose automatic install was cancelled
    shortcuts: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SHORTCUTS))
    scenes: list[Scene] = field(default_factory=default_scenes)
    schedules: list[Schedule] = field(default_factory=list)
    lock_off: bool = False  # turn off when the PC locks or sleeps
    unlock_on: bool = False  # turn back on when you return (if Mi Bulb turned it off)
    tray_click: str = "panel"  # left-click on the tray icon: "panel" or "toggle"
    sync_brightness: bool = True  # screen sync also follows how bright the screen is

    @property
    def usable_bulbs(self) -> list[BulbInfo]:
        return [bulb for bulb in self.bulbs if bulb.is_complete]

    @property
    def is_complete(self) -> bool:
        return bool(self.usable_bulbs)

    @property
    def current_bulbs(self) -> list[BulbInfo]:
        """The bulbs the window, shortcuts and scenes control right now."""
        usable = self.usable_bulbs
        if self.selected == ALL:
            return usable
        chosen = [bulb for bulb in usable if bulb.id == self.selected]
        return chosen or usable[:1]

    @property
    def display_name(self) -> str:
        if self.selected == ALL and len(self.usable_bulbs) > 1:
            return "All lights"
        current = self.current_bulbs
        return current[0].name if current else "Mi Bulb"

    def bulb(self, bulb_id: str) -> BulbInfo | None:
        return next((bulb for bulb in self.bulbs if bulb.id == bulb_id), None)


def load(path: Path | None = None) -> Config:
    path = path or find_config_path()
    if not path.exists():
        return Config()
    data = json.loads(path.read_text(encoding="utf-8"))
    if "bulbs" in data:
        bulbs = [BulbInfo.from_dict(d) for d in data["bulbs"]]
    elif data.get("ip") or data.get("token"):
        # Before 0.7.0 there was one bulb, stored at the top level.
        bulbs = [BulbInfo.from_dict({**data, "id": "main"})]
    else:
        bulbs = []
    return Config(
        bulbs=bulbs,
        selected=str(data.get("selected", "")),
        hotkey=bool(data.get("hotkey", True)),
        check_updates=bool(data.get("check_updates", True)),
        skipped_update=str(data.get("skipped_update", "")),
        # Defaults first, so actions added in a later version get theirs.
        shortcuts={**DEFAULT_SHORTCUTS, **{k: str(v) for k, v in data.get("shortcuts", {}).items()
                                           if k in DEFAULT_SHORTCUTS or k.startswith("scene:")}},
        scenes=[Scene.from_dict(d) for d in data["scenes"]] if "scenes" in data else default_scenes(),
        schedules=[Schedule.from_dict(d) for d in data.get("schedules", [])],
        lock_off=bool(data.get("lock_off", False)),
        unlock_on=bool(data.get("unlock_on", False)),
        tray_click="toggle" if data.get("tray_click") == "toggle" else "panel",
        sync_brightness=bool(data.get("sync_brightness", True)),
    )


def save(config: Config, path: Path | None = None) -> Path:
    path = path or find_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "bulbs": [bulb.to_dict() for bulb in config.bulbs],
        "selected": config.selected,
        "hotkey": config.hotkey,
        "check_updates": config.check_updates,
        "shortcuts": config.shortcuts,
        "scenes": [scene.to_dict() for scene in config.scenes],
        "schedules": [schedule.to_dict() for schedule in config.schedules],
        "lock_off": config.lock_off,
        "unlock_on": config.unlock_on,
        "tray_click": config.tray_click,
        "sync_brightness": config.sync_brightness,
    }
    if config.skipped_update:
        data["skipped_update"] = config.skipped_update
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def forget_bulbs(config: Config) -> Config:
    """Return a copy without any bulbs (names, IPs, tokens), keeping app preferences."""
    return replace(config, bulbs=[], selected="")
