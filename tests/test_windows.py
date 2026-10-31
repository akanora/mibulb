"""The windows, driven like a user would, with hidden windows and simulated bulbs.

Nothing is shown on screen: windows are withdrawn, the tray icon isn't started
and the Windows-wide shortcuts are off.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from mibulb import api, automation, config, effects, i18n, miio, screensync
from mibulb import gui
from mibulb.gui import app as app_module
from mibulb.gui import settings as settings_module
from test_miio import TOKEN, FakeBulb


class WindowTest(unittest.TestCase):
    bulbs = 1

    def setUp(self):
        self.fakes = [FakeBulb(yeelight=True) for _ in range(self.bulbs)]
        for fake in self.fakes:
            self.addCleanup(fake.close)
        ports = {f"10.0.0.{i + 1}": fake.port for i, fake in enumerate(self.fakes)}
        original_send = miio.Device.send

        def send(device, method, params=None):
            real_ip = device.ip
            device.port = ports.get(real_ip, 1)
            device.ip = "127.0.0.1"
            try:
                return original_send(device, method, params)
            finally:
                device.ip = real_ip

        for patcher in (mock.patch.object(miio.Device, "send", send),
                        mock.patch.object(app_module, "pystray", None),  # no tray icon in tests
                        mock.patch.object(gui.QuickPanel, "_place", lambda panel: panel.withdraw()),
                        mock.patch.object(gui.QuickPanel, "focus_force", lambda panel: None)):
            patcher.start()
            self.addCleanup(patcher.stop)

        folder = tempfile.mkdtemp()
        self.config_path = os.path.join(folder, "config.json")
        data = {
            "bulbs": [{"id": f"b{i}", "name": name, "ip": f"10.0.0.{i + 1}", "token": TOKEN}
                      for i, name in enumerate(["Desk", "Bed"][:self.bulbs])],
            "hotkey": False, "check_updates": False, "language": "en",
        }
        data.update(self.extra_config())
        json.dump(data, open(self.config_path, "w"))
        env = mock.patch.dict(os.environ, {"MIBULB_CONFIG": self.config_path})
        env.start()
        self.addCleanup(env.stop)

        self.app = gui.App()
        self.app.withdraw()
        self.addCleanup(self._close)
        self.pump(0.8)

    def extra_config(self):
        return {}

    def _close(self):
        if self.app.winfo_exists():
            self.app.quit_app()
        i18n.set_language("en")

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.app.update()
            time.sleep(0.02)

    @property
    def desk(self):
        return self.fakes[0].props


class MainWindowTest(WindowTest):
    def test_connects_and_controls_the_bulb(self):
        self.assertIn("Connected", self.app.status_label.cget("text"))
        self.desk[1] = False
        self.app.toggle()
        self.pump(0.8)
        self.assertTrue(self.desk[1])
        self.app._on_brightness(33)
        self.app._set_kelvin(2700)
        self.pump(0.8)
        self.assertEqual((self.desk[2], self.desk[3]), (33, 2700))
        self.app._set_color("#ff0000")
        self.pump(0.8)
        self.assertEqual((self.desk[4], self.desk[5]), (0xFF0000, 1))

    def test_scenes(self):
        gaming = next(s for s in self.app.cfg.scenes if s.name == "Gaming")
        self.app.apply_scene(gaming)
        self.pump(1)
        self.assertEqual((self.desk[2], self.desk[4]), (60, gaming.color))

        self.desk.update({2: 55, 3: 5000, 5: 2})
        with mock.patch.object(app_module.simpledialog, "askstring", return_value="Desk work"):
            self.app.save_current_scene()
            self.pump(1)
        saved = self.app.cfg.scenes[-1]
        self.assertEqual((saved.name, saved.brightness, saved.kelvin, saved.mode), ("Desk work", 55, 5000, "white"))
        self.app.cfg.shortcuts[f"scene:{saved.id}"] = "Ctrl+Alt+Shift+F9"
        with mock.patch.object(app_module.messagebox, "askyesno", return_value=True):
            self.app._delete_scene(saved)
        stored = config.load()
        self.assertNotIn("Desk work", [s.name for s in stored.scenes])
        self.assertNotIn(f"scene:{saved.id}", stored.shortcuts)

    def test_sleep_timer_fades_then_turns_off_and_manual_change_cancels(self):
        with mock.patch.object(automation, "MIN_STEP_SECONDS", 0.3):
            self.desk.update({1: True, 2: 80})
            self.app.refresh()
            self.pump(0.5)
            self.app.start_sleep_timer(0.04)
            self.pump(3.5)
            self.assertFalse(self.desk[1])
            self.assertIsNone(self.app._program)

            self.desk.update({1: True, 2: 80})
            self.app.start_sleep_timer(0.04)
            self.pump(0.4)
            self.app._on_brightness(50)
            self.pump(1.5)
            self.assertIsNone(self.app._program)
            self.assertTrue(self.desk[1])

    def test_effects(self):
        self.app.start_effect("candle")
        self.pump(0.8)
        fake = self.fakes[0]
        self.assertEqual(fake.flow, effects.BY_ID["candle"].expression())
        self.assertIn("Candle", self.app.program_label.cget("text"))
        self.app.run_shortcut("effect:candle")  # the same effect's shortcut again stops it
        self.pump(0.8)
        self.assertIsNone(fake.flow)
        self.app.start_effect("party")
        self.pump(0.5)
        self.app._on_brightness(40)  # taking over stops it
        self.pump(0.8)
        self.assertIsNone(fake.flow)
        self.assertIsNone(self.app._effect)

    def test_sleep_timer_also_sets_the_bulbs_own_timer(self):
        self.app.start_sleep_timer(30)
        self.pump(0.8)
        self.assertEqual(self.fakes[0].off_timer, 30)
        self.app.cancel_program()
        self.pump(0.8)
        self.assertIsNone(self.fakes[0].off_timer)

    def test_quick_panel(self):
        self.desk.update({1: True, 2: 35})
        self.app.refresh()
        self.pump(0.5)
        self.app._tray_click()
        self.pump(0.5)
        panel = self.app.quick_panel
        self.assertEqual(round(panel.brightness.get()), 35)
        panel.brightness.set(70)
        self.pump(0.8)
        self.assertEqual(self.desk[2], 70)
        self.app._tray_click()
        self.pump(0.2)
        self.assertIsNone(self.app.quick_panel)

    def test_screen_sync(self):
        frames = {"now": Image.new("RGB", (640, 360), (200, 30, 30))}
        with mock.patch.object(screensync, "grab_screen", lambda: frames["now"]):
            self.app.toggle_screen_sync()
            self.pump(1.2)
            self.assertEqual(self.desk[4] >> 16, 0xFF)  # red
            frames["now"] = Image.new("RGB", (640, 360), (20, 60, 220))
            self.pump(1.2)
            self.assertEqual(self.desk[4] & 0xFF, 0xFF)  # blue
            self.app._on_brightness(80)  # taking over stops it
            self.pump(0.5)
            self.assertIsNone(self.app.screen_sync)

    def test_music_sync(self):
        class FakeMusic:
            def __init__(self, send):
                self.send, self.running, self.error = send, True, None

            def start(self):
                self.send(0x00FF40, 70)  # what the analyzer would send on a beat

            def stop(self):
                self.running = False

        with mock.patch.object(app_module.musicsync, "MusicSync", FakeMusic),                 mock.patch.object(app_module.musicsync, "available", return_value=True):
            self.app.toggle_music_sync()
            self.pump(1)
            self.assertEqual((self.desk[4], self.desk[2]), (0x00FF40, 70))
            self.assertIn("Music sync", self.app.program_label.cget("text"))
            self.app._set_kelvin(4000)  # taking over stops it
            self.pump(0.5)
            self.assertIsNone(self.app.music_sync)

    def test_pick_colour_from_screen(self):
        picked = {}

        def fake_picker(master, on_pick, on_cancel):
            picked["called"] = True
            on_pick("#12ab34")

        with mock.patch("mibulb.gui.picker.ScreenColorPicker", fake_picker):
            self.app.pick_from_screen()
            self.pump(1.2)
        self.assertTrue(picked["called"])
        self.assertEqual(self.desk[4], 0x12AB34)

    def test_follow_the_pc(self):
        self.app.cfg.lock_off = self.app.cfg.unlock_on = True
        self.desk[1] = True
        self.app.refresh()
        self.pump(0.5)
        self.app._on_pc_event("lock")
        self.pump(0.6)
        self.assertFalse(self.desk[1])
        self.app._on_pc_event("unlock")
        self.pump(0.6)
        self.assertTrue(self.desk[1])


class SettingsWindowTest(WindowTest):
    def open(self, tab="bulb"):
        dialog = gui.SettingsDialog(self.app, self.app.cfg, self.app._ui_calls.put, tab=tab)
        dialog.withdraw()
        self.addCleanup(lambda: dialog.winfo_exists() and dialog.destroy())
        return dialog

    def test_add_and_remove_a_bulb(self):
        dialog = self.open()
        dialog._new_bulb()
        dialog.name_var.set("Hall")
        dialog.ip_var.set("10.0.0.9")
        dialog.token_var.set(TOKEN)
        dialog._save()
        self.assertEqual([b.name for b in config.load().bulbs], ["Desk", "Hall"])
        dialog.bulb_list.selection_clear(0, "end")
        dialog.bulb_list.selection_set(1)
        with mock.patch.object(settings_module.messagebox, "askyesno", return_value=True):
            dialog._remove_bulb()
        self.assertEqual([b.name for b in config.load().bulbs], ["Desk"])

    def test_record_a_shortcut(self):
        dialog = self.open("shortcuts")
        dialog._start_capture("on")
        with mock.patch.object(settings_module.hotkey, "pressed_modifiers", return_value=0x2 | 0x1 | 0x4):
            dialog._capture_key(SimpleNamespace(keycode=ord("O")))
        self.assertEqual(config.load().shortcuts["on"], "Ctrl+Alt+Shift+O")

    def test_add_a_schedule(self):
        dialog = self.open("automation")
        editor = gui.ScheduleDialog(dialog, self.app, None)
        editor.withdraw()
        editor.hour.set("6")
        editor.minute.set("45")
        editor._pick_days(automation.WEEKDAYS)
        editor.action.current(3)  # sunrise, 15 min
        editor._save()
        self.assertEqual((editor.result.time, editor.result.days, editor.result.action),
                         ("06:45", automation.WEEKDAYS, "sunrise:15"))

    def test_dropdowns_are_readable(self):
        style = gui.app.ttk.Style(self.app)
        self.assertEqual(style.lookup("TCombobox", "fieldbackground", ["readonly"]), gui.PANEL)
        self.assertEqual(style.lookup("TCombobox", "foreground", ["readonly"]), gui.TEXT)


class TwoBulbsTest(WindowTest):
    bulbs = 2

    def extra_config(self):
        return {"selected": config.ALL}

    def test_all_lights_and_one_light(self):
        self.assertEqual(self.app.title_label.cget("text"), "All lights ▾")
        self.app._on_brightness(25)
        self.pump(0.8)
        self.assertEqual([f.props[2] for f in self.fakes], [25, 25])
        self.app.select_bulb("b1")
        self.pump(0.5)
        self.app._on_brightness(75)
        self.pump(0.8)
        self.assertEqual([f.props[2] for f in self.fakes], [25, 75])


class ApiAndExportTest(WindowTest):
    bulbs = 2

    def test_api_commands_reach_the_lights(self):
        call = self.app._api_command
        call("light", {"name": "Bed"})
        self.pump(0.5)
        call("on", {})
        call("brightness", {"value": "35"})
        self.pump(1)
        self.assertEqual((self.fakes[1].props[1], self.fakes[1].props[2]), (True, 35))
        call("light", {"name": "all"})
        self.pump(0.5)
        call("scene", {"name": "relax"})
        self.pump(1)
        self.assertEqual([f.props[3] for f in self.fakes], [2700, 2700])
        self.assertEqual(call("status", {})["light"], "All lights")
        for bad in (("brightness", {"value": "500"}), ("color", {"hex": "zz"}), ("scene", {"name": "nope"})):
            with self.assertRaises(api.ApiError):
                call(*bad)

    def test_api_server_starts_from_settings(self):
        self.app.cfg.api_enabled, self.app.cfg.api_port = True, 0
        self.app.apply_api()
        self.assertIsNotNone(self.app.api_server)
        self.assertTrue(self.app.cfg.api_key)  # a key is made the first time
        self.app.cfg.api_enabled = False
        self.app.apply_api()
        self.assertIsNone(self.app.api_server)

    def test_export_and_import(self):
        path = os.path.join(tempfile.mkdtemp(), "export.json")
        config.export(self.app.cfg, Path(path))
        exported = json.load(open(path))
        self.assertEqual(exported["bulbs"][0]["token"], TOKEN)  # readable, to work on another PC
        exported["bulbs"] = exported["bulbs"][:1]
        json.dump(exported, open(path, "w"))
        self.app.import_settings(config.load(Path(path)))
        self.pump(0.5)
        self.assertEqual([b.name for b in config.load().bulbs], ["Desk"])


class TwoBulbAutomationTest(WindowTest):
    bulbs = 2

    def test_schedule_for_one_bulb(self):
        for fake in self.fakes:
            fake.props[1] = False
        self.app.run_schedule_action("on", "b1")  # only Bed
        self.pump(1)
        self.assertEqual([f.props[1] for f in self.fakes], [False, True])
        self.app.run_schedule_action("off", config.ALL)
        self.pump(1)
        self.assertEqual([f.props[1] for f in self.fakes], [False, False])

    def test_evening_warmth(self):
        self.app.cfg.warmth = True
        self.app.cfg.warmth_start, self.app.cfg.warmth_end, self.app.cfg.warmth_kelvin = "00:00", "00:01", 2700
        self.desk.update({1: True, 3: 6000, 5: 2})
        self.app.refresh()
        self.pump(0.6)
        with mock.patch.object(app_module, "datetime", mock.Mock(wraps=app_module.datetime)) as clock:
            clock.now.return_value = app_module.datetime(2026, 11, 2, 23, 0)
            with mock.patch.object(automation, "warmth_kelvin", return_value=2700):
                self.app._warmth_tick()
                self.pump(0.8)
                self.assertEqual(self.desk[3], 2700)
                self.app._set_kelvin(5000)  # you choose a white yourself
                self.pump(0.8)
                self.app._warmth_tick()
                self.pump(0.8)
                self.assertEqual(self.desk[3], 5000)  # left alone for the rest of the evening


class TurkishTest(WindowTest):
    def extra_config(self):
        return {"language": "tr"}

    def test_windows_are_in_turkish(self):
        texts = []

        def collect(widget):
            try:
                value = widget.cget("text")
                if isinstance(value, str) and value.strip():
                    texts.append(value)
            except Exception:
                pass
            for child in widget.winfo_children():
                collect(child)

        collect(self.app)
        dialog = gui.SettingsDialog(self.app, self.app.cfg, self.app._ui_calls.put)
        dialog.withdraw()
        collect(dialog)
        dialog.destroy()
        untranslated = [text for text in texts if text in i18n.TURKISH]
        self.assertEqual(untranslated, [])
        self.assertIn("Parlaklık", texts)
        self.assertIn("Sahneler", texts)


if __name__ == "__main__":
    unittest.main()
