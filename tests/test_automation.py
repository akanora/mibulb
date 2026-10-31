import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from mibulb import automation, config


class ScheduleTest(unittest.TestCase):
    def test_normalise_time(self):
        self.assertEqual(automation.normalise_time("7:5"), "07:05")
        self.assertEqual(automation.normalise_time("23.59"), "23:59")
        for bad in ("24:00", "12:60", "x"):
            with self.assertRaises(ValueError):
                automation.normalise_time(bad)

    def test_describe_days(self):
        self.assertEqual(automation.describe_days(list(range(7))), "Every day")
        self.assertEqual(automation.describe_days([4, 3, 2, 1, 0]), "Weekdays")
        self.assertEqual(automation.describe_days([5, 6]), "Weekends")
        self.assertEqual(automation.describe_days([0, 2]), "Mon, Wed")

    def test_due(self):
        schedule = automation.Schedule("a", "07:30", automation.WEEKDAYS, "on")
        monday = datetime(2026, 11, 2, 7, 30, 45)
        self.assertTrue(schedule.due(monday))
        self.assertFalse(schedule.due(monday.replace(minute=31)))
        self.assertFalse(schedule.due(datetime(2026, 11, 7, 7, 30)))  # Saturday
        schedule.enabled = False
        self.assertFalse(schedule.due(monday))

    def test_from_dict_cleans_up(self):
        schedule = automation.Schedule.from_dict({"time": "6:0", "days": [6, 6, 9, 0], "action": "sunrise:15"})
        self.assertEqual((schedule.time, schedule.days), ("06:00", [0, 6]))
        self.assertEqual(automation.sunrise_minutes(schedule.action), 15)
        self.assertIsNone(automation.sunrise_minutes("on"))

    def test_config_round_trip(self):
        path = Path(tempfile.mkdtemp()) / "config.json"
        cfg = config.Config(lock_off=True, unlock_on=True)
        cfg.schedules.append(automation.Schedule("s1", "22:30", [0, 1], "off"))
        config.save(cfg, path)
        loaded = config.load(path)
        self.assertEqual(loaded.schedules[0].to_dict(), cfg.schedules[0].to_dict())
        self.assertTrue(loaded.lock_off and loaded.unlock_on)


class FadeTest(unittest.TestCase):
    def test_sleep_timer(self):
        steps = automation.plan_sleep_timer(30, 80)
        self.assertEqual((steps[0].at, steps[0].brightness), (0, 80))
        self.assertEqual((steps[-1].at, steps[-1].brightness), (1800, 1))
        self.assertTrue(all(s.kelvin is None for s in steps))
        brightness = [s.brightness for s in steps]
        self.assertEqual(brightness, sorted(brightness, reverse=True))
        gaps = [b.at - a.at for a, b in zip(steps, steps[1:])]
        self.assertGreaterEqual(min(gaps), automation.MIN_STEP_SECONDS - 0.001)

    def test_sunrise(self):
        steps = automation.plan_sunrise(15)
        self.assertEqual((steps[0].brightness, steps[0].kelvin), automation.SUNRISE_START)
        self.assertEqual((steps[-1].brightness, steps[-1].kelvin), automation.SUNRISE_END)
        self.assertEqual(steps[-1].at, 900)
        self.assertLessEqual(len(steps), 900 // automation.MIN_STEP_SECONDS + 1)

    def test_already_dim_sleep_timer_still_ends(self):
        steps = automation.plan_sleep_timer(10, 1)
        self.assertEqual(steps[-1].at, 600)


if __name__ == "__main__":
    unittest.main()
