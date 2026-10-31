"""Tests for start-with-Windows, the global shortcut, update checks and forgetting the bulb."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mibulb import config, hotkey, startup, updates


class UpdatesTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updates.parse_version("v0.10.1"), (0, 10, 1))
        self.assertGreater(updates.parse_version("0.10.0"), updates.parse_version("0.9.9"))
        self.assertEqual(updates.parse_version("1.2.0-beta"), (1, 2, 0))

    def _check(self, tag, current):
        response = mock.Mock()
        response.json.return_value = {"tag_name": tag, "html_url": "https://example/release"}
        with mock.patch.object(updates.requests, "get", return_value=response):
            return updates.check(current)

    def test_newer_release(self):
        update = self._check("v0.4.0", "0.3.0")
        self.assertEqual((update.version, update.url), ("0.4.0", "https://example/release"))

    def test_same_or_older_release(self):
        self.assertIsNone(self._check("v0.3.0", "0.3.0"))
        self.assertIsNone(self._check("v0.2.0", "0.3.0"))


class ForgetBulbTest(unittest.TestCase):
    def test_keeps_preferences_only(self):
        cfg = config.Config(ip="1.2.3.4", token="a" * 32, name="Desk", did="5", hotkey=False, check_updates=False)
        forgotten = config.forget_bulb(cfg)
        self.assertEqual((forgotten.ip, forgotten.token, forgotten.did, forgotten.name), ("", "", "", "Light"))
        self.assertFalse(forgotten.hotkey)
        self.assertFalse(forgotten.check_updates)
        self.assertFalse(forgotten.is_complete)

    def test_preferences_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "config.json"
        config.save(config.Config(ip="1.2.3.4", token="a" * 32, hotkey=False), path)
        loaded = config.load(path)
        self.assertFalse(loaded.hotkey)
        self.assertTrue(loaded.check_updates)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class StartupTest(unittest.TestCase):
    def setUp(self):
        import winreg

        # Use a throwaway key so the real "start with Windows" setting is untouched.
        self.key = r"Software\mibulb-test-run"
        self.shortcut = Path(tempfile.mkdtemp()) / "Mi Bulb.lnk"
        for patcher in (
            mock.patch.object(startup, "RUN_KEY", self.key),
            mock.patch.object(startup, "_legacy_shortcut", lambda: self.shortcut),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self._delete_key)

    def _delete_key(self):
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, self.key)
        except FileNotFoundError:
            pass

    def test_enable_disable(self):
        self.assertFalse(startup.is_enabled())
        startup.enable()
        self.assertTrue(startup.is_enabled())
        self.assertIn("--minimized", startup._read())
        startup.disable()
        self.assertFalse(startup.is_enabled())

    def test_legacy_shortcut_counts_and_is_removed(self):
        self.shortcut.write_bytes(b"")
        self.assertTrue(startup.is_enabled())
        startup.disable()
        self.assertFalse(self.shortcut.exists())

    def test_repair_moved_exe(self):
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.key) as key:
            winreg.SetValueEx(key, startup.VALUE_NAME, 0, winreg.REG_SZ, '"C:\\gone\\MiBulb.exe" --minimized')
        startup.repair()
        self.assertEqual(startup._read(), startup.launch_command())


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class HotkeyTest(unittest.TestCase):
    def test_register_and_conflict(self):
        # An unusual combination so it won't clash with the user's own shortcuts.
        combo = dict(modifiers=hotkey.MOD_CONTROL | hotkey.MOD_ALT | 0x0004, key=0x7B)  # Ctrl+Alt+Shift+F12
        first = hotkey.GlobalHotkey(lambda: None, **combo)
        self.assertTrue(first.start())
        try:
            self.assertFalse(hotkey.GlobalHotkey(lambda: None, **combo).start())
        finally:
            first.stop()
        again = hotkey.GlobalHotkey(lambda: None, **combo)
        self.assertTrue(again.start())
        again.stop()


if __name__ == "__main__":
    unittest.main()
