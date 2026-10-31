"""Light effects that run on the bulb itself (Yeelight "colour flow").

The bulb plays the effect on its own, so it is perfectly smooth and needs no
PC or network traffic once started. Each step is (milliseconds, mode, value,
brightness): mode 1 = RGB colour, 2 = white temperature in kelvin.
"""

from __future__ import annotations

from dataclasses import dataclass

COLOR, WHITE = 1, 2


@dataclass(frozen=True)
class Effect:
    id: str
    name: str
    steps: tuple[tuple[int, int, int, int], ...]

    def expression(self) -> str:
        return ",".join(f"{max(50, ms)},{mode},{value},{max(1, min(100, bright))}"
                        for ms, mode, value, bright in self.steps)


def _cycle(colors: list[int], ms: int, brightness: int = 100) -> tuple:
    return tuple((ms, COLOR, color, brightness) for color in colors)


EFFECTS = [
    Effect("candle", "Candle", (
        (800, WHITE, 1900, 50), (800, WHITE, 1800, 30), (1200, WHITE, 2000, 80), (800, WHITE, 1850, 60),
        (1200, WHITE, 1950, 90), (2400, WHITE, 1800, 50), (1200, WHITE, 2000, 80), (800, WHITE, 1900, 60),
        (400, WHITE, 1850, 70),
    )),
    Effect("breathe", "Breathing", ((2500, WHITE, 3000, 100), (2500, WHITE, 3000, 5))),
    Effect("rainbow", "Rainbow", _cycle([0xFF0000, 0xFF8800, 0xFFEE00, 0x22FF00, 0x00CCFF, 0x2244FF, 0xAA00FF],
                                        3000)),
    Effect("party", "Party", _cycle([0xFF0040, 0x00FF60, 0x2060FF, 0xFFD000, 0xFF00FF, 0x00FFFF], 400)),
    Effect("romance", "Romance", _cycle([0xFF2070, 0xB0208A, 0xFF5050, 0x9030C0], 4000, 40)),
    Effect("ocean", "Ocean", _cycle([0x0040FF, 0x00A0C0, 0x0070FF, 0x00C090], 5000, 60)),
    Effect("police", "Police", _cycle([0xFF0000, 0x0000FF], 300)),
    Effect("alarm", "Alarm", ((250, COLOR, 0xFF0000, 100), (250, COLOR, 0xFF0000, 1))),
]
BY_ID = {effect.id: effect for effect in EFFECTS}

# start_cf actions: what the bulb does when a finite flow ends
RECOVER, STAY, TURN_OFF = 0, 1, 2
