"""Settings survive crashes and damaged files, and tokens are encrypted on disk."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from mibulb import config, secret

TOKEN = "0123456789abcdef0123456789abcdef"


def sample():
    return config.Config(bulbs=[config.BulbInfo("a", "Desk", "10.0.0.5", TOKEN, "42")], hotkey=False)


class SafeSaveTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "config.json"

    def test_save_leaves_no_temp_file_and_keeps_backup(self):
        config.save(sample(), self.path)
        cfg = sample()
        cfg.hotkey = True
        config.save(cfg, self.path)
        files = sorted(p.name for p in self.path.parent.iterdir())
        self.assertEqual(files, ["config.json", "config.json.bak"])
        self.assertTrue(config.load(self.path).hotkey)
        self.assertFalse(json.loads((self.path.parent / "config.json.bak").read_text())["hotkey"])

    def test_damaged_file_restores_backup(self):
        config.save(sample(), self.path)
        config.save(sample(), self.path)  # now there is a good backup
        self.path.write_text('{"bulbs": [ {"id": "a", "ip": "1.2.')  # cut off mid-write
        cfg = config.load(self.path)
        self.assertEqual([b.name for b in cfg.bulbs], ["Desk"])
        self.assertEqual(cfg.bulbs[0].token, TOKEN)
        self.assertIn("restored", config.load_problems[0])
        self.assertTrue(any(p.name.startswith("config.broken-") for p in self.path.parent.iterdir()))

    def test_damaged_file_without_backup_starts_fresh(self):
        self.path.write_text("not json at all")
        cfg = config.load(self.path)
        self.assertEqual(cfg.bulbs, [])
        self.assertIn("started fresh", config.load_problems[0])

    def test_wrong_shape_is_handled(self):
        self.path.write_text('{"bulbs": 5, "scenes": "x"}')
        cfg = config.load(self.path)
        self.assertIsInstance(cfg, config.Config)
        self.assertTrue(config.load_problems)

    def test_good_file_reports_nothing(self):
        config.save(sample(), self.path)
        config.load(self.path)
        self.assertEqual(config.load_problems, [])


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class EncryptedTokenTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "config.json"

    def test_token_is_not_stored_in_plain_text(self):
        config.save(sample(), self.path)
        text = self.path.read_text()
        self.assertNotIn(TOKEN, text)
        self.assertIn("token_protected", text)
        self.assertEqual(config.load(self.path).bulbs[0].token, TOKEN)

    def test_old_plain_token_still_loads_and_gets_encrypted(self):
        self.path.write_text(json.dumps({"bulbs": [{"id": "a", "name": "Desk", "ip": "1.2.3.4", "token": TOKEN}]}))
        cfg = config.load(self.path)
        self.assertEqual(cfg.bulbs[0].token, TOKEN)
        config.save(cfg, self.path)
        self.assertNotIn(TOKEN, self.path.read_text())

    def test_token_from_another_account(self):
        data = {"bulbs": [{"id": "a", "name": "Desk", "ip": "1.2.3.4", "token_protected": "AQAAAAAAbm90IG91cnM="}]}
        self.path.write_text(json.dumps(data))
        cfg = config.load(self.path)
        self.assertEqual(cfg.bulbs[0].token, "")
        self.assertIn("Sign in with Xiaomi again", config.load_problems[0])

    def test_round_trip(self):
        self.assertEqual(secret.unprotect(secret.protect(TOKEN)), TOKEN)


if __name__ == "__main__":
    unittest.main()
