import unittest
from unittest import mock

from PIL import Image, ImageDraw

from mibulb import miio, screensync
from mibulb.bulb import Bulb
from test_miio import TOKEN, FakeBulb


def screen(background, patches=()):
    image = Image.new("RGB", (1920, 1080), background)
    draw = ImageDraw.Draw(image)
    for box, color in patches:
        draw.rectangle(box, fill=color)
    return image


def hue_of(rgb):
    import colorsys

    return colorsys.rgb_to_hsv((rgb >> 16) / 255, ((rgb >> 8) & 255) / 255, (rgb & 255) / 255)[0]


class DominantColorTest(unittest.TestCase):
    def test_solid_colour(self):
        rgb, brightness = screensync.dominant_color(screen((200, 30, 30)))
        self.assertGreater(rgb >> 16, 200)  # strongly red
        self.assertLess((rgb >> 8) & 255, 60)
        self.assertGreater(brightness, 20)

    def test_colourful_area_beats_grey_ui(self):
        # A dark grey game UI with a blue sky in the top third
        rgb, _ = screensync.dominant_color(screen((40, 40, 45), [((0, 0, 1919, 360), (40, 120, 230))]))
        self.assertAlmostEqual(hue_of(rgb), hue_of(0x2878E6), delta=0.05)

    def test_grey_screen_gives_white(self):
        rgb, _ = screensync.dominant_color(screen((128, 128, 128)))
        self.assertEqual(rgb, 0xFFFFFF)

    def test_black_frame_is_ignored(self):
        self.assertIsNone(screensync.dominant_color(screen((0, 0, 0))))

    def test_brighter_screen_brighter_light(self):
        _, dim = screensync.dominant_color(screen((30, 10, 10)))
        _, bright = screensync.dominant_color(screen((250, 90, 90)))
        self.assertLess(dim, bright)


class SyncLoopTest(unittest.TestCase):
    def run_frames(self, frames, match_brightness=True):
        sent = []
        sync = screensync.ScreenSync(lambda rgb, b: sent.append((rgb, b)), match_brightness=match_brightness,
                                     grab=iter(frames).__next__)
        for _ in frames:
            sync.step()
        return sent

    def test_only_noticeable_changes_are_sent(self):
        red, red2, blue = screen((200, 30, 30)), screen((198, 31, 30)), screen((30, 30, 200))
        sent = self.run_frames([red, red2, red, blue])
        self.assertEqual(len(sent), 2)  # first red, then blue
        self.assertIsNotNone(sent[0][1])  # first update includes brightness

    def test_black_frames_keep_last_colour(self):
        sent = self.run_frames([screen((200, 30, 30)), screen((0, 0, 0)), screen((0, 0, 0))])
        self.assertEqual(len(sent), 1)

    def test_without_brightness(self):
        sent = self.run_frames([screen((200, 30, 30)), screen((60, 9, 9))], match_brightness=False)
        self.assertTrue(all(b is None for _rgb, b in sent))

    def test_capture_errors_are_skipped(self):
        def broken():
            raise OSError("screen locked")

        sync = screensync.ScreenSync(lambda *a: self.fail("nothing should be sent"), grab=broken)
        self.assertFalse(sync.step())

    def test_thread_starts_and_stops(self):
        sent = []
        sync = screensync.ScreenSync(lambda rgb, b: sent.append(rgb), grab=lambda: screen((200, 30, 30)),
                                     interval=0.01)
        sync.start()
        self.assertTrue(sync.running)
        import time
        time.sleep(0.2)
        sync.stop()
        self.assertFalse(sync.running)
        self.assertEqual(len(sent), 1)  # same colour every frame: sent once


class BulbSyncCommandTest(unittest.TestCase):
    def check(self, yeelight):
        fake = FakeBulb(yeelight=yeelight)
        self.addCleanup(fake.close)
        with mock.patch.object(miio, "PORT", fake.port):
            bulb = Bulb("127.0.0.1", TOKEN)
            bulb.sync_color(0x3366FF, 55, screensync.FADE_MS)
            self.assertEqual((fake.props[4], fake.props[2]), (0x3366FF, 55))
            bulb.sync_color(0xFF0000, None, screensync.FADE_MS)
            self.assertEqual((fake.props[4], fake.props[2]), (0xFF0000, 55))

    def test_yeelight(self):
        self.check(True)

    def test_miot(self):
        self.check(False)


if __name__ == "__main__":
    unittest.main()
