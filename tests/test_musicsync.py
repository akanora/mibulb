import array
import math
import unittest

from mibulb import musicsync
from mibulb.gui.picker import pixel_for


def tone(loudness, frames=1024):
    """A 440 Hz stereo tone at a loudness between 0 and 1."""
    samples = []
    for i in range(frames):
        value = int(loudness * 30000 * math.sin(2 * math.pi * 440 * i / 48000))
        samples += [value, value]
    return array.array("h", samples)


class AnalyzerTest(unittest.TestCase):
    def test_silence(self):
        analyzer = musicsync.MusicAnalyzer()
        for step in range(50):
            analyzer.feed(tone(0), step * 0.02)
        self.assertTrue(analyzer.silent)
        self.assertEqual(analyzer.beats, 0)

    def test_loudness_sets_brightness(self):
        quiet, loud = musicsync.MusicAnalyzer(), musicsync.MusicAnalyzer()
        for step in range(100):
            quiet.feed(tone(0.6 if step < 50 else 0.1), step * 0.02)
            loud.feed(tone(0.6), step * 0.02)
        self.assertLess(quiet.color()[1], loud.color()[1])

    def test_beats_move_the_colour(self):
        analyzer = musicsync.MusicAnalyzer()
        hues = []
        for step in range(200):
            beat = step % 25 == 0  # a kick drum twice a second
            analyzer.feed(tone(0.9 if beat else 0.15), step * 0.02)
            hues.append(round(analyzer.hue, 2))
        self.assertGreaterEqual(analyzer.beats, 6)
        self.assertGreater(len(set(hues)), 5)

    def test_publish_only_sends_noticeable_changes(self):
        sent = []
        sync = musicsync.MusicSync(lambda rgb, b: sent.append((rgb, b)))
        for step in range(30):
            sync.analyzer.feed(tone(0.5), step * 0.02)
        self.assertTrue(sync.publish())
        self.assertFalse(sync.publish())  # nothing changed
        self.assertEqual(len(sent), 1)


class PickerMappingTest(unittest.TestCase):
    def test_no_scaling(self):
        self.assertEqual(pixel_for(100, 50, (1920, 1080), (1920, 1080)), (100, 50))

    def test_display_scaling(self):
        # At 150% scaling the window is 1280x720 "points" but the screenshot is 1920x1080 pixels.
        self.assertEqual(pixel_for(640, 360, (1280, 720), (1920, 1080)), (960, 540))

    def test_edges_stay_inside(self):
        self.assertEqual(pixel_for(5000, -3, (1920, 1080), (1920, 1080)), (1919, 0))


if __name__ == "__main__":
    unittest.main()
