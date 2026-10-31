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
import shutil
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import secret
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
    ("music_sync", "Music sync on/off", ""),
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

    def to_dict(self, plain_token: bool = False) -> dict:
        data = {"id": self.id, "name": self.name, "ip": self.ip}
        if secret.supported() and not plain_token and self.token:
            data["token_protected"] = secret.protect(self.token)
        else:
            data["token"] = self.token
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
            token=_read_token(data),
            did=str(data.get("did", "")),
            properties=dict(data.get("properties", {})),
        )


def _read_secret(data: dict, name: str) -> str:
    if data.get(name):
        return str(data[name])
    if data.get(f"{name}_protected"):
        try:
            return secret.unprotect(data[f"{name}_protected"])
        except secret.SecretError:
            pass
    return ""


def _read_token(data: dict) -> str:
    if data.get("token"):
        return str(data["token"])  # plain (older versions, exports, other systems)
    if data.get("token_protected"):
        try:
            return secret.unprotect(data["token_protected"])
        except secret.SecretError:
            # Encrypted by another Windows account or PC: sign in again to get the token.
            load_problems.append(f"Couldn't read the token for {data.get('name') or 'a bulb'}. "
                                 "Sign in with Xiaomi again to restore it.")
    return ""


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
    sync_monitor: int = 0  # which screen screen sync follows (0 = main screen)
    language: str = "auto"  # "auto" (Windows language), "en" or "tr"
    # Evening warmth: white light fades warmer from warmth_start ("sunset" or "HH:MM") to warmth_end
    warmth: bool = False
    warmth_start: str = "sunset"
    warmth_end: str = "22:30"
    warmth_kelvin: int = 2700
    location: str = ""  # "latitude, longitude", only used to work out sunset
    # Local web API (see api.py)
    api_enabled: bool = False
    api_lan: bool = False  # also allow other devices on the network
    api_port: int = 8765
    api_key: str = ""

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


# Problems found by the last load(), for the app to show (e.g. a damaged file was replaced).
load_problems: list[str] = []


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def _read(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not a settings file")
    return data


def load(path: Path | None = None) -> Config:
    path = path or find_config_path()
    load_problems.clear()
    if not path.exists():
        return Config()
    try:
        data = _read(path)
    except (ValueError, OSError) as exc:
        # Keep the damaged file for inspection and fall back to the last good copy.
        broken = path.with_name(f"config.broken-{int(time.time())}.json")
        try:
            path.replace(broken)
        except OSError:
            broken = path
        try:
            data = _read(_backup_path(path))
            load_problems.append(f"Your settings file was damaged ({exc}). The last good copy was restored; "
                                 f"the damaged one is kept as {broken.name}.")
        except (ValueError, OSError):
            data = {}
            load_problems.append(f"Your settings file was damaged ({exc}) and there was no backup, so "
                                 f"Mi Bulb started fresh. The damaged file is kept as {broken.name}.")
    try:
        return _from_data(data)
    except (TypeError, ValueError, AttributeError) as exc:
        load_problems.append(f"Some settings couldn't be read ({exc}), so defaults were used.")
        return Config()


def _from_data(data: dict) -> Config:
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
                                           if k in DEFAULT_SHORTCUTS or k.startswith(("scene:", "effect:"))}},
        scenes=[Scene.from_dict(d) for d in data["scenes"]] if "scenes" in data else default_scenes(),
        schedules=[Schedule.from_dict(d) for d in data.get("schedules", [])],
        lock_off=bool(data.get("lock_off", False)),
        unlock_on=bool(data.get("unlock_on", False)),
        tray_click="toggle" if data.get("tray_click") == "toggle" else "panel",
        sync_brightness=bool(data.get("sync_brightness", True)),
        sync_monitor=int(data.get("sync_monitor", 0)),
        language=str(data.get("language", "auto")),
        warmth=bool(data.get("warmth", False)),
        warmth_start=str(data.get("warmth_start", "sunset")),
        warmth_end=str(data.get("warmth_end", "22:30")),
        warmth_kelvin=int(data.get("warmth_kelvin", 2700)),
        location=str(data.get("location", "")),
        api_enabled=bool(data.get("api_enabled", False)),
        api_lan=bool(data.get("api_lan", False)),
        api_port=int(data.get("api_port", 8765)),
        api_key=_read_secret(data, "api_key"),
    )


def save(config: Config, path: Path | None = None) -> Path:
    path = path or find_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, _to_data(config))
    return path


def export(config: Config, path: Path) -> None:
    """Save settings to move to another PC. Tokens are written readable, since encryption is per account."""
    write_json(path, _to_data(config, plain=True))


def _to_data(config: Config, plain: bool = False) -> dict:
    data = {
        "bulbs": [bulb.to_dict(plain_token=plain) for bulb in config.bulbs],
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
        "sync_monitor": config.sync_monitor,
        "language": config.language,
        "warmth": config.warmth,
        "warmth_start": config.warmth_start,
        "warmth_end": config.warmth_end,
        "warmth_kelvin": config.warmth_kelvin,
        "location": config.location,
        "api_enabled": config.api_enabled,
        "api_lan": config.api_lan,
        "api_port": config.api_port,
    }
    if config.api_key:
        if secret.supported() and not plain:
            data["api_key_protected"] = secret.protect(config.api_key)
        else:
            data["api_key"] = config.api_key
    if config.skipped_update:
        data["skipped_update"] = config.skipped_update
    return data


def write_json(path: Path, data: dict) -> None:
    """Write without ever leaving a half-written file: write a temp file, then swap it in.

    The previous file is kept as config.json.bak, so a bad save can be undone.
    """
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8") as out:
        out.write(json.dumps(data, indent=2) + "\n")
        out.flush()
        os.fsync(out.fileno())
    if path.exists():
        try:
            _read(path)  # only back up a file that is itself good
            shutil.copyfile(path, _backup_path(path))
        except (ValueError, OSError):
            pass
    os.replace(temp, path)


def forget_bulbs(config: Config) -> Config:
    """Return a copy without any bulbs (names, IPs, tokens), keeping app preferences."""
    return replace(config, bulbs=[], selected="")
