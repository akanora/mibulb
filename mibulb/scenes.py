"""Scenes: named favourite light settings, like "Reading" or "Movie"."""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass

from .bulb import MAX_KELVIN, MIN_KELVIN, MODE_COLOR, BulbState


@dataclass
class Scene:
    id: str
    name: str
    brightness: int
    mode: str = "white"  # "white" or "color"
    kelvin: int = 4000
    color: int = 0xFFFFFF

    @property
    def is_color(self) -> bool:
        return self.mode == "color"

    @property
    def swatch(self) -> str:
        """A colour to show next to the scene's name."""
        return f"#{self.color:06x}" if self.is_color else kelvin_to_hex(self.kelvin)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Scene":
        return cls(
            id=str(data.get("id") or new_id()),
            name=str(data.get("name") or "Scene"),
            brightness=max(1, min(100, int(data.get("brightness", 100)))),
            mode="color" if data.get("mode") == "color" else "white",
            kelvin=max(MIN_KELVIN, min(MAX_KELVIN, int(data.get("kelvin", 4000)))),
            color=max(1, min(0xFFFFFF, int(data.get("color", 0xFFFFFF)))),
        )

    @classmethod
    def from_state(cls, name: str, state: BulbState) -> "Scene":
        return cls(
            id=new_id(),
            name=name,
            brightness=state.brightness,
            mode="color" if state.mode == MODE_COLOR else "white",
            kelvin=state.color_temperature,
            color=state.color,
        )


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def default_scenes() -> list[Scene]:
    return [
        Scene("reading", "Reading", 100, "white", kelvin=4500),
        Scene("relax", "Relax", 40, "white", kelvin=2700),
        Scene("movie", "Movie", 10, "white", kelvin=2200),
        Scene("gaming", "Gaming", 60, "color", color=0x7C3AED),
        Scene("night", "Night light", 1, "white", kelvin=1700),
    ]


def kelvin_to_hex(kelvin: int) -> str:
    """Approximate RGB of a white light at this colour temperature (Tanner Helland's fit)."""
    t = kelvin / 100

    def clamp(value: float) -> int:
        return int(max(0, min(255, value)))

    if t <= 66:
        red = 255.0
        green = 99.4708025861 * math.log(t) - 161.1195681661
        blue = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        red = 329.698727446 * (t - 60) ** -0.1332047592
        green = 288.1221695283 * (t - 60) ** -0.0755148492
        blue = 255.0
    return f"#{clamp(red):02x}{clamp(green):02x}{clamp(blue):02x}"
