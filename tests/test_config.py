"""Tests for atomic config writes and crash safety."""
import os
import sys
import json
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Keep test runs out of the real logs/youdownloader.log.
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

from src.utils.config import Config


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = Config(config_dir=self.dir)

    def test_set_writes_valid_json(self):
        self.cfg.set("download_path", "X")
        with open(self.cfg.config_file, encoding="utf-8") as f:
            json.load(f)  # raises if invalid

    def test_consent_default_is_none(self):
        self.assertIsNone(self.cfg.get("js_runtime_consent"))

    def test_default_theme_is_midnight(self):
        self.assertEqual(self.cfg.get("theme"), "midnight")

    def test_crash_during_rename_preserves_file(self):
        self.cfg.set("download_path", "GOOD")
        orig_replace = os.replace
        os.replace = lambda *a, **k: (_ for _ in ()).throw(OSError("boom"))
        try:
            self.cfg.set("download_path", "SHOULD_NOT_PERSIST")
        finally:
            os.replace = orig_replace
        with open(self.cfg.config_file, encoding="utf-8") as f:
            on_disk = json.load(f)
        self.assertEqual(on_disk.get("download_path"), "GOOD")
        # No temp files left behind.
        leftovers = [n for n in os.listdir(self.dir) if n.startswith(".settings-")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
