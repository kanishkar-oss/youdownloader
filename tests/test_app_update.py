"""Tests for the app self-updater's version logic and its no-API fallback."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

from src.utils import app_update as u  # noqa: E402


class _Resp:
    def __init__(self, status=200, text="", headers=None, data=None):
        self.status_code, self.text, self.headers, self._data = status, text, headers or {}, data
        self.ok = 200 <= status < 300

    def json(self):
        return self._data


class TestVersions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(u.parse_version("v5.1.10"), (5, 1, 10))
        self.assertEqual(u.parse_version("junk"), ())

    def test_is_newer(self):
        self.assertTrue(u.is_newer("5.1.2", "5.1.1"))
        self.assertTrue(u.is_newer("5.10.0", "5.9.9"))
        self.assertFalse(u.is_newer("5.1", "5.1.0"))
        self.assertFalse(u.is_newer("5.0.9", "5.1.0"))


class TestSums(unittest.TestCase):
    SUMS = ("a" * 64 + "  YouDownloader-5.2.0-windows-setup.exe\n"
            + "B" * 64 + " *YouDownloader-5.2.0-mac-intel.zip\n")

    def test_finds_hash(self):
        self.assertEqual(u.sha_from_sums(self.SUMS, "YouDownloader-5.2.0-windows-setup.exe"), "a" * 64)
        self.assertEqual(u.sha_from_sums(self.SUMS, "YouDownloader-5.2.0-mac-intel.zip"), "b" * 64)
        self.assertIsNone(u.sha_from_sums(self.SUMS, "YouDownloader-5.2.0-mac-apple-silicon.zip"))


class TestRateLimitFallback(unittest.TestCase):
    def _get(self, url, **kw):
        if url == u.LATEST_URL:
            return _Resp(403, "API rate limit exceeded")
        if url == u.RELEASES_PAGE:
            return _Resp(302, headers={"Location": f"https://github.com/{u.GITHUB_REPO}/releases/tag/v99.0.0"})
        if url.endswith("/v99.0.0/SHA256SUMS.txt"):
            return _Resp(200, "c" * 64 + "  YouDownloader-99.0.0-windows-setup.exe\n")
        raise AssertionError(url)

    def test_uses_releases_page_when_api_limited(self):
        with mock.patch("requests.get", side_effect=self._get), \
                mock.patch.object(u, "asset_suffix", return_value="-windows-setup.exe"):
            rel = u.check()
        self.assertEqual(rel.version, "99.0.0")
        self.assertEqual(rel.sha256, "c" * 64)
        self.assertTrue(rel.asset_url.endswith("/releases/download/v99.0.0/YouDownloader-99.0.0-windows-setup.exe"))

    def test_asset_without_checksum_is_not_offered(self):
        with mock.patch("requests.get", side_effect=self._get), \
                mock.patch.object(u, "asset_suffix", return_value="-mac-intel.zip"):
            rel = u.check()
        self.assertEqual(rel.version, "99.0.0")
        self.assertIsNone(rel.asset_url)  # dialog falls back to "Open download page"

    def test_no_releases_yet(self):
        def get(url, **kw):
            if url == u.LATEST_URL:
                return _Resp(403, "rate limit")
            return _Resp(302, headers={"Location": f"https://github.com/{u.GITHUB_REPO}/releases"})
        with mock.patch("requests.get", side_effect=get):
            self.assertIsNone(u.check())


if __name__ == "__main__":
    unittest.main()
