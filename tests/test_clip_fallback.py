"""A clip whose ffmpeg cut fails (YouTube 403s ffmpeg without sign-in) retries
with the progressive format instead of failing with 'ffmpeg exited with code N'."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

import yt_dlp  # noqa: E402
from src.downloader import engine as eng  # noqa: E402

URL = "https://www.youtube.com/watch?v=FcEVbVrNIyg"
FFMPEG_FAIL = yt_dlp.utils.DownloadError("ERROR: ffmpeg exited with code 3436169992")


class TestClipFallback(unittest.TestCase):
    def _engine(self, fail_attempts):
        e = eng.DownloadEngine(ffmpeg_path="ffmpeg")
        attempts = []
        real_build = e._build_opts

        def build(output_path, mode, quality, attempt, *a, **k):
            attempts.append(attempt)
            return real_build(output_path, mode, quality, attempt, *a, **k)

        def run(url, opts, mode):
            if attempts[-1] in fail_attempts:
                raise FFMPEG_FAIL

        e._build_opts = build
        e._run = run
        return e, attempts

    def test_clip_falls_back_to_progressive(self):
        e, attempts = self._engine({eng._PRIMARY})
        self.assertTrue(e.download(URL, tempfile.gettempdir(), "Video (MP4)", "1080p",
                                   clip_start=10, clip_end=14))
        self.assertEqual(attempts, [eng._PRIMARY, eng._PROGRESSIVE])

    def test_clip_failing_twice_gives_a_readable_error(self):
        e, _ = self._engine({eng._PRIMARY, eng._PROGRESSIVE})
        with self.assertRaises(Exception) as ctx:
            e.download(URL, tempfile.gettempdir(), "Video (MP4)", "1080p", clip_start=10, clip_end=14)
        self.assertIn("clip", str(ctx.exception))
        self.assertNotIn("exited with code", str(ctx.exception))

    def test_full_video_ffmpeg_error_is_not_masked(self):
        e, attempts = self._engine({eng._PRIMARY})
        with self.assertRaises(Exception) as ctx:
            e.download(URL, tempfile.gettempdir(), "Video (MP4)", "1080p")
        self.assertEqual(attempts, [eng._PRIMARY])
        self.assertIn("ffmpeg exited", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
