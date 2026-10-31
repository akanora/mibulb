"""Music sync: the light reacts to whatever your PC is playing.

It listens to the sound going to your speakers or headphones (Windows
"loopback", so no microphone), measures how loud each short slice is, and:
- loudness sets the brightness,
- a beat (a slice much louder than the last moment) moves the colour along
  the rainbow, which otherwise drifts slowly.
Updates go out about 4 times a second, like screen sync.

Needs PyAudioWPatch (Windows loopback recording). Without it the feature is
simply unavailable.
"""

from __future__ import annotations

import array
import colorsys
import math
import threading
import time
from typing import Callable

from .screensync import FADE_MS, MIN_BRIGHTNESS_CHANGE, MIN_COLOR_CHANGE, color_distance

UPDATE_SECONDS = 0.25
CHUNK_FRAMES = 1024

__all__ = ["FADE_MS", "MusicAnalyzer", "MusicSync", "available"]


def available() -> bool:
    import importlib.util

    return importlib.util.find_spec("pyaudiowpatch") is not None


class MusicAnalyzer:
    """Turns slices of audio into a colour and brightness. No audio library needed, so it is easy to test."""

    BEAT_RATIO = 1.6  # a slice this much louder than the recent average counts as a beat
    MIN_BEAT_GAP = 0.25  # seconds
    SILENCE = 1e-6  # energy below this (as a fraction of full scale) is silence

    def __init__(self):
        self.average = 0.0
        self.peak = 1e-4
        self.level = 0.0
        self.hue = 0.0
        self.last_beat = -1.0
        self.beats = 0

    def feed(self, samples: array.array, now: float) -> None:
        """samples: signed 16-bit audio (channels interleaved)."""
        if not samples:
            return
        energy = sum(s * s for s in samples) / len(samples) / (32768.0 * 32768.0)
        if energy > self.SILENCE and energy > self.average * self.BEAT_RATIO and now - self.last_beat > self.MIN_BEAT_GAP:
            self.last_beat = now
            self.beats += 1
            self.hue = (self.hue + 0.18) % 1.0
        self.average = self.average * 0.95 + energy * 0.05
        self.peak = max(energy, self.peak * 0.995, 1e-4)
        target = math.sqrt(energy / self.peak) if energy > self.SILENCE else 0.0
        # Rise fast, fall slower, so the light pulses with the music instead of flickering.
        self.level = target if target > self.level else self.level * 0.85 + target * 0.15

    def drift(self, seconds: float) -> None:
        self.hue = (self.hue + 0.02 * seconds) % 1.0

    @property
    def silent(self) -> bool:
        return self.level < 0.02

    def color(self) -> tuple[int, int]:
        r, g, b = colorsys.hsv_to_rgb(self.hue, 1.0, 1.0)
        rgb = (round(r * 255) << 16) | (round(g * 255) << 8) | round(b * 255)
        return max(1, rgb), max(5, min(100, round(10 + self.level * 90)))


class MusicSync:
    """Calls send(rgb, brightness_or_None) as the music changes. Same contract as ScreenSync."""

    def __init__(self, send: Callable[[int, int | None], None]):
        self._send = send
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.analyzer = MusicAnalyzer()
        self.last: tuple[int, int] | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(2)
        self._thread = None

    def publish(self) -> bool:
        """Send the current colour if it changed noticeably. Returns True if something was sent."""
        if self.analyzer.silent:
            return False
        rgb, brightness = self.analyzer.color()
        if self.last is not None:
            last_rgb, last_brightness = self.last
            if color_distance(rgb, last_rgb) < MIN_COLOR_CHANGE and \
                    abs(brightness - last_brightness) < MIN_BRIGHTNESS_CHANGE:
                return False
        self.last = (rgb, brightness)
        self._send(rgb, brightness)
        return True

    def _run(self) -> None:
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            self.error = "Music sync needs the PyAudioWPatch package"
            return
        audio = pyaudio.PyAudio()
        stream = None
        try:
            device = audio.get_default_wasapi_loopback()
            stream = audio.open(format=pyaudio.paInt16, channels=device["maxInputChannels"],
                                rate=int(device["defaultSampleRate"]), input=True,
                                input_device_index=device["index"], frames_per_buffer=CHUNK_FRAMES)
            last_publish = last_drift = time.monotonic()
            while not self._stop.is_set():
                data = stream.read(CHUNK_FRAMES, exception_on_overflow=False)
                now = time.monotonic()
                self.analyzer.feed(array.array("h", data), now)
                if now - last_publish >= UPDATE_SECONDS:
                    self.analyzer.drift(now - last_drift)
                    last_drift = last_publish = now
                    self.publish()
        except Exception as exc:  # no audio device, device unplugged, ...
            self.error = f"Couldn't listen to the PC's sound: {exc}"
        finally:
            if stream is not None:
                stream.close()
            audio.terminate()
