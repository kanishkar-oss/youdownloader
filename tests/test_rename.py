"""File-name validation, renaming downloads, and custom output names."""
import os
import tempfile
import unittest

# Keep test runs out of the real logs/youdownloader.log.
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

from src.utils.validators import validate_filename
from src.utils.files import rename_download
from src.downloader.engine import DownloadEngine


class TestValidateFilename(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(validate_filename("  My song  "), ("My song", None))
        self.assertEqual(validate_filename("My song.mp3", ".mp3"), ("My song", None))
        self.assertEqual(validate_filename("v1.2 final"), ("v1.2 final", None))
        self.assertEqual(validate_filename("trailing dots..."), ("trailing dots", None))

    def test_rejects(self):
        for bad in ("", "   ", "a/b", "a\\b", "what?", "x:y", "<tag>", "CON", "lpt1.txt", "a" * 181):
            name, err = validate_filename(bad)
            self.assertIsNone(name, bad)
            self.assertTrue(err)


class TestRenameDownload(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def touch(self, name):
        path = os.path.join(self.dir, name)
        open(path, "w").close()
        return path

    def test_renames_with_sidecars(self):
        video = self.touch("Old title.mp4")
        self.touch("Old title.en.srt")
        self.touch("Old title extra.mp4")  # different stem: untouched
        new, err = rename_download(video, "New name")
        self.assertIsNone(err)
        self.assertEqual(os.path.basename(new), "New name.mp4")
        self.assertEqual(sorted(os.listdir(self.dir)),
                         ["New name.en.srt", "New name.mp4", "Old title extra.mp4"])

    def test_typed_extension_is_dropped(self):
        new, err = rename_download(self.touch("a.mp3"), "b.mp3")
        self.assertIsNone(err)
        self.assertEqual(os.path.basename(new), "b.mp3")

    def test_collision_and_missing(self):
        a = self.touch("a.wav")
        self.touch("b.wav")
        new, err = rename_download(a, "b")
        self.assertIsNone(new)
        self.assertIn("already exists", err)
        self.assertTrue(os.path.exists(a))
        self.assertIsNone(rename_download(os.path.join(self.dir, "gone.wav"), "x")[0])

    def test_case_only_rename(self):
        new, err = rename_download(self.touch("song.mp3"), "Song")
        self.assertIsNone(err)
        self.assertEqual(os.listdir(self.dir), ["Song.mp3"])


class TestCustomOuttmpl(unittest.TestCase):
    def test_custom_name(self):
        t = DownloadEngine._outtmpl("out", "https://youtu.be/x", None, "My 100% mix")
        self.assertEqual(t, os.path.join("out", "My 100%% mix.%(ext)s"))  # % escaped for yt-dlp

    def test_custom_name_on_playlist_names_folder(self):
        t = DownloadEngine._outtmpl("out", "https://www.youtube.com/playlist?list=PL1", None, "Road trip")
        self.assertTrue(t.startswith(os.path.join("out", "Road trip") + os.sep))
        self.assertIn("%(playlist_index)03d", t)


if __name__ == "__main__":
    unittest.main()
