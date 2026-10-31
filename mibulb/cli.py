"""Command-line interface. Running without a command opens the window."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from . import config as config_mod
from .bulb import Bulb, parse_color
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
    choice = input("Which one is your bulb? [1]: ").strip() or "1"
    device = devices[int(choice) - 1]
    cfg = config_mod.load()
    cfg.name, cfg.ip, cfg.token, cfg.did = device.name, device.ip, device.token, device.did
    print(f"Saved {device.name} to {config_mod.save(cfg)}")


def _bulb(args: argparse.Namespace) -> Bulb:
    cfg = config_mod.load()
    ip = args.ip or cfg.ip
    token = args.token or cfg.token
    if not ip or not token:
        raise SystemExit(
            f"No bulb configured. Create {config_mod.find_config_path()} (see config.example.json) "
            "or pass --ip and --token."
        )
    return Bulb(ip, token, properties=cfg.properties)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mibulb", description="Control a Mi Smart LED Bulb over your local network.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--ip", help="bulb IP address (overrides config.json)")
    parser.add_argument("--token", help="32-character device token (overrides config.json)")
    parser.add_argument("--minimized", action="store_true", help="start the window hidden in the system tray")
    sub = parser.add_subparsers(dest="command", metavar="command")

    sub.add_parser("gui", help="open the window (default)")
    sub.add_parser("on", help="turn the light on")
    sub.add_parser("off", help="turn the light off")
    sub.add_parser("toggle", help="toggle the light")
    sub.add_parser("status", help="show the current state")
    sub.add_parser("discover", help="find miIO devices on the network")
    sub.add_parser("login", help="sign in to your Xiaomi account and pick a bulb (saves config.json)")
    p = sub.add_parser("brightness", help="set brightness (1-100)")
    p.add_argument("percent", type=int)
    p = sub.add_parser("temp", help="set white colour temperature (1700-6500 K)")
    p.add_argument("kelvin", type=int)
    p = sub.add_parser("color", help="set colour, e.g. ff8800")
    p.add_argument("hex")

    args = parser.parse_args(argv)

    if args.command in (None, "gui"):
        from .gui import main as gui_main

        gui_main(start_minimized=args.minimized)
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
