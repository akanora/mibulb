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
from dataclasses import dataclass, field
from pathlib import Path

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


@dataclass
class Config:
    ip: str = ""
    token: str = ""
    name: str = "Light"
    did: str = ""  # device id, used to find the bulb again if its IP changes
    properties: dict[str, int] = field(default_factory=dict)
    # App preferences (start with Windows lives in the registry, see startup.py)
    hotkey: bool = True  # keyboard shortcuts on/off
    check_updates: bool = True
    shortcuts: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SHORTCUTS))

    @property
    def is_complete(self) -> bool:
        return bool(self.ip and self.token)


def load(path: Path | None = None) -> Config:
    path = path or find_config_path()
    if not path.exists():
        return Config()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Config(
        ip=data.get("ip", ""),
        token=data.get("token", ""),
        name=data.get("name", "Light"),
        did=str(data.get("did", "")),
        properties=data.get("properties", {}),
        hotkey=bool(data.get("hotkey", True)),
        check_updates=bool(data.get("check_updates", True)),
        # Defaults first, so actions added in a later version get theirs.
        shortcuts={**DEFAULT_SHORTCUTS, **{k: str(v) for k, v in data.get("shortcuts", {}).items()
                                           if k in DEFAULT_SHORTCUTS}},
    )


def save(config: Config, path: Path | None = None) -> Path:
    path = path or find_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"ip": config.ip, "token": config.token, "name": config.name}
    if config.did:
        data["did"] = config.did
    if config.properties:
        data["properties"] = config.properties
    data["hotkey"] = config.hotkey
    data["check_updates"] = config.check_updates
    data["shortcuts"] = config.shortcuts
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def forget_bulb(config: Config) -> Config:
    """Return a copy without the bulb's name, IP, token and device id, keeping app preferences."""
    return Config(properties=config.properties, hotkey=config.hotkey, check_updates=config.check_updates,
                  shortcuts=dict(config.shortcuts))
