"""Clip parsing, cookies inspection, yt-dlp age, and the engine options they drive."""
import os
import tempfile
import time
import unittest
from datetime import date

# Keep test runs out of the real logs/youdownloader.log.
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

from src.utils.validators import parse_timestamp, parse_clip, format_timestamp
from src.utils import cookies, updater
from src.downloader.engine import DownloadEngine, _PRIMARY
from src.downloader.formats import VIDEO_MP4, VIDEO_MOV, AUDIO_MP3, AUDIO_WAV


class TestTimestamps(unittest.TestCase):
    def test_parse(self):
        self.assertIsNone(parse_timestamp("  "))
        self.assertEqual(parse_timestamp("90"), 90)
        self.assertEqual(parse_timestamp("1:30"), 90)
        self.assertEqual(parse_timestamp("1:02:03"), 3723)
        self.assertEqual(parse_timestamp("0:05.5"), 5.5)
        for bad in ("1:75", "a:10", "1::2", "-5", "1:2:3:4"):
            with self.assertRaises(ValueError):
                parse_timestamp(bad)

    def test_clip(self):
        self.assertEqual(parse_clip("", ""), (None, None))
        self.assertEqual(parse_clip("", "0:30"), (0.0, 30))
        self.assertEqual(parse_clip("1:00", ""), (60, None))
        with self.assertRaises(ValueError):
            parse_clip("2:00", "1:00")

    def test_format(self):
        self.assertEqual(format_timestamp(83), "1:23")
        self.assertEqual(format_timestamp(3723), "1:02:03")


class TestCookies(unittest.TestCase):
    def _write(self, rows):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            for domain, exp, name in rows:
                f.write(f"{domain}\tTRUE\t/\tTRUE\t{exp}\t{name}\tvalue\n")
        self.addCleanup(os.remove, path)
        return path

    def test_signed_in(self):
        future = int(time.time()) + 86400 * 30
        info = cookies.inspect(self._write([(".youtube.com", future, "SAPISID"),
                                             (".youtube.com", future, "PREF")]))
        self.assertTrue(info["ok"] and info["signed_in"])
        self.assertEqual(info["youtube_count"], 2)
        self.assertIn("signed in", cookies.describe(self._write([(".youtube.com", future, "SID")])))

    def test_expired_or_not_signed_in(self):
        past = int(time.time()) - 10
        self.assertFalse(cookies.inspect(self._write([(".youtube.com", past, "SID")]))["ok"])
        anon = cookies.inspect(self._write([(".youtube.com", 0, "PREF")]))
        self.assertTrue(anon["ok"])
        self.assertFalse(anon["signed_in"])

    def test_missing(self):
        self.assertFalse(cookies.inspect(None)["ok"])
        self.assertFalse(cookies.inspect("C:/nope/cookies.txt")["ok"])


class TestUpdater(unittest.TestCase):
    def test_age(self):
        self.assertEqual(updater.ytdlp_age_days("2026.10.26", date(2026, 11, 17)), 22)
        self.assertIsNone(updater.ytdlp_age_days("unknown"))


class TestEngineFeatureOptions(unittest.TestCase):
    def setUp(self):
        self.engine = DownloadEngine(ffmpeg_path="ffmpeg")

    def build(self, mode, url="https://youtu.be/x", **kw):
        return self.engine._build_opts("out", mode, "1080p", _PRIMARY, True, False, "en", url=url, **kw)

    def keys(self, opts):
        return [pp["key"] for pp in opts.get("postprocessors", [])]

    def test_metadata_and_cover_art(self):
        self.assertIn("EmbedThumbnail", self.keys(self.build(AUDIO_MP3, embed_metadata=True)))
        self.assertIn("EmbedThumbnail", self.keys(self.build(VIDEO_MP4, embed_metadata=True)))
        # WAV / MOV get tags but no cover art (unsupported / dropped on MOV rebuild).
        for mode in (AUDIO_WAV, VIDEO_MOV):
            keys = self.keys(self.build(mode, embed_metadata=True))
            self.assertIn("FFmpegMetadata", keys)
            self.assertNotIn("EmbedThumbnail", keys)
        self.assertEqual(self.keys(self.build(VIDEO_MP4, embed_metadata=False)), [])

    def test_clip(self):
        opts = self.build(AUDIO_WAV, clip=(30.0, None))
        self.assertIn("download_ranges", opts)
        self.assertTrue(opts["force_keyframes_at_cuts"])
        self.assertNotIn("external_downloader", opts)   # sections can't use aria2c
        self.assertIn("(clip 0.30-end)", opts["outtmpl"])

    def test_playlist_folder(self):
        self.assertTrue(DownloadEngine.is_playlist_url("https://www.youtube.com/playlist?list=PL1"))
        self.assertFalse(DownloadEngine.is_playlist_url("https://www.youtube.com/watch?v=a&list=PL1"))
        opts = self.build(VIDEO_MP4, url="https://www.youtube.com/playlist?list=PL1")
        self.assertIn("%(playlist_title)", opts["outtmpl"])
        self.assertIn("%(playlist_index)03d", opts["outtmpl"])


if __name__ == "__main__":
    unittest.main()
