"""Tests for URL/path/disk validators (the security-critical Step 1 fixes)."""
import os
import sys
import tempfile
import unittest
# Keep test runs out of the real logs/youdownloader.log.
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.validators import validate_youtube_url, validate_path, check_disk_space


class TestYouTubeURLValidation(unittest.TestCase):
    def test_accepts_canonical_forms(self):
        for url in [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "youtube.com/watch?v=dQw4w9WgXcQ",            # scheme-less
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/abc123",
            "https://www.youtube.com/embed/abc123",
            "https://www.youtube.com/playlist?list=PL123",
            "https://www.youtube.com/watch?v=abc&list=PL123&t=10s",
            "https://m.youtube.com/watch?v=abc123",
        ]:
            ok, _ = validate_youtube_url(url)
            self.assertTrue(ok, f"should accept {url}")

    def test_rejects_injection_and_other_hosts(self):
        for url in [
            "http://evil.com/?youtube.com/watch?v=X",   # old re.search accepted this
            "file:///etc/passwd",
            "javascript:alert(1)//youtube.com/watch?v=x",
            "https://notyoutube.com/watch?v=x",
            "https://youtube.com.evil.com/watch?v=x",
            "",
            "   ",
        ]:
            ok, _ = validate_youtube_url(url)
            self.assertFalse(ok, f"should reject {url!r}")


class TestPathValidation(unittest.TestCase):
    def test_expands_home(self):
        ok, _ = validate_path("~")
        self.assertTrue(ok)

    def test_accepts_temp_dir(self):
        ok, _ = validate_path(tempfile.gettempdir())
        self.assertTrue(ok)

    def test_rejects_missing(self):
        ok, _ = validate_path(os.path.join(tempfile.gettempdir(), "nope_xyz_123"))
        self.assertFalse(ok)

    def test_rejects_empty(self):
        ok, _ = validate_path("   ")
        self.assertFalse(ok)


class TestDiskSpace(unittest.TestCase):
    def test_real_path_ok(self):
        ok, _ = check_disk_space(tempfile.gettempdir(), 0)
        self.assertTrue(ok)

    def test_impossible_requirement_flagged(self):
        # Cross-platform check actually runs now (was a no-op on Windows).
        ok, msg = check_disk_space(tempfile.gettempdir(), 10 ** 18)
        self.assertFalse(ok)
        self.assertTrue(msg)


if __name__ == "__main__":
    unittest.main()
