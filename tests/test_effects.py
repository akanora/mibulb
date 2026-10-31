import unittest
from unittest import mock

from mibulb import effects, miio
from mibulb.bulb import MAX_KELVIN, MIN_KELVIN, Bulb
from mibulb.miio import MiIOError
from test_miio import TOKEN, FakeBulb


class EffectListTest(unittest.TestCase):
    def test_every_step_is_valid_for_the_bulb(self):
        for effect in effects.EFFECTS:
            values = [int(v) for v in effect.expression().split(",")]
            self.assertEqual(len(values) % 4, 0, effect.id)
            for ms, mode, value, brightness in zip(*[iter(values)] * 4):
                self.assertGreaterEqual(ms, 50, effect.id)
                self.assertIn(mode, (effects.COLOR, effects.WHITE), effect.id)
                self.assertTrue(1 <= brightness <= 100, effect.id)
                if mode == effects.WHITE:
                    self.assertTrue(MIN_KELVIN <= value <= MAX_KELVIN, effect.id)
                else:
                    self.assertTrue(1 <= value <= 0xFFFFFF, effect.id)

    def test_ids_are_unique(self):
        self.assertEqual(len(effects.BY_ID), len(effects.EFFECTS))


class BulbFeaturesTest(unittest.TestCase):
    def make(self, yeelight):
        fake = FakeBulb(yeelight=yeelight)
        self.addCleanup(fake.close)
        patcher = mock.patch.object(miio, "PORT", fake.port)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake, Bulb("127.0.0.1", TOKEN)

    def test_effect_and_timer(self):
        fake, bulb = self.make(yeelight=True)
        bulb.start_effect(effects.BY_ID["rainbow"].expression())
        self.assertTrue(fake.props[1])  # turned on first
        self.assertEqual(fake.flow, effects.BY_ID["rainbow"].expression())
        bulb.stop_effect()
        self.assertIsNone(fake.flow)
        bulb.set_off_timer(45)
        self.assertEqual(bulb.off_timer_minutes(), 45)
        bulb.cancel_off_timer()
        self.assertIsNone(bulb.off_timer_minutes())

    def test_miot_bulbs_say_not_supported(self):
        _fake, bulb = self.make(yeelight=False)
        with self.assertRaises(MiIOError) as caught:
            bulb.start_effect("100,1,255,100")
        self.assertIn("doesn't support", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
