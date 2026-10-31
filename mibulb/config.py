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
    )


def save(config: Config, path: Path | None = None) -> Path:
    path = path or find_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"ip": config.ip, "token": config.token, "name": config.name}
    if config.did:
        data["did"] = config.did
    if config.properties:
        data["properties"] = config.properties
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path
