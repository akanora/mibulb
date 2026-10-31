"""High-level control of a Mi / Yeelight bulb.

Two command sets exist for the same bulbs, depending on firmware:

- "yeelight": the original Yeelight miIO commands (get_prop, set_power,
  set_bright, set_ct_abx, set_rgb). The Mi Smart LED Bulb Essential on
  firmware 2.0.x only understands these.
- "miot": MIoT get_properties / set_properties with ids from
  https://home.miot-spec.com/spec/yeelink.light.color5

By default the bulb is probed once to see which one it speaks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .miio import Device, DeviceUnreachable, MiIOError, find_ip

LIGHT_SIID = 2

# MIoT ids for yeelink.light.color5; other MIoT lights may use different ids,
# which can be overridden with the "properties" key in config.json.
DEFAULT_PROPERTIES = {
    "on": 1,
    "brightness": 2,
    "color_temperature": 3,
    "color": 4,
    "mode": 5,
}

MODE_COLOR = 1
MODE_WHITE = 2

MIN_KELVIN = 1700
MAX_KELVIN = 6500

# Fade time for Yeelight commands, so changes look smooth but sliders stay snappy.
FADE_MS = 300


@dataclass
class BulbState:
    on: bool
    brightness: int
    color_temperature: int
    color: int
    mode: int

    @property
    def color_hex(self) -> str:
        return f"#{self.color:06x}"


class Bulb:
    def __init__(
        self,
        ip: str,
        token: str,
        siid: int = LIGHT_SIID,
        properties: dict[str, int] | None = None,
        protocol: str = "auto",
    ):
        self.device = Device(ip, token)
        self.siid = siid
        self.piids = {**DEFAULT_PROPERTIES, **(properties or {})}
        if protocol not in ("auto", "yeelight", "miot"):
            raise ValueError(f"Unknown protocol {protocol!r}")
        self.protocol = protocol
        self._scene_supported: bool | None = None

    # ---- protocol detection ------------------------------------------------

    def _detect(self) -> str:
        if self.protocol != "auto":
            return self.protocol
        # A bulb that doesn't know a command either errors or stays silent,
        # so probe with a short timeout and no retries.
        timeout, retries = self.device.timeout, self.device.retries
        self.device.timeout, self.device.retries = 1.5, 0
        try:
            result = self.device.send("get_prop", ["power"])
            detected = "yeelight" if isinstance(result, list) and result and result[0] in ("on", "off") else "miot"
        except DeviceUnreachable:
            # No answer to get_prop. Try MIoT, which surfaces a real "unreachable" if it's offline.
            self.device.timeout, self.device.retries = timeout, retries
            self.device.send("get_properties", [{"did": "on", "siid": self.siid, "piid": self.piids["on"]}])
            detected = "miot"
        except MiIOError:
            detected = "miot"
        finally:
            self.device.timeout, self.device.retries = timeout, retries
        self.protocol = detected
        return detected

    # ---- MIoT ------------------------------------------------------------

    def _miot_set(self, **values: object) -> None:
        params = [
            {"did": name, "siid": self.siid, "piid": self.piids[name], "value": value}
            for name, value in values.items()
        ]
        result = self.device.send("set_properties", params)
        for item in result or []:
            if item.get("code", 0) != 0:
                raise MiIOError(f"Bulb rejected {item.get('did')} (code {item.get('code')})")

    def _miot_status(self) -> BulbState:
        params = [{"did": name, "siid": self.siid, "piid": piid} for name, piid in self.piids.items()]
        result = self.device.send("get_properties", params)
        values = {item["did"]: item.get("value") for item in result if item.get("code", 0) == 0}
        missing = set(self.piids) - set(values)
        if missing:
            raise MiIOError(f"Bulb did not report: {', '.join(sorted(missing))}")
        return BulbState(
            on=bool(values["on"]),
            brightness=int(values["brightness"]),
            color_temperature=int(values["color_temperature"]),
            color=int(values["color"]),
            mode=int(values["mode"]),
        )

    # ---- Yeelight --------------------------------------------------------

    def _yeelight(self, method: str, *args: object) -> None:
        result = self.device.send(method, [*args, "smooth", FADE_MS])
        if result != ["ok"]:
            raise MiIOError(f"Bulb rejected {method}: {result}")

    def _yeelight_status(self) -> BulbState:
        power, bright, ct, rgb, color_mode = self.device.send(
            "get_prop", ["power", "bright", "ct", "rgb", "color_mode"]
        )

        def number(value: object, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        # color_mode: 1 = RGB, 2 = colour temperature, 3 = HSV
        return BulbState(
            on=power == "on",
            brightness=number(bright, 100),
            color_temperature=number(ct, 4000),
            color=number(rgb, 0xFFFFFF),
            mode=MODE_COLOR if number(color_mode, 2) in (1, 3) else MODE_WHITE,
        )

    # ---- public API ------------------------------------------------------

    def status(self) -> BulbState:
        return self._yeelight_status() if self._detect() == "yeelight" else self._miot_status()

    def set_power(self, on: bool) -> None:
        if self._detect() == "yeelight":
            self._yeelight("set_power", "on" if on else "off")
        else:
            self._miot_set(on=on)

    def turn_on(self) -> None:
        self.set_power(True)

    def turn_off(self) -> None:
        self.set_power(False)

    def toggle(self) -> bool:
        """Toggle power and return the new state."""
        new_state = not self.status().on
        self.set_power(new_state)
        return new_state

    def set_brightness(self, percent: int) -> None:
        percent = max(1, min(100, int(percent)))
        if self._detect() == "yeelight":
            self._yeelight("set_bright", percent)
        else:
            self._miot_set(brightness=percent)

    def set_color_temperature(self, kelvin: int) -> None:
        kelvin = max(MIN_KELVIN, min(MAX_KELVIN, int(kelvin)))
        if self._detect() == "yeelight":
            self._yeelight("set_ct_abx", kelvin)
        else:
            self._miot_set(color_temperature=kelvin)

    def set_color(self, rgb: int) -> None:
        # 0 (black) is outside the valid range, so clamp to the darkest blue.
        rgb = max(1, min(0xFFFFFF, int(rgb)))
        if self._detect() == "yeelight":
            self._yeelight("set_rgb", rgb)
        else:
            self._miot_set(color=rgb)


    def apply_scene(self, brightness: int, kelvin: int | None = None, rgb: int | None = None) -> None:
        """Turn on and set brightness plus either a white temperature or a colour."""
        brightness = max(1, min(100, int(brightness)))
        if kelvin is not None:
            kelvin = max(MIN_KELVIN, min(MAX_KELVIN, int(kelvin)))
        if rgb is not None:
            rgb = max(1, min(0xFFFFFF, int(rgb)))
        if self._detect() == "yeelight":
            # set_scene does it all in one command and turns the light on. Bulbs
            # often ignore unknown commands silently, so probe it quickly once.
            scene = ["color", rgb, brightness] if rgb is not None else ["ct", kelvin, brightness]
            if self._scene_supported is not False:
                timeout, retries = self.device.timeout, self.device.retries
                if self._scene_supported is None:
                    self.device.timeout, self.device.retries = 1.5, 0
                try:
                    ok = self.device.send("set_scene", scene) == ["ok"]
                except MiIOError:
                    ok = False
                finally:
                    self.device.timeout, self.device.retries = timeout, retries
                self._scene_supported = ok
                if ok:
                    return
            # Step by step for firmware without set_scene
            self._yeelight("set_power", "on")
            if rgb is not None:
                self._yeelight("set_rgb", rgb)
            else:
                self._yeelight("set_ct_abx", kelvin)
            self._yeelight("set_bright", brightness)
        else:
            values: dict[str, object] = {"on": True, "brightness": brightness}
            if rgb is not None:
                values["color"] = rgb
            else:
                values["color_temperature"] = kelvin
            self._miot_set(**values)


class BulbGroup:
    """Sends each command to one or more bulbs, with the same methods as Bulb.

    If a bulb stops answering and has a device id, it is looked for on the
    network in case the router gave it a new IP; on_moved(member) is then
    called so the new IP can be saved.
    """

    def __init__(self, members: list, on_moved: Callable[[Any], None] | None = None):
        # members: objects with .name, .ip, .token, .did and .properties (config.BulbInfo)
        self.members = [(info, Bulb(info.ip, info.token, properties=info.properties)) for info in members]
        self.on_moved = on_moved

    @property
    def names(self) -> list[str]:
        return [info.name for info, _bulb in self.members]

    def _with_relocate(self, info: Any, bulb: Bulb, func: Callable[[Bulb], Any]) -> Any:
        try:
            return func(bulb)
        except DeviceUnreachable:
            if not str(info.did).isdigit():
                raise
            ip = find_ip(int(info.did))
            if not ip or ip == bulb.device.ip:
                raise
            info.ip = bulb.device.ip = ip
            if self.on_moved is not None:
                self.on_moved(info)
            return func(bulb)

    def _each(self, func: Callable[[Bulb], Any]) -> list:
        results, failed = [], []
        for info, bulb in self.members:
            try:
                results.append(self._with_relocate(info, bulb, func))
            except MiIOError as exc:
                failed.append((info, exc))
        if failed:
            if len(self.members) == 1:
                raise failed[0][1]
            names = ", ".join(info.name for info, _exc in failed)
            raise MiIOError(f"{names} didn't respond ({failed[0][1]})")
        return results

    def status(self) -> BulbState:
        """The state of the first bulb that answers."""
        first_error: MiIOError | None = None
        for info, bulb in self.members:
            try:
                return self._with_relocate(info, bulb, lambda b: b.status())
            except MiIOError as exc:
                first_error = first_error or exc
        raise first_error or MiIOError("No bulbs")

    def set_power(self, on: bool) -> None:
        self._each(lambda b: b.set_power(on))

    def turn_on(self) -> None:
        self.set_power(True)

    def turn_off(self) -> None:
        self.set_power(False)

    def toggle(self) -> bool:
        # Base it on one bulb so a group always ends up all on or all off.
        new_state = not self.status().on
        self.set_power(new_state)
        return new_state

    def set_brightness(self, percent: int) -> None:
        self._each(lambda b: b.set_brightness(percent))

    def set_color_temperature(self, kelvin: int) -> None:
        self._each(lambda b: b.set_color_temperature(kelvin))

    def set_color(self, rgb: int) -> None:
        self._each(lambda b: b.set_color(rgb))

    def apply_scene(self, brightness: int, kelvin: int | None = None, rgb: int | None = None) -> None:
        self._each(lambda b: b.apply_scene(brightness, kelvin=kelvin, rgb=rgb))


def parse_color(text: str) -> int:
    """Parse "#ff8800", "ff8800" or "0xff8800" into an integer."""
    text = text.strip().lower().removeprefix("#").removeprefix("0x")
    if len(text) != 6:
        raise ValueError("Colour must look like #RRGGBB")
    return int(text, 16)
