"""Several bulbs: config migration, choosing bulbs, and sending commands to a group."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mibulb import bulb as bulb_mod
from mibulb import config, miio
from test_miio import TOKEN, FakeBulb


def info(bulb_id, name, ip="127.0.0.1", did=""):
    return config.BulbInfo(bulb_id, name, ip, TOKEN, did)


class ConfigTest(unittest.TestCase):
    def test_migrates_single_bulb_config(self):
        path = Path(tempfile.mkdtemp()) / "config.json"
        path.write_text(json.dumps({"ip": "192.168.1.102", "token": TOKEN, "name": "Light bulb", "did": "470029281",
                                    "hotkey": False}))
        cfg = config.load(path)
        self.assertEqual([(b.id, b.name, b.ip, b.did) for b in cfg.bulbs],
                         [("main", "Light bulb", "192.168.1.102", "470029281")])
        self.assertFalse(cfg.hotkey)
        config.save(cfg, path)
        saved = json.loads(path.read_text())
        self.assertNotIn("ip", saved)  # now stored under "bulbs"
        self.assertEqual(config.load(path).bulbs[0].token, TOKEN)

    def test_selection(self):
        cfg = config.Config(bulbs=[info("a", "Desk"), info("b", "Bed"), config.BulbInfo("c", "No token", "1.2.3.4")])
        self.assertEqual([b.id for b in cfg.usable_bulbs], ["a", "b"])
        self.assertEqual([b.id for b in cfg.current_bulbs], ["a"])  # nothing picked: the first
        self.assertEqual(cfg.display_name, "Desk")
        cfg.selected = "b"
        self.assertEqual([b.id for b in cfg.current_bulbs], ["b"])
        cfg.selected = config.ALL
        self.assertEqual([b.id for b in cfg.current_bulbs], ["a", "b"])
        self.assertEqual(cfg.display_name, "All lights")
        cfg.selected = "gone"  # removed bulb: fall back to the first
        self.assertEqual([b.id for b in cfg.current_bulbs], ["a"])

    def test_empty(self):
        cfg = config.Config()
        self.assertFalse(cfg.is_complete)
        self.assertEqual((cfg.current_bulbs, cfg.display_name), ([], "Mi Bulb"))


class GroupTest(unittest.TestCase):
    def setUp(self):
        self.fakes = [FakeBulb(yeelight=True), FakeBulb()]
        for fake in self.fakes:
            self.addCleanup(fake.close)
        # Each fake listens on its own port; route by "IP" (we use the port number as a stand-in).
        self.ports = {f"127.0.0.{i + 1}": fake.port for i, fake in enumerate(self.fakes)}
        real_init = miio.Device.__init__

        def init(device, ip, token, timeout=3.0, retries=2):
            real_init(device, ip, token, timeout, retries)

        original_send = miio.Device.send
        ports = self.ports

        def send(device, method, params=None):
            with mock.patch.object(miio, "PORT", ports.get(device.ip, 1)):
                real_ip = device.ip
                device.ip = "127.0.0.1"
                try:
                    return original_send(device, method, params)
                finally:
                    device.ip = real_ip

        patcher = mock.patch.object(miio.Device, "send", send)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_commands_reach_every_bulb(self):
        group = bulb_mod.BulbGroup([info("a", "Desk", "127.0.0.1"), info("b", "Bed", "127.0.0.2")])
        group.turn_on()
        group.set_brightness(30)
        self.assertEqual([(f.props[1], f.props[2]) for f in self.fakes], [(True, 30), (True, 30)])
        group.apply_scene(60, rgb=0x7C3AED)
        self.assertEqual([(f.props[2], f.props[4]) for f in self.fakes], [(60, 0x7C3AED), (60, 0x7C3AED)])
        self.assertFalse(group.toggle())  # both were on, so both go off
        self.assertEqual([f.props[1] for f in self.fakes], [False, False])

    def test_one_bulb_offline(self):
        offline = info("c", "Hall", "127.0.0.9")
        group = bulb_mod.BulbGroup([info("a", "Desk", "127.0.0.1"), offline])
        group.members[1][1].device.timeout = 0.2
        group.members[1][1].device.retries = 0
        with self.assertRaises(miio.MiIOError) as caught:
            group.set_brightness(20)
        self.assertIn("Hall", str(caught.exception))
        self.assertEqual(self.fakes[0].props[2], 20)  # the working bulb still changed
        self.assertTrue(group.status() is not None)  # status comes from a bulb that answers

    def test_moved_bulb_is_found_again(self):
        moved = info("b", "Bed", "127.0.0.7", did="4242")
        seen = []
        group = bulb_mod.BulbGroup([moved], on_moved=seen.append)
        group.members[0][1].device.timeout = 0.2
        group.members[0][1].device.retries = 0
        with mock.patch.object(bulb_mod, "find_ip", return_value="127.0.0.2") as find:
            group.set_brightness(45)
        find.assert_called_once_with(4242)
        self.assertEqual((moved.ip, self.fakes[1].props[2]), ("127.0.0.2", 45))
        self.assertEqual(seen, [moved])


if __name__ == "__main__":
    unittest.main()
