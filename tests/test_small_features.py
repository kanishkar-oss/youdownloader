"""Dropped links, diagnostics redaction, notification commands."""
import os
import plistlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

from src.app import links_from_drop  # noqa: E402
from src.utils import diagnostics, notify  # noqa: E402


class TestDroppedLinks(unittest.TestCase):
    def test_plain_url(self):
        self.assertEqual(links_from_drop("https://www.youtube.com/watch?v=abc"),
                         ["https://www.youtube.com/watch?v=abc"])

    def test_several_and_braces(self):
        data = "{https://youtu.be/a} https://youtu.be/b"
        self.assertEqual(links_from_drop(data), ["https://youtu.be/a", "https://youtu.be/b"])

    def test_windows_url_file(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "My video.url")
        with open(path, "w") as f:
            f.write("[InternetShortcut]\nURL=https://www.youtube.com/watch?v=xyz\n")
        self.assertEqual(links_from_drop("{" + path + "}", splitlist=lambda s: [path]),
                         ["https://www.youtube.com/watch?v=xyz"])

    def test_mac_webloc_file(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "clip.webloc")
        with open(path, "wb") as f:
            plistlib.dump({"URL": "https://youtu.be/q"}, f)
        self.assertEqual(links_from_drop(path, splitlist=lambda s: [path]), ["https://youtu.be/q"])

    def test_html_link(self):  # what some browsers (e.g. Dia) offer instead of plain text
        data = '<a href="https://www.youtube.com/watch?v=abc&amp;t=10">Video title</a>'
        self.assertEqual(links_from_drop(data), ["https://www.youtube.com/watch?v=abc&t=10"])

    def test_url_and_title(self):  # public.url + public.url-name
        self.assertEqual(links_from_drop("https://youtu.be/q\nMy video"), ["https://youtu.be/q"])

    def test_nothing_useful(self):
        self.assertEqual(links_from_drop("just some words"), [])


class TestDropTypes(unittest.TestCase):
    def test_mac_with_new_tkdnd_accepts_everything(self):
        from src.app import drop_types, DND_ALL
        self.assertEqual(drop_types("2.10.3", is_mac=True), (DND_ALL,))

    def test_intel_mac_tkdnd_29_keeps_text_and_files(self):
        from src.app import drop_types, DND_TEXT, DND_FILES
        self.assertEqual(drop_types("2.9.4", is_mac=True), (DND_TEXT, DND_FILES))

    def test_windows_keeps_text_and_files(self):
        from src.app import drop_types, DND_TEXT, DND_FILES
        self.assertEqual(drop_types("2.10.3", is_mac=False), (DND_TEXT, DND_FILES))
        self.assertEqual(drop_types("weird", is_mac=True), (DND_TEXT, DND_FILES))


class TestDiagnostics(unittest.TestCase):
    def test_home_folder_is_redacted(self):
        home = os.path.expanduser("~")
        text = diagnostics.redact(f"saved to {home}{os.sep}Downloads{os.sep}x.mp4")
        self.assertNotIn(home, text)
        self.assertIn("~", text)

    def test_collect_has_versions_and_log(self):
        text = diagnostics.collect()
        self.assertIn("YouDownloader", text)
        self.assertIn("yt-dlp:", text)
        self.assertIn("log lines", text)
        self.assertNotIn(os.path.expanduser("~"), text)


class TestNotify(unittest.TestCase):
    def test_windows_command_passes_text_through_env(self):
        with mock.patch.object(sys, "platform", "win32"):
            argv, env = notify.command('Done "quoted"', "a <b> & c")
        self.assertEqual(argv[0], "powershell.exe")
        self.assertIn("-EncodedCommand", argv)
        self.assertEqual(env["YD_TOAST_BODY"], "a <b> & c")  # escaped inside PowerShell, not by us
        self.assertEqual(env["YD_TOAST_APPID"], "YouDownloader.App")

    def test_mac_command_passes_text_as_arguments(self):
        with mock.patch.object(sys, "platform", "darwin"):
            argv, env = notify.command("Done", 'He said "hi"')
        self.assertEqual(argv[0], "/usr/bin/osascript")
        self.assertEqual(argv[-2:], ["Done", 'He said "hi"'])


class TestDownloadsListDisplay(unittest.TestCase):
    def test_order_is_active_waiting_held_then_newest_finished(self):
        from datetime import datetime, timedelta
        from src.app import YouDownloaderApp
        from src.models.download import DownloadItem, DownloadStatus as S
        t = datetime(2026, 1, 1)
        old = DownloadItem(url="old", status=S.COMPLETED, completed_at=t)
        new = DownloadItem(url="new", status=S.FAILED, created_at=t + timedelta(hours=1))
        active = DownloadItem(url="active", status=S.DOWNLOADING)
        w1, w2 = DownloadItem(url="w1"), DownloadItem(url="w2")
        held = DownloadItem(url="held", status=S.PAUSED)
        order = YouDownloaderApp.display_order([old, w1, held, active, new, w2])
        self.assertEqual([i.url for i in order], ["active", "w1", "w2", "held", "new", "old"])

    def test_row_stats(self):
        from src.app import YouDownloaderApp
        from src.models.download import DownloadItem
        item = DownloadItem(url="u", progress=0.42, speed=8.4 * 1048576, eta=72)
        item.stage = "Video"
        self.assertEqual(YouDownloaderApp.row_stats(item), "Video 42%  ·  8.4 MB/s  ·  1:12 left")
        item.stage, item.speed, item.eta = "Merging", 0, None
        self.assertEqual(YouDownloaderApp.row_stats(item), "Merging")


class TestLinkMessages(unittest.TestCase):
    """Wording of the errors shown under the link box."""

    def test_short_error_drops_ytdlp_prefixes_and_extra_lines(self):
        from src.app import YouDownloaderApp
        err = Exception("ERROR: [youtube] aaaaaaaaaaa: This video is unavailable\nmore detail")
        self.assertEqual(YouDownloaderApp._short_error(err), "This video is unavailable")

    def test_short_error_caps_length(self):
        from src.app import YouDownloaderApp
        text = YouDownloaderApp._short_error(Exception("x" * 500))
        self.assertEqual(len(text), 201)
        self.assertTrue(text.endswith("…"))

    def test_sentence_adds_a_full_stop_once(self):
        from src.app import YouDownloaderApp
        self.assertEqual(YouDownloaderApp._sentence("Invalid YouTube URL format"), "Invalid YouTube URL format.")
        self.assertEqual(YouDownloaderApp._sentence("Already done."), "Already done.")
        self.assertEqual(YouDownloaderApp._sentence(None), "Check the link and try again.")


if __name__ == "__main__":
    unittest.main()
