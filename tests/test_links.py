"""youdownloader:// links and the inbox that hands them to the open window."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

from src.utils import links  # noqa: E402


class TestParse(unittest.TestCase):
    def test_bookmarklet_link(self):
        link = "youdownloader://open?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3DjNQXAC9IVRw%26t%3D10"
        self.assertEqual(links.video_url_from_link(link), "https://www.youtube.com/watch?v=jNQXAC9IVRw&t=10")

    def test_loose_forms(self):
        self.assertEqual(links.video_url_from_link("youdownloader://https%3A%2F%2Fyoutu.be%2Fabc"),
                         "https://youtu.be/abc")
        self.assertEqual(links.video_url_from_link("YouDownloader:open?https://youtu.be/abc"),
                         "https://youtu.be/abc")

    def test_not_ours(self):
        self.assertIsNone(links.video_url_from_link("https://youtu.be/abc"))
        self.assertIsNone(links.video_url_from_link("youdownloader://open"))

    def test_bookmarklet_builds_our_link(self):
        self.assertIn("youdownloader://open?url=", links.BOOKMARKLET)
        self.assertIn("encodeURIComponent(location.href)", links.BOOKMARKLET)

    def test_setup_page_uses_the_same_bookmarklet(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "assets", "browser-button.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn(links.BOOKMARKLET, page)


class TestInbox(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.patch = mock.patch.object(links, "inbox_dir", return_value=self.dir)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_post_then_take_in_order(self):
        links.post("youdownloader://open?url=a")
        links.post("youdownloader://open?url=b")
        self.assertEqual(links.take(), ["youdownloader://open?url=a", "youdownloader://open?url=b"])
        self.assertEqual(links.take(), [])

    def test_stale_links_are_dropped(self):
        path = links.post("youdownloader://open?url=old")
        old = time.time() - 7200
        os.utime(path, (old, old))
        self.assertEqual(links.take(), [])
        self.assertEqual(os.listdir(self.dir), [])


if __name__ == "__main__":
    unittest.main()
