"""Newer yt-dlp for the packaged app, without a full app update.

YouTube changes often and yt-dlp ships fixes within days, but the packaged app
has yt-dlp built in. This downloads the newest yt-dlp from PyPI, plus the
yt-dlp-ejs solver version it pins, into the app-data folder
(<app data>/yt-dlp). From the next launch that copy is imported instead of the
built-in one. That's about 3 MB instead of a 150 MB app update.

- activate(): main.py calls it before anything imports yt_dlp (packaged app only)
- install():  fetch, verify (PyPI's SHA-256), unpack, precompile (worker thread)
- reset():    go back to the built-in copy (from the next launch)

Safety nets:
- an update that fails to import is set aside (yt-dlp.bad) and the built-in
  copy is used; the app logs why and keeps working
- an update that isn't newer than the built-in copy (e.g. after an app update
  that bundled a newer yt-dlp) is deleted
- only the yt_dlp / yt_dlp_ejs packages are taken from the wheels

From source this module does nothing; source installs update yt-dlp with pip.
"""
import hashlib
import importlib
import importlib.machinery
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from typing import Dict, Optional, Tuple

from src.utils import paths

OVERRIDE_DIR = os.path.join(paths.user_data_dir(), "yt-dlp")
INFO_FILE = "override.json"
PACKAGES = ("yt_dlp", "yt_dlp_ejs")
_UA = {"User-Agent": "YouDownloader-ytdlp-updater"}

# What activate() did, for the UI, self-test and logs.
state: Dict[str, Optional[str]] = {"active": None, "bundled": None, "error": None}


def _vtuple(v: Optional[str]) -> Tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", v or ""))


def newer(a: Optional[str], b: Optional[str]) -> bool:
    """yt-dlp versions are dates (2026.10.26, 2026.10.26.1)."""
    return bool(a) and _vtuple(a) > _vtuple(b)


def bundled_info() -> dict:
    """What this build ships (packaging/build.py writes build_info.json)."""
    try:
        with open(paths.resource("build_info.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _read_info(root: str) -> dict:
    try:
        with open(os.path.join(root, INFO_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


class _OverrideFinder:
    """Serves yt_dlp / yt_dlp_ejs (and their submodules) from the update
    folder ahead of every other finder, including PyInstaller's frozen one."""

    def __init__(self, root: str):
        self.root = root

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in PACKAGES:
            return None
        search = [self.root] if "." not in fullname else list(path or [])
        root = os.path.normcase(self.root)
        if not any(os.path.normcase(os.path.abspath(p)).startswith(root) for p in search):
            return None  # e.g. yt_dlp_ejs isn't in the update: use the built-in one
        return importlib.machinery.PathFinder.find_spec(fullname, search)


def _purge_modules() -> None:
    for name in list(sys.modules):
        if name.split(".")[0] in PACKAGES:
            del sys.modules[name]
    importlib.invalidate_caches()


def activate(frozen: Optional[bool] = None, override_dir: Optional[str] = None,
             bundled: Optional[str] = None) -> dict:
    """Use the downloaded yt-dlp if it's newer than the built-in one."""
    frozen = paths.FROZEN if frozen is None else frozen
    root = os.path.abspath(override_dir or OVERRIDE_DIR)
    if not frozen:
        return state
    bundled = bundled or bundled_info().get("yt_dlp")
    state.update(active=None, bundled=bundled, error=None)
    info = _read_info(root)
    version = info.get("yt_dlp")
    if not version:
        return state
    if not bundled or not newer(version, bundled):
        shutil.rmtree(root, ignore_errors=True)  # the app now ships this one (or newer)
        return state
    finder = _OverrideFinder(root)
    sys.meta_path.insert(0, finder)
    try:
        _purge_modules()
        import yt_dlp  # noqa: F401  (trial import: fail here, not mid-download)
        from yt_dlp.version import __version__ as loaded
        if loaded != version:
            raise ImportError(f"expected yt-dlp {version}, loaded {loaded}")
        state["active"] = version
    except Exception as e:
        sys.meta_path.remove(finder)
        _purge_modules()
        bad = root + ".bad"
        shutil.rmtree(bad, ignore_errors=True)
        try:
            os.replace(root, bad)
        except OSError:
            shutil.rmtree(root, ignore_errors=True)
        state["error"] = f"{type(e).__name__}: {e}"
    return state


def active_version() -> Optional[str]:
    return state.get("active") or state.get("bundled") or bundled_info().get("yt_dlp")


def latest(timeout: float = 15) -> dict:
    """Newest yt-dlp on PyPI: {version, wheel: {url, sha256}, ejs: {version, url, sha256} | None}."""
    import requests
    r = requests.get("https://pypi.org/pypi/yt-dlp/json", timeout=timeout, headers=_UA)
    r.raise_for_status()
    data = r.json()
    version = data["info"]["version"]
    wheel = next(u for u in data["urls"] if u.get("packagetype") == "bdist_wheel")
    out = {"version": version, "wheel": {"url": wheel["url"], "sha256": wheel["digests"]["sha256"]}, "ejs": None}
    pin = next((m.group(1) for req in data["info"].get("requires_dist") or []
                for m in [re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", req)] if m), None)
    if pin:
        e = requests.get(f"https://pypi.org/pypi/yt-dlp-ejs/{pin}/json", timeout=timeout, headers=_UA)
        e.raise_for_status()
        ew = next(u for u in e.json()["urls"] if u.get("packagetype") == "bdist_wheel")
        out["ejs"] = {"version": pin, "url": ew["url"], "sha256": ew["digests"]["sha256"]}
    return out


def _fetch_verified(url: str, sha256: str, timeout: float) -> bytes:
    import requests
    r = requests.get(url, timeout=timeout, headers=_UA)
    r.raise_for_status()
    if hashlib.sha256(r.content).hexdigest() != sha256.lower():
        raise ValueError(f"checksum mismatch for {url.rsplit('/', 1)[-1]}")
    return r.content


def _unpack(wheel: bytes, dest: str) -> None:
    import io
    with zipfile.ZipFile(io.BytesIO(wheel)) as z:
        for member in z.infolist():
            top = member.filename.split("/")[0]
            if top in PACKAGES or (top.endswith(".dist-info") and top.split("-")[0] in PACKAGES):
                target = os.path.normpath(os.path.join(dest, member.filename))
                if not target.startswith(os.path.normpath(dest) + os.sep):
                    raise ValueError(f"unsafe path in wheel: {member.filename}")
                z.extract(member, dest)


def install(timeout: float = 60, override_dir: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
    """Download a newer yt-dlp if there is one. Returns (ok, message, new_version)."""
    import compileall
    root = os.path.abspath(override_dir or OVERRIDE_DIR)
    current = active_version()
    try:
        info = latest(timeout=min(timeout, 20))
    except Exception as e:
        return False, f"Couldn't check for a newer yt-dlp ({e.__class__.__name__}).", None
    version = info["version"]
    pending = _read_info(root).get("yt_dlp")
    if not newer(version, current) or version == pending:
        if pending and newer(pending, current):
            return True, f"yt-dlp {pending} is downloaded. Restart YouDownloader to use it.", pending
        return True, f"yt-dlp {current} is the latest version.", None
    parent = os.path.dirname(root)
    os.makedirs(parent, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=".yt-dlp-new-", dir=parent)
    try:
        _unpack(_fetch_verified(info["wheel"]["url"], info["wheel"]["sha256"], timeout), staging)
        ejs = info.get("ejs")
        if ejs and ejs["version"] != bundled_info().get("yt_dlp_ejs"):
            _unpack(_fetch_verified(ejs["url"], ejs["sha256"], timeout), staging)
        if not os.path.isfile(os.path.join(staging, "yt_dlp", "__init__.py")):
            raise ValueError("the yt-dlp package wasn't in the download")
        compileall.compile_dir(staging, quiet=1)  # so the first launch isn't slow
        with open(os.path.join(staging, INFO_FILE), "w", encoding="utf-8") as f:
            json.dump({"yt_dlp": version, "yt_dlp_ejs": (ejs or {}).get("version"),
                       "replaces": current}, f, indent=2)
        old = root + ".old"
        shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(root):
            os.replace(root, old)
        os.replace(staging, root)
        shutil.rmtree(old, ignore_errors=True)
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        return False, f"yt-dlp update failed: {e}", None
    return True, f"yt-dlp {version} is downloaded. Restart YouDownloader to use it.", version


def reset(override_dir: Optional[str] = None) -> None:
    """Use the built-in yt-dlp again (from the next launch)."""
    root = os.path.abspath(override_dir or OVERRIDE_DIR)
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(root + ".bad", ignore_errors=True)
