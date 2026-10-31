"""Schedules, sleep timer and sunrise wake-up.

A schedule runs an action at a time of day on chosen weekdays. Actions are
"on", "off", "scene:<id>", or "sunrise:<minutes>" (a slow wake-up light).
Fades are planned here as a list of steps; the app sends them over time.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAYS = [0, 1, 2, 3, 4]
WEEKEND = [5, 6]
EVERY_DAY = list(range(7))

SLEEP_TIMER_MINUTES = [15, 30, 45, 60, 90]
SUNRISE_MINUTES = [10, 15, 30]

# Sunrise starts as a dim, deep warm glow and ends as bright neutral white.
SUNRISE_START = (1, 1700)
SUNRISE_END = (100, 4000)

# The bulb only accepts about one command per second, so fades move in steps.
MIN_STEP_SECONDS = 20


@dataclass
class Schedule:
    id: str
    time: str  # "HH:MM", 24-hour
    days: list[int] = field(default_factory=lambda: list(EVERY_DAY))  # 0 = Monday
    action: str = "on"
    enabled: bool = True

    def due(self, now: datetime) -> bool:
        return self.enabled and now.weekday() in self.days and now.strftime("%H:%M") == self.time

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        return cls(
            id=str(data.get("id") or new_id()),
            time=normalise_time(str(data.get("time", "07:00"))),
            days=sorted({int(d) for d in data.get("days", EVERY_DAY) if 0 <= int(d) <= 6}),
            action=str(data.get("action", "on")),
            enabled=bool(data.get("enabled", True)),
        )


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def normalise_time(text: str) -> str:
    """Accept "7:5", "07:05", "7.05" and return "07:05"."""
    text = text.strip().replace(".", ":")
    hours, _, minutes = text.partition(":")
    h, m = int(hours), int(minutes or 0)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError("Time must be between 00:00 and 23:59")
    return f"{h:02d}:{m:02d}"


def describe_days(days: list[int]) -> str:
    days = sorted(set(days))
    if days == EVERY_DAY:
        return "Every day"
    if days == WEEKDAYS:
        return "Weekdays"
    if days == WEEKEND:
        return "Weekends"
    if not days:
        return "Never"
    return ", ".join(DAY_NAMES[d] for d in days)


def sunrise_minutes(action: str) -> int | None:
    if action.startswith("sunrise:"):
        try:
            return max(1, int(action.split(":", 1)[1]))
        except ValueError:
            return 15
    return None


@dataclass
class Step:
    at: float  # seconds after the start
    brightness: int
    kelvin: int | None = None  # None: keep the current colour


def plan_fade(minutes: float, start: tuple[int, int | None], end: tuple[int, int | None]) -> list[Step]:
    """Evenly spaced steps from start to end (brightness, kelvin), including both ends."""
    total = max(1.0, minutes * 60)
    count = max(1, int(total // MIN_STEP_SECONDS))
    (b0, k0), (b1, k1) = start, end
    steps = []
    for i in range(count + 1):
        f = i / count
        brightness = round(b0 + (b1 - b0) * f)
        kelvin = None if k0 is None or k1 is None else round(k0 + (k1 - k0) * f)
        steps.append(Step(total * f, max(1, min(100, brightness)), kelvin))
    # Drop steps that wouldn't change anything.
    unique = [steps[0]]
    for step in steps[1:]:
        if (step.brightness, step.kelvin) != (unique[-1].brightness, unique[-1].kelvin) or step is steps[-1]:
            unique.append(step)
    return unique


def plan_sleep_timer(minutes: float, brightness: int) -> list[Step]:
    """Dim from the current brightness to the lowest over the timer; the app then turns the light off."""
    return plan_fade(minutes, (brightness, None), (1, None))


def plan_sunrise(minutes: float) -> list[Step]:
    return plan_fade(minutes, SUNRISE_START, SUNRISE_END)
