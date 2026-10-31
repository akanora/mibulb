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


class ShortcutParsingTest(unittest.TestCase):
    def test_round_trip(self):
        for text in ("Ctrl+Alt+L", "Ctrl+Alt+PageUp", "Shift+Win+F5", "Alt+Num7", "F13"):
            self.assertEqual(hotkey.format_shortcut(*hotkey.parse(text)), text)

    def test_case_and_spacing(self):
        self.assertEqual(hotkey.parse(" ctrl + alt + l "), (hotkey.MOD_CONTROL | hotkey.MOD_ALT, ord("L")))

    def test_rejects_plain_keys_and_unknowns(self):
        for text in ("L", "Shift+L", "Ctrl+Alt+Enter", "Hyper+L", ""):
            with self.assertRaises(hotkey.ShortcutError, msg=text):
                hotkey.parse(text)

    def test_defaults_are_valid_and_unique(self):
        used = [s for s in config.DEFAULT_SHORTCUTS.values() if s]
        self.assertEqual(len(used), len(set(used)))
        for text in used:
            hotkey.parse(text)


class ShortcutConfigTest(unittest.TestCase):
    def test_defaults_merge_with_saved(self):
        path = Path(tempfile.mkdtemp()) / "config.json"
        path.write_text('{"shortcuts": {"toggle": "Ctrl+Alt+T", "dimmer": "", "bogus": "Ctrl+Alt+B"}}')
        shortcuts = config.load(path).shortcuts
        self.assertEqual(shortcuts["toggle"], "Ctrl+Alt+T")
        self.assertEqual(shortcuts["dimmer"], "")  # cleared on purpose stays cleared
        self.assertEqual(shortcuts["brighter"], "Ctrl+Alt+PageUp")  # default filled in
        self.assertNotIn("bogus", shortcuts)

    def test_forget_bulb_keeps_shortcuts(self):
        cfg = config.Config(ip="1.2.3.4", token="a" * 32)
        cfg.shortcuts["on"] = "Ctrl+Alt+O"
        self.assertEqual(config.forget_bulb(cfg).shortcuts["on"], "Ctrl+Alt+O")


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class HotkeyManagerTest(unittest.TestCase):
    # Unusual combinations so they won't clash with the user's own shortcuts.
    A = "Ctrl+Alt+Shift+F11"
    B = "Ctrl+Alt+Shift+F12"

    def test_register_conflict_and_bad_entries(self):
        first = hotkey.HotkeyManager(lambda action: None)
        self.assertEqual(first.apply({"one": self.A, "two": self.B, "none": ""}), {})
        try:
            second = hotkey.HotkeyManager(lambda action: None)
            problems = second.apply({"one": self.A, "bad": "Q"})
            self.assertEqual(set(problems), {"one", "bad"})
            second.stop()
        finally:
            first.stop()
        again = hotkey.HotkeyManager(lambda action: None)
        self.assertEqual(again.apply({"one": self.A}), {})
        again.stop()

    def test_reapply_releases_old_shortcuts(self):
        manager = hotkey.HotkeyManager(lambda action: None)
        manager.apply({"one": self.A})
        manager.apply({"one": self.B})
        other = hotkey.HotkeyManager(lambda action: None)
        self.assertEqual(other.apply({"x": self.A}), {})
        other.stop()
        manager.stop()


if __name__ == "__main__":
    unittest.main()
