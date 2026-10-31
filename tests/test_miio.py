"""Tests that run against a fake MIoT bulb on localhost."""

import json
import socket
import struct
import threading
import unittest
from unittest import mock

from mibulb import miio
from mibulb.bulb import Bulb, parse_color

TOKEN = "0123456789abcdef0123456789abcdef"
DEVICE_ID = 0x1234ABCD


class FakeBulb:
    """Answers hello packets and MIoT get/set_properties like the real bulb."""

    def __init__(self, yeelight=False, scenes=True):
        self.yeelight = yeelight
        self.scenes = scenes  # whether set_scene is understood
        self.methods = []
        self.flow = None  # colour flow expression while an effect plays
        self.off_timer = None  # minutes on the bulb's own off-timer
        self.token = bytes.fromhex(TOKEN)
        self.props = {1: False, 2: 50, 3: 4000, 4: 0xFFFFFF, 5: 2}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self):
        self.sock.close()

    def _serve(self):
        while True:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError:
                return
            if data == miio.HELLO:
                reply = struct.pack(">HHIII", miio.MAGIC, 32, 0, DEVICE_ID, 1000) + b"\xff" * 16
                self.sock.sendto(reply, addr)
                continue
            request = miio.parse_packet(self.token, data)
            result = self._handle(request["method"], request["params"])
            if result is None:
                continue  # stay silent, like a real bulb given an unknown command
            payload = json.dumps({"id": request["id"], "result": result}).encode()
            self.sock.sendto(miio.build_packet(self.token, DEVICE_ID, 1001, payload), addr)

    def _handle(self, method, params):
        self.methods.append(method)
        if self.yeelight:
            return self._handle_yeelight(method, params)
        if method == "get_properties":
            return [{**p, "code": 0, "value": self.props[p["piid"]]} for p in params]
        if method == "set_properties":
            for p in params:
                self.props[p["piid"]] = p["value"]
                if p["piid"] == 4:
                    self.props[5] = 1
                elif p["piid"] == 3:
                    self.props[5] = 2
            return [{"did": p["did"], "siid": p["siid"], "piid": p["piid"], "code": 0} for p in params]
        return []

    def _handle_yeelight(self, method, params):
        p = self.props
        if method == "get_prop":
            values = {"power": "on" if p[1] else "off", "bright": str(p[2]), "ct": str(p[3]),
                      "rgb": str(p[4]), "color_mode": "1" if p[5] == 1 else "2"}
            return [values[name] for name in params]
        setters = {"set_power": (1, lambda v: v == "on"), "set_bright": (2, int), "set_ct_abx": (3, int),
                   "set_rgb": (4, int)}
        if method in setters:
            assert params[1:] == ["smooth", 300], params
            piid, convert = setters[method]
            p[piid] = convert(params[0])
            if method in ("set_rgb", "set_ct_abx"):
                p[5] = 1 if method == "set_rgb" else 2
            return ["ok"]
        if method == "start_cf":
            self.flow = params[2]
            return ["ok"]
        if method == "stop_cf":
            self.flow = None
            return ["ok"]
        if method == "cron_add":
            self.off_timer = params[1]
            return ["ok"]
        if method == "cron_del":
            self.off_timer = None
            return ["ok"]
        if method == "cron_get":
            return [{"type": 0, "delay": self.off_timer, "mix": 0}] if self.off_timer else []
        if method == "set_scene" and self.scenes:
            kind, value, bright = params
            p[1], p[2] = True, bright
            if kind == "color":
                p[4], p[5] = value, 1
            else:
                p[3], p[5] = value, 2
            return ["ok"]
        return None


class CryptoTest(unittest.TestCase):
    def test_round_trip(self):
        token = bytes.fromhex(TOKEN)
        packet = miio.build_packet(token, DEVICE_ID, 42, b'{"id":1,"method":"x","params":[]}')
        header = miio.parse_header(packet)
        self.assertEqual(header.device_id, DEVICE_ID)
        self.assertEqual(header.stamp, 42)
        self.assertEqual(header.length, len(packet))
        self.assertEqual(miio.parse_packet(token, packet)["method"], "x")

    def test_wrong_token_is_rejected(self):
        packet = miio.build_packet(bytes.fromhex(TOKEN), DEVICE_ID, 42, b"{}")
        with self.assertRaises(miio.MiIOError):
            miio.parse_packet(bytes(16), packet)

    def test_bad_token_format(self):
        with self.assertRaises(miio.MiIOError):
            miio.parse_token("not-a-token")

    def test_parse_color(self):
        self.assertEqual(parse_color("#FF8800"), 0xFF8800)
        self.assertEqual(parse_color("0x00ff00"), 0x00FF00)
        with self.assertRaises(ValueError):
            parse_color("fff")


class BulbTest(unittest.TestCase):
    yeelight = False

    def setUp(self):
        self.fake = FakeBulb(yeelight=self.yeelight)
        patcher = mock.patch.object(miio, "PORT", self.fake.port)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.fake.close)
        self.bulb = Bulb("127.0.0.1", TOKEN)

    def test_power(self):
        self.assertFalse(self.bulb.status().on)
        self.bulb.turn_on()
        self.assertTrue(self.bulb.status().on)
        self.assertFalse(self.bulb.toggle())
        self.assertFalse(self.fake.props[1])

    def test_brightness_is_clamped(self):
        self.bulb.set_brightness(150)
        self.assertEqual(self.fake.props[2], 100)
        self.bulb.set_brightness(0)
        self.assertEqual(self.fake.props[2], 1)

    def test_colour_and_temperature(self):
        self.bulb.set_color(0xFF0000)
        state = self.bulb.status()
        self.assertEqual(state.color_hex, "#ff0000")
        self.assertEqual(state.mode, 1)
        self.bulb.set_color_temperature(9000)
        state = self.bulb.status()
        self.assertEqual(state.color_temperature, 6500)
        self.assertEqual(state.mode, 2)

    def test_unreachable_device(self):
        self.fake.close()
        bulb = Bulb("127.0.0.1", TOKEN)
        bulb.device.timeout = 0.2
        bulb.device.retries = 0
        with self.assertRaises(miio.MiIOError):
            bulb.status()

    def test_detects_protocol(self):
        self.bulb.status()
        self.assertEqual(self.bulb.protocol, "yeelight" if self.yeelight else "miot")


class SceneTest(unittest.TestCase):
    def make(self, **kwargs):
        fake = FakeBulb(**kwargs)
        patcher = mock.patch.object(miio, "PORT", fake.port)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(fake.close)
        return fake, Bulb("127.0.0.1", TOKEN)

    def check(self, fake, bulb):
        bulb.apply_scene(40, kelvin=2700)
        state = bulb.status()
        self.assertEqual((state.on, state.brightness, state.color_temperature, state.mode), (True, 40, 2700, 2))
        bulb.apply_scene(60, rgb=0x7C3AED)
        state = bulb.status()
        self.assertEqual((state.on, state.brightness, state.color, state.mode), (True, 60, 0x7C3AED, 1))

    def test_yeelight_set_scene(self):
        fake, bulb = self.make(yeelight=True)
        self.check(fake, bulb)
        self.assertNotIn("set_power", fake.methods)  # done in one command each time

    def test_yeelight_without_set_scene_falls_back(self):
        fake, bulb = self.make(yeelight=True, scenes=False)
        self.check(fake, bulb)
        self.assertEqual(fake.methods.count("set_scene"), 1)  # probed once, then remembered

    def test_miot(self):
        fake, bulb = self.make()
        self.check(fake, bulb)


class YeelightBulbTest(BulbTest):
    """Same tests against a bulb that only knows the older Yeelight commands."""

    yeelight = True


if __name__ == "__main__":
    unittest.main()
