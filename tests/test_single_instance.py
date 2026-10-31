import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from mibulb import single_instance


class SingleInstanceTest(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        patcher = mock.patch.object(single_instance, "_port_file", lambda: folder / "instance.port")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.port_file = folder / "instance.port"

    def test_no_instance(self):
        self.assertFalse(single_instance.notify_existing())

    def test_second_launch_shows_first(self):
        shown = threading.Event()
        server = single_instance.InstanceServer(shown.set)
        self.addCleanup(server.close)
        self.assertTrue(single_instance.notify_existing())
        self.assertTrue(shown.wait(2))

    def test_minimized_launch_does_not_show(self):
        shown = threading.Event()
        server = single_instance.InstanceServer(shown.set)
        self.addCleanup(server.close)
        self.assertTrue(single_instance.notify_existing(show=False))
        self.assertFalse(shown.wait(0.3))

    def test_stale_port_file(self):
        server = single_instance.InstanceServer(lambda: None)
        port = self.port_file.read_text()
        server.close()
        self.assertFalse(self.port_file.exists())
        self.port_file.write_text(port)  # left behind by a crash
        self.assertFalse(single_instance.notify_existing())


if __name__ == "__main__":
    unittest.main()
