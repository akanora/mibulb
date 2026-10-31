"""Command-line interface. Running without a command opens the window."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from . import config as config_mod
from .bulb import Bulb, BulbGroup, parse_color
from .cloud import CloudError, QrLogin, XiaomiCloud
from .miio import MiIOError, discover


def _login() -> None:
    login = QrLogin()
    qr = login.start()
    print("Open this link and scan the QR code with the Xiaomi Home app on your phone:")
    print(f"  {qr.login_url or qr.image_url}")
    print("Waiting for you to scan it (Ctrl+C to cancel)…")
    session = login.wait(qr)
    print("Signed in. Reading your devices from every region…")
    devices = XiaomiCloud(session).all_devices()
    devices.sort(key=lambda d: not d.is_light)
    if not devices:
        raise SystemExit("No devices found on this Xiaomi account.")
    for number, device in enumerate(devices, 1):
        print(f"  {number}. {device.label}")
    choice = input("Which ones are your bulbs? Numbers separated by commas [1]: ").strip() or "1"
    cfg = config_mod.load()
    for number in choice.replace(" ", "").split(","):
        device = devices[int(number) - 1]
        existing = next((b for b in cfg.bulbs if b.did and b.did == device.did), None)
        if existing is None:
            existing = config_mod.BulbInfo(config_mod.new_bulb_id(), device.name)
            cfg.bulbs.append(existing)
        existing.ip, existing.token, existing.did = device.ip or existing.ip, device.token, device.did
        print(f"Saved {device.name}")
    print(f"Settings are in {config_mod.save(cfg)}")


def _bulb(args: argparse.Namespace) -> Bulb | BulbGroup:
    if args.ip or args.token:
        if not (args.ip and args.token):
            raise SystemExit("Pass both --ip and --token.")
        return Bulb(args.ip, args.token)
    cfg = config_mod.load()
    for problem in config_mod.load_problems:
        print(f"warning: {problem}", file=sys.stderr)
    if args.bulb:
        wanted = args.bulb.lower()
        if wanted == config_mod.ALL:
            cfg.selected = config_mod.ALL
        else:
            match = [b for b in cfg.usable_bulbs if b.name.lower() == wanted or b.id == args.bulb]
            if not match:
                names = ", ".join(b.name for b in cfg.usable_bulbs) or "none"
                raise SystemExit(f"No bulb called {args.bulb!r}. Your bulbs: {names}")
            cfg.selected = match[0].id
    if not cfg.is_complete:
        raise SystemExit("No bulb configured. Run 'mibulb login', or pass --ip and --token.")
    return BulbGroup(cfg.current_bulbs)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mibulb", description="Control a Mi Smart LED Bulb over your local network.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--ip", help="bulb IP address (overrides config.json)")
    parser.add_argument("--token", help="32-character device token (overrides config.json)")
    parser.add_argument("--bulb", help="which bulb to control: its name, or 'all' (default: the one picked in the app)")
    parser.add_argument("--minimized", action="store_true", help="start the window hidden in the system tray")
    parser.add_argument("--restarted", action="store_true", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser("gui", help="open the window (default)")
    sub.add_parser("on", help="turn the light on")
    sub.add_parser("off", help="turn the light off")
    sub.add_parser("toggle", help="toggle the light")
    sub.add_parser("status", help="show the current state")
    sub.add_parser("discover", help="find miIO devices on the network")
    sub.add_parser("login", help="sign in to your Xiaomi account and add bulbs")
    p = sub.add_parser("brightness", help="set brightness (1-100)")
    p.add_argument("percent", type=int)
    p = sub.add_parser("temp", help="set white colour temperature (1700-6500 K)")
    p.add_argument("kelvin", type=int)
    p = sub.add_parser("color", help="set colour, e.g. ff8800")
    p.add_argument("hex")

    args = parser.parse_args(argv)

    if args.command in (None, "gui"):
        from .gui import main as gui_main

        gui_main(start_minimized=args.minimized, restarted=args.restarted)
        return

    try:
        if args.command == "login":
            _login()
            return
        if args.command == "discover":
            devices = discover()
            if not devices:
                print("No miIO devices answered. Check that this PC is on the same network as the bulb.")
            for ip, device_id in devices:
                print(f"{ip}\tdevice id {device_id}")
            return

        bulb = _bulb(args)
        if args.command == "on":
            bulb.turn_on()
        elif args.command == "off":
            bulb.turn_off()
        elif args.command == "toggle":
            print("on" if bulb.toggle() else "off")
        elif args.command == "brightness":
            bulb.set_brightness(args.percent)
        elif args.command == "temp":
            bulb.set_color_temperature(args.kelvin)
        elif args.command == "color":
            bulb.set_color(parse_color(args.hex))
        elif args.command == "status":
            s = bulb.status()
            print(f"power:       {'on' if s.on else 'off'}")
            print(f"brightness:  {s.brightness}%")
            print(f"mode:        {'colour' if s.mode == 1 else 'white'}")
            print(f"temperature: {s.color_temperature} K")
            print(f"colour:      {s.color_hex}")
    except (MiIOError, CloudError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
