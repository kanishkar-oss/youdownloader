"""The packaged app's downloaded-yt-dlp override: activation, fallback, install."""
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("YOUDOWNLOADER_LOG_DIR", os.path.join(tempfile.gettempdir(), "youdownloader-test-logs"))

import yt_dlp  # noqa: E402,F401  (the real one, restored after each test)
from src.utils import ytdlp_override as yo  # noqa: E402

REAL = yt_dlp.version.__version__


def _fake_package(root, version, broken=False):
    pkg = os.path.join(root, "yt_dlp")
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "__init__.py"), "w") as f:
        f.write("raise ImportError('boom')\n" if broken else "from . import version\n")
    with open(os.path.join(pkg, "version.py"), "w") as f:
        f.write(f"__version__ = {version!r}\n")
    with open(os.path.join(root, yo.INFO_FILE), "w") as f:
        json.dump({"yt_dlp": version}, f)


class OverrideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "yt-dlp")
        self._meta = list(sys.meta_path)

    def tearDown(self):
        sys.meta_path[:] = self._meta
        yo._purge_modules()
        import yt_dlp as real  # noqa: F401
        self.assertEqual(real.version.__version__, REAL)


class TestActivate(OverrideTest):
    def test_newer_download_is_used(self):
        _fake_package(self.root, "2099.01.01")
        st = yo.activate(frozen=True, override_dir=self.root, bundled="2026.10.26")
        self.assertEqual(st["active"], "2099.01.01")
        import yt_dlp as y
        self.assertEqual(y.version.__version__, "2099.01.01")
        self.assertTrue(os.path.abspath(y.__file__).startswith(os.path.abspath(self.root)))

    def test_broken_download_is_set_aside(self):
        _fake_package(self.root, "2099.01.01", broken=True)
        st = yo.activate(frozen=True, override_dir=self.root, bundled="2026.10.26")
        self.assertIsNone(st["active"])
        self.assertIn("boom", st["error"])
        self.assertFalse(os.path.exists(self.root))
        self.assertTrue(os.path.isdir(self.root + ".bad"))

    def test_older_download_is_deleted(self):
        _fake_package(self.root, "2020.01.01")
        st = yo.activate(frozen=True, override_dir=self.root, bundled="2026.10.26")
        self.assertIsNone(st["active"])
        self.assertFalse(os.path.exists(self.root))

    def test_source_runs_are_untouched(self):
        _fake_package(self.root, "2099.01.01")
        yo.activate(frozen=False, override_dir=self.root, bundled="2026.10.26")
        self.assertTrue(os.path.isdir(self.root))
        self.assertEqual(self._meta, list(sys.meta_path))


def _wheel(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


class _Resp:
    def __init__(self, content=b"", data=None):
        self.content, self._data = content, data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class TestInstall(OverrideTest):
    def _pypi(self, wheel, sha=None):
        sha = sha or hashlib.sha256(wheel).hexdigest()
        meta = {"info": {"version": "2099.01.01", "requires_dist": []},
                "urls": [{"packagetype": "bdist_wheel", "url": "https://files/yt_dlp.whl",
                          "digests": {"sha256": sha}}]}

        def get(url, **kw):
            return _Resp(data=meta) if url.endswith("/json") else _Resp(content=wheel)
        return get

    def test_install_unpacks_only_the_package(self):
        wheel = _wheel({"yt_dlp/__init__.py": "", "yt_dlp/version.py": "__version__ = '2099.01.01'\n",
                        "yt_dlp-2099.01.01.dist-info/METADATA": "Name: yt-dlp\n",
                        "evil/__init__.py": "raise SystemExit"})
        with mock.patch("requests.get", side_effect=self._pypi(wheel)), \
                mock.patch.object(yo, "active_version", return_value="2026.10.26"):
            ok, msg, new = yo.install(override_dir=self.root)
        self.assertTrue(ok, msg)
        self.assertEqual(new, "2099.01.01")
        self.assertTrue(os.path.isfile(os.path.join(self.root, "yt_dlp", "version.py")))
        self.assertFalse(os.path.exists(os.path.join(self.root, "evil")))
        self.assertEqual(json.load(open(os.path.join(self.root, yo.INFO_FILE)))["yt_dlp"], "2099.01.01")

    def test_checksum_mismatch_installs_nothing(self):
        wheel = _wheel({"yt_dlp/__init__.py": ""})
        with mock.patch("requests.get", side_effect=self._pypi(wheel, sha="0" * 64)), \
                mock.patch.object(yo, "active_version", return_value="2026.10.26"):
            ok, msg, new = yo.install(override_dir=self.root)
        self.assertFalse(ok)
        self.assertIn("checksum", msg)
        self.assertFalse(os.path.exists(self.root))

    def test_already_latest(self):
        wheel = _wheel({"yt_dlp/__init__.py": ""})
        with mock.patch("requests.get", side_effect=self._pypi(wheel)), \
                mock.patch.object(yo, "active_version", return_value="2099.01.01"):
            ok, msg, new = yo.install(override_dir=self.root)
        self.assertTrue(ok)
        self.assertIsNone(new)
        self.assertIn("latest", msg)


if __name__ == "__main__":
    unittest.main()
