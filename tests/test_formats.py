"""Format modes, quality presets, resolution tiers and engine option building."""
import os
import tempfile
import threading
import time
import unittest
# Keep test runs out of the real logs/youdownloader.log.
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))
from unittest import mock

from src.downloader.formats import FormatManager, VIDEO_MP4, VIDEO_MOV, AUDIO_MP3, AUDIO_M4A, AUDIO_WAV
from src.downloader.engine import DownloadEngine, _PRIMARY, _PROGRESSIVE
from src.downloader.queue import DownloadQueue, progress_fraction
from src.models.download import DownloadItem, DownloadStatus


class TestFormatModes(unittest.TestCase):
    def test_labels_round_trip(self):
        self.assertEqual(FormatManager.labels(), ["MP4", "MOV", "MP3", "M4A", "WAV"])
        for mode in (VIDEO_MP4, VIDEO_MOV, AUDIO_MP3, AUDIO_M4A, AUDIO_WAV):
            self.assertEqual(FormatManager.mode_from_label(FormatManager.label(mode)), mode)

    def test_unknown_mode_falls_back(self):
        self.assertEqual(FormatManager.normalize_mode("Video (AVI)"), VIDEO_MP4)
        self.assertEqual(FormatManager.normalize_mode(None), VIDEO_MP4)

    def test_kind_and_ffmpeg(self):
        self.assertTrue(FormatManager.is_video(VIDEO_MOV))
        self.assertFalse(FormatManager.is_video(AUDIO_WAV))
        self.assertFalse(FormatManager.needs_ffmpeg(VIDEO_MP4))
        for mode in (VIDEO_MOV, AUDIO_MP3, AUDIO_M4A, AUDIO_WAV):
            self.assertTrue(FormatManager.needs_ffmpeg(mode))

    def test_quality_options_per_mode(self):
        self.assertEqual(FormatManager.get_quality_options(VIDEO_MP4),
                         FormatManager.get_quality_options(VIDEO_MOV))
        self.assertIn("Best (320kbps)", FormatManager.get_quality_options(AUDIO_MP3))
        self.assertIn("24-bit / 48 kHz (studio)", FormatManager.get_quality_options(AUDIO_WAV))

    def test_normalize_quality(self):
        self.assertEqual(FormatManager.normalize_quality(VIDEO_MP4, "High (1080p+)"), "1080p")
        self.assertEqual(FormatManager.normalize_quality(VIDEO_MP4, "Best (320kbps)"), "1080p")
        self.assertEqual(FormatManager.normalize_quality(AUDIO_WAV, "1080p"),
                         FormatManager.get_quality_options(AUDIO_WAV)[0])

    def test_mp3_bitrate_matches_label(self):
        # Regression: "Best (320kbps)" used to encode at 192 kbps.
        self.assertEqual(FormatManager.get_audio_quality_value("Best (320kbps)"), "320")
        self.assertEqual(FormatManager.get_audio_quality_value("Standard (128kbps)"), "128")

    def test_selection(self):
        mov = FormatManager.get_selection(VIDEO_MOV, "720p")
        self.assertEqual(mov["format_sort"], ["res:720", "hdr:sdr", "+codec:avc:m4a"])
        native = FormatManager.get_selection(VIDEO_MP4, "Native (Max Quality)")
        self.assertEqual(native["format_sort"][0], "res")
        self.assertNotIn("format_sort", FormatManager.get_selection(AUDIO_WAV, "x"))


class TestResolutionTiers(unittest.TestCase):
    def test_tiers(self):
        tier = FormatManager.resolution_tier
        self.assertEqual(tier(1920, 1080), 1080)
        self.assertEqual(tier(1920, 960), 1080)    # letterboxed — was misread as 720p
        self.assertEqual(tier(1080, 1920), 1080)   # vertical / Shorts
        self.assertEqual(tier(1440, 1080), 1080)   # 4:3
        self.assertEqual(tier(3840, 1920), 2160)
        self.assertEqual(tier(1280, 640), 720)
        self.assertIsNone(tier(None, None))

    def test_best_available(self):
        formats = [{"width": 1920, "height": 960}, {"width": 1280, "height": 640},
                   {"width": None, "height": None, "vcodec": "none"}]
        self.assertEqual(FormatManager.get_best_available_resolution(formats, "1080p"), (1080, "1080p", True))
        self.assertEqual(FormatManager.get_best_available_resolution(formats, "4K (2160p)"), (1080, "1080p", False))
        self.assertEqual(FormatManager.get_best_available_resolution(formats, "480p"), (720, "720p", False))
        self.assertTrue(FormatManager.get_best_available_resolution(formats, "Native (Max Quality)")[2])


class TestEngineOptions(unittest.TestCase):
    def setUp(self):
        self.engine = DownloadEngine(ffmpeg_path="ffmpeg")

    def build(self, mode, quality, attempt=_PRIMARY):
        return self.engine._build_opts("out", mode, quality, attempt, False, False, "en")

    def test_common(self):
        opts = self.build(VIDEO_MP4, "1080p")
        self.assertTrue(opts["noplaylist"])  # watch?v=..&list=.. must not grab a whole Mix
        self.assertNotIn("remote_components", opts)
        self.assertEqual(opts["merge_output_format"], "mp4")

    def test_mov_merges_to_mkv(self):
        self.assertEqual(self.build(VIDEO_MOV, "4K (2160p)")["merge_output_format"], "mkv")

    def test_wav_args(self):
        opts = self.build(AUDIO_WAV, "24-bit / 48 kHz (studio)")
        self.assertEqual(opts["postprocessors"][0]["preferredcodec"], "wav")
        self.assertEqual(opts["postprocessor_args"]["extractaudio+ffmpeg_o"],
                         ["-c:a", "pcm_s24le", "-ar", "48000"])
        opts = self.build(AUDIO_WAV, "16-bit / original rate")
        self.assertEqual(opts["postprocessor_args"]["extractaudio+ffmpeg_o"], ["-c:a", "pcm_s16le"])

    def test_m4a_copies_the_aac_stream(self):
        opts = self.build(AUDIO_M4A, "Original quality (no re-encode)")
        self.assertTrue(opts["format"].startswith("bestaudio[ext=m4a]"))
        extract = next(p for p in opts["postprocessors"] if p["key"] == "FFmpegExtractAudio")
        self.assertEqual(extract["preferredcodec"], "m4a")
        self.assertNotIn("preferredquality", extract)  # no bitrate = no forced re-encode
        tagged = self.engine._build_opts("out", AUDIO_M4A, "Original quality (no re-encode)", _PRIMARY,
                                         False, False, "en", embed_metadata=True)
        self.assertTrue(tagged.get("writethumbnail"))  # cover art like MP3
        self.assertEqual(FormatManager.extension(AUDIO_M4A), "m4a")

    def test_progressive_attempt_keeps_audio_conversion(self):
        opts = self.build(AUDIO_MP3, "Best (320kbps)", _PROGRESSIVE)
        self.assertIn("18", opts["format"])
        self.assertEqual(opts["postprocessors"][0]["preferredquality"], "320")

    def test_missing_ffmpeg_is_reported(self):
        eng = DownloadEngine(ffmpeg_path=None)
        eng.ffmpeg_path = None
        with self.assertRaisesRegex(Exception, "FFmpeg is required"):
            eng.download("https://youtu.be/jNQXAC9IVRw", "out", AUDIO_WAV, "x")


class TestProgressFraction(unittest.TestCase):
    def test_none_totals(self):
        # Regression: 'total_bytes': None used to raise TypeError inside the hook.
        self.assertIsNone(progress_fraction({"downloaded_bytes": 10, "total_bytes": None}))
        self.assertEqual(progress_fraction({"downloaded_bytes": 5, "total_bytes": None,
                                            "total_bytes_estimate": 10}), 0.5)


class _FakeEngine:
    """Stands in for DownloadEngine: blocks until cancelled."""
    def __init__(self, **kwargs):
        self.cancelled = False
        self.downloaded_files = []
        self.progress_callback = None

    def download(self, **kwargs):
        for _ in range(200):
            if self.cancelled:
                return False
            time.sleep(0.01)
        return True

    def cancel(self):
        self.cancelled = True


class TestQueueCancel(unittest.TestCase):
    def test_stop_marks_cancelled_and_does_not_continue(self):
        # The queue saves on background threads; tolerate one finishing late.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, \
                mock.patch("src.downloader.queue.DownloadEngine", _FakeEngine):
            q = DownloadQueue(os.path.join(d, "queue.json"))
            q.add(DownloadItem(url="https://youtu.be/a"))
            q.add(DownloadItem(url="https://youtu.be/b"))
            self.assertTrue(q.start())
            time.sleep(0.05)
            q.stop()
            q._download_thread.join(timeout=5)
            items = q.get_all()
            # Regression: cancelling used to record FAILED and start the next item.
            self.assertEqual(items[0].status, DownloadStatus.CANCELLED)
            self.assertEqual(items[1].status, DownloadStatus.PENDING)
            self.assertFalse(q.is_running())
            self.assertTrue(q.retry(0))
            self.assertEqual(q.get_all()[0].status, DownloadStatus.PENDING)
            time.sleep(0.2)  # let async saves land before the temp dir goes


class TestDownloadsList(unittest.TestCase):
    """The one Downloads list: held items, start-next, pause."""

    def _queue(self, d):
        return DownloadQueue(os.path.join(d, "queue.json"))

    def test_held_items_wait_until_started(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, \
                mock.patch("src.downloader.queue.DownloadEngine", _FakeEngine):
            q = self._queue(d)
            held = DownloadItem(url="https://youtu.be/held", status=DownloadStatus.PAUSED)
            q.add(held)
            self.assertFalse(q.start())  # nothing pending: held items don't start by themselves
            self.assertEqual(held.status, DownloadStatus.PAUSED)
            self.assertEqual(len(q.get_waiting()), 1)
            self.assertTrue(q.start_all())
            self.assertEqual(held.status, DownloadStatus.DOWNLOADING)
            q.stop()
            q._download_thread.join(timeout=5)
            time.sleep(0.2)

    def test_start_item_jumps_ahead_of_other_waiting_items(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, \
                mock.patch("src.downloader.queue.DownloadEngine", _FakeEngine):
            q = self._queue(d)
            a, b, c = (DownloadItem(url=f"https://youtu.be/{x}") for x in "abc")
            for it in (a, b, c):
                q.add(it)
            self.assertTrue(q.start())          # a downloads
            self.assertTrue(q.start_item(c))    # c is next, ahead of b
            self.assertEqual([i.url[-1] for i in q.get_pending()], ["c", "b"])
            self.assertIs(q.current, a)
            q.stop()
            q._download_thread.join(timeout=5)
            time.sleep(0.2)

    def test_pause_puts_the_current_item_back_to_waiting(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, \
                mock.patch("src.downloader.queue.DownloadEngine", _FakeEngine):
            q = self._queue(d)
            q.add(DownloadItem(url="https://youtu.be/a"))
            q.add(DownloadItem(url="https://youtu.be/b"))
            self.assertTrue(q.start())
            time.sleep(0.05)
            q.pause()
            q._download_thread.join(timeout=5)
            items = q.get_all()
            self.assertEqual(items[0].status, DownloadStatus.PENDING)  # not "Cancelled"
            self.assertEqual(items[0].progress, 0.0)
            self.assertEqual(items[1].status, DownloadStatus.PENDING)
            self.assertFalse(q.is_running())
            self.assertTrue(q.is_paused())
            self.assertTrue(q.start())  # resumes from the paused item
            self.assertIs(q.current, items[0])
            q.cancel_current()  # a row's Stop: that one is Cancelled, the list moves on
            q._download_thread.join(timeout=5)
            self.assertEqual(items[0].status, DownloadStatus.CANCELLED)
            q.stop()
            time.sleep(0.2)

    def test_file_count_round_trips(self):
        item = DownloadItem(url="https://youtu.be/a", file_path="x.mp4", file_count=12)
        self.assertEqual(DownloadItem.from_dict(item.to_dict()).file_count, 12)
        # Older queue files have no file_count: one file if there's a path.
        data = item.to_dict()
        del data["file_count"]
        self.assertEqual(DownloadItem.from_dict(data).file_count, 1)


if __name__ == "__main__":
    unittest.main()
