"""Schedules, sleep timer and sunrise wake-up.

A schedule runs an action at a time of day on chosen weekdays. Actions are
"on", "off", "scene:<id>", or "sunrise:<minutes>" (a slow wake-up light).
Fades are planned here as a list of steps; the app sends them over time.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone

from .i18n import t

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
    target: str = ""  # "" = the lights picked in the window, "all", or a bulb id

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
            target=str(data.get("target", "")),
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
        return t("Every day")
    if days == WEEKDAYS:
        return t("Weekdays")
    if days == WEEKEND:
        return t("Weekends")
    if not days:
        return t("Never")
    return ", ".join(t(DAY_NAMES[d]) for d in days)


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


# ---- evening warmth --------------------------------------------------------------

DAY_KELVIN = 5000  # where the evening fade starts
WARMTH_KELVIN_CHOICES = [2200, 2700, 3000]


def sunset(latitude: float, longitude: float, day: date) -> datetime | None:
    """Local sunset time (NOAA's approximation, within a minute or two). None during polar day/night."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    lat = math.radians(latitude)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(lat) * math.cos(decl))) - math.tan(lat) * math.tan(decl)
    if not -1 <= cos_ha <= 1:
        return None
    ha = math.degrees(math.acos(cos_ha))
    minutes_utc = 720 - 4 * (longitude - ha) - eqtime
    utc_midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return (utc_midnight + timedelta(minutes=minutes_utc)).astimezone().replace(tzinfo=None)


def parse_location(text: str) -> tuple[float, float] | None:
    """'41.01, 28.98' -> (41.01, 28.98); empty or invalid -> None."""
    try:
        lat_text, lon_text = text.replace(";", ",").split(",")
        lat, lon = float(lat_text), float(lon_text)
    except ValueError:
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


def warmth_start(start: str, location: tuple[float, float] | None, day: date) -> datetime:
    if start == "sunset" and location is not None:
        found = sunset(location[0], location[1], day)
        if found is not None:
            return found
    clock = normalise_time(start if start != "sunset" else "20:00")
    return datetime.combine(day, datetime.strptime(clock, "%H:%M").time())


def warmth_kelvin(now: datetime, start: str, end: str, warm: int,
                  location: tuple[float, float] | None = None) -> int | None:
    """The white temperature evening warmth wants right now, or None during the day.

    From the start time to the end time it fades from DAY_KELVIN down to warm,
    then stays warm until 5:00 the next morning.
    """
    day = now.date() if now.hour >= 5 else (now - timedelta(days=1)).date()
    begin = warmth_start(start, location, day)
    finish = datetime.combine(day, datetime.strptime(normalise_time(end), "%H:%M").time())
    if finish <= begin:
        finish += timedelta(days=1) if finish.hour < 5 else timedelta(0)
        finish = max(finish, begin + timedelta(minutes=1))
    if now < begin:
        return None
    if now >= finish:
        return warm
    progress = (now - begin) / (finish - begin)
    return round(DAY_KELVIN + (warm - DAY_KELVIN) * progress)
