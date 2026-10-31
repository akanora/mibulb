"""Tests for start-with-Windows, the global shortcut, update checks and forgetting the bulb."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mibulb import config, hotkey, scenes, startup, updates
from mibulb.bulb import BulbState


class UpdatesTest(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updates.parse_version("v0.10.1"), (0, 10, 1))
        self.assertGreater(updates.parse_version("0.10.0"), updates.parse_version("0.9.9"))
        self.assertEqual(updates.parse_version("1.2.0-beta"), (1, 2, 0))

    def _check(self, tag, current, assets=()):
        response = mock.Mock()
        response.json.return_value = {"tag_name": tag, "html_url": "https://example/release", "assets": list(assets)}
        with mock.patch.object(updates.requests, "get", return_value=response):
            return updates.check(current)

    def test_newer_release(self):
        update = self._check("v0.5.0", "0.4.0", assets=[
            {"name": "MiBulb-Setup.exe", "browser_download_url": "https://dl/setup", "digest": "sha256:ABC"},
            {"name": "MiBulb-Portable.exe", "browser_download_url": "https://dl/portable"},
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://dl/sums"},
        ])
        self.assertEqual((update.version, update.url), ("0.5.0", "https://example/release"))
        self.assertEqual((update.installer_url, update.installer_sha256, update.sums_url),
                         ("https://dl/setup", "abc", "https://dl/sums"))

    def test_same_or_older_release(self):
        self.assertIsNone(self._check("v0.4.0", "0.4.0"))
        self.assertIsNone(self._check("v0.3.0", "0.4.0"))

    def test_installer_arguments(self):
        self.assertIn("/UPDATE", updates.installer_arguments(False))
        self.assertNotIn("RELAUNCH", updates.installer_arguments(False))
        self.assertIn("/RELAUNCH=--minimized", updates.installer_arguments(True))

    def test_not_installed_when_running_from_source(self):
        self.assertFalse(updates.is_installed())


class FakeDownload:
    def __init__(self, body, text=""):
        self.body, self.text = body, text
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        for i in range(0, len(self.body), 3):
            yield self.body[i:i + 3]


class DownloadTest(unittest.TestCase):
    BODY = b"pretend this is an installer"
    HASH = __import__("hashlib").sha256(BODY).hexdigest()

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def download(self, update, sums=""):
        def get(url, stream=False, timeout=None):
            return FakeDownload(self.BODY) if url == update.installer_url else FakeDownload(b"", sums)

        progress = []
        with mock.patch.object(updates.requests, "get", side_effect=get):
            path = updates.download(update, progress.append, folder=self.folder)
        return path, progress

    def test_verified_download(self):
        update = updates.Update("0.5.0", "u", installer_url="https://dl/setup", installer_sha256=self.HASH)
        path, progress = self.download(update)
        self.assertEqual(path.read_bytes(), self.BODY)
        self.assertEqual(path.name, "MiBulb-Setup-0.5.0.exe")
        self.assertEqual(progress[-1], 100)

    def test_hash_from_sha256sums(self):
        update = updates.Update("0.5.0", "u", installer_url="https://dl/setup", sums_url="https://dl/sums")
        sums = f"{self.HASH}  MiBulb-Setup.exe\n{'0' * 64}  MiBulb-Portable.exe\n"
        path, _ = self.download(update, sums=sums)
        self.assertTrue(path.exists())

    def test_mismatch_is_deleted(self):
        update = updates.Update("0.5.0", "u", installer_url="https://dl/setup", installer_sha256="0" * 64)
        with self.assertRaises(updates.UpdateError):
            self.download(update)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_no_checksum_refuses(self):
        update = updates.Update("0.5.0", "u", installer_url="https://dl/setup")
        with self.assertRaises(updates.UpdateError):
            self.download(update)


class ForgetBulbTest(unittest.TestCase):
    def test_keeps_preferences_only(self):
        cfg = config.Config(bulbs=[config.BulbInfo("a", "Desk", "1.2.3.4", "a" * 32, "5")], selected="a",
                            hotkey=False, check_updates=False)
        forgotten = config.forget_bulbs(cfg)
        self.assertEqual((forgotten.bulbs, forgotten.selected), ([], ""))
        self.assertEqual(len(cfg.bulbs), 1)  # the original is untouched
        self.assertFalse(forgotten.hotkey)
        self.assertFalse(forgotten.check_updates)
        self.assertFalse(forgotten.is_complete)

    def test_preferences_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "config.json"
        config.save(config.Config(bulbs=[config.BulbInfo("a", ip="1.2.3.4", token="a" * 32)], hotkey=False), path)
        loaded = config.load(path)
        self.assertFalse(loaded.hotkey)
        self.assertTrue(loaded.check_updates)


class ScenesTest(unittest.TestCase):
    def test_defaults_and_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "config.json"
        cfg = config.Config()
        self.assertEqual([s.name for s in cfg.scenes], ["Reading", "Relax", "Movie", "Gaming", "Night light"])
        cfg.scenes.append(scenes.Scene.from_state("Desk", BulbState(True, 70, 5000, 0xFF0000, 1)))
        cfg.scenes = [s for s in cfg.scenes if s.id != "movie"]
        cfg.shortcuts[f"scene:{cfg.scenes[-1].id}"] = "Ctrl+Alt+F1"
        config.save(cfg, path)
        loaded = config.load(path)
        self.assertEqual([s.name for s in loaded.scenes], ["Reading", "Relax", "Gaming", "Night light", "Desk"])
        desk = loaded.scenes[-1]
        self.assertEqual((desk.mode, desk.color, desk.brightness), ("color", 0xFF0000, 70))
        self.assertEqual(loaded.shortcuts[f"scene:{desk.id}"], "Ctrl+Alt+F1")

    def test_all_deleted_stays_empty(self):
        path = Path(tempfile.mkdtemp()) / "config.json"
        config.save(config.Config(scenes=[]), path)
        self.assertEqual(config.load(path).scenes, [])

    def test_bad_values_are_clamped(self):
        scene = scenes.Scene.from_dict({"name": "X", "brightness": 500, "kelvin": 99999, "mode": "weird"})
        self.assertEqual((scene.brightness, scene.kelvin, scene.mode), (100, 6500, "white"))
        self.assertTrue(scene.id)

    def test_swatch(self):
        self.assertEqual(scenes.Scene("a", "A", 50, "color", color=0x123456).swatch, "#123456")
        warm, cool = scenes.kelvin_to_hex(2000), scenes.kelvin_to_hex(6500)
        self.assertGreater(int(warm[1:3], 16), int(warm[5:7], 16))  # warm is more red than blue
        self.assertGreaterEqual(int(cool[5:7], 16), int(warm[5:7], 16))


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
        cfg = config.Config(bulbs=[config.BulbInfo("a", ip="1.2.3.4", token="a" * 32)])
        cfg.shortcuts["on"] = "Ctrl+Alt+O"
        self.assertEqual(config.forget_bulbs(cfg).shortcuts["on"], "Ctrl+Alt+O")


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
