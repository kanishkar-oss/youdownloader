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

    def test_nothing_useful(self):
        self.assertEqual(links_from_drop("just some words"), [])


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


if __name__ == "__main__":
    unittest.main()
