"""Self-update from GitHub Releases.

How releases are published: `scripts/release.ps1 <version>` (or release.sh)
bumps src/version.py, tags vX.Y.Z and pushes; GitHub Actions builds every
platform and attaches the files to a GitHub Release. This module reads the
newest release, picks this platform's file, verifies its SHA-256 and installs it:

- Windows: runs the Inno Setup installer silently (per-user, no admin prompt);
  it replaces the app and relaunches it.
- macOS:   unzips the new .app and, once this process exits, swaps it in place
  of the running bundle and relaunches it.

Asset names (made by .github/workflows/release.yml):
    YouDownloader-<ver>-windows-setup.exe
    YouDownloader-<ver>-mac-apple-silicon.zip / .dmg
    YouDownloader-<ver>-mac-intel.zip / .dmg
"""
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from src.utils import paths
from src.utils.logger import get_logger
from src.version import APP_NAME, GITHUB_REPO, __version__

logger = get_logger()

LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"


class UpdateError(Exception):
    """A user-readable update failure."""


@dataclass
class Release:
    version: str
    notes: str
    page_url: str
    asset_name: Optional[str] = None
    asset_url: Optional[str] = None
    asset_size: int = 0
    sha256: Optional[str] = None


def parse_version(text: str) -> Tuple[int, ...]:
    m = re.match(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def is_newer(latest: str, current: str = __version__) -> bool:
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def mac_arch() -> str:
    """'apple-silicon' or 'intel'. An Intel build running under Rosetta on an
    Apple Silicon Mac updates to the native build."""
    machine = platform.machine().lower()
    if machine == "x86_64":
        try:
            out = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"],
                                 capture_output=True, text=True, timeout=5)
            if out.stdout.strip() == "1":
                return "apple-silicon"
        except (OSError, subprocess.SubprocessError):
            pass
        return "intel"
    return "apple-silicon"


def asset_suffix() -> Optional[str]:
    """The release file this platform installs, by name suffix."""
    if paths.IS_WINDOWS:
        return "-windows-setup.exe"
    if paths.IS_MAC:
        return f"-mac-{mac_arch()}.zip"
    return None


def can_self_install() -> bool:
    """Only the packaged app can replace itself (not a source checkout)."""
    return paths.FROZEN and asset_suffix() is not None


def check(timeout: float = 12) -> Optional[Release]:
    """The latest release if it's newer than this build, else None."""
    import requests
    try:
        r = requests.get(LATEST_URL, timeout=timeout, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}-updater",
        })
    except requests.RequestException as e:
        raise UpdateError(f"Couldn't reach GitHub to check for updates ({e.__class__.__name__}).")
    if r.status_code == 404:
        return None  # no releases yet
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise UpdateError("GitHub's update check limit was hit. Try again in an hour.")
    if r.status_code != 200:
        raise UpdateError(f"The update check failed (GitHub returned {r.status_code}).")
    data = r.json()
    version = (data.get("tag_name") or "").lstrip("v")
    if not version or data.get("draft") or data.get("prerelease") or not is_newer(version):
        return None

    rel = Release(version=version, notes=(data.get("body") or "").strip(),
                  page_url=data.get("html_url") or RELEASES_PAGE)
    suffix = asset_suffix()
    for asset in data.get("assets") or []:
        if suffix and asset.get("name", "").endswith(suffix):
            rel.asset_name = asset["name"]
            rel.asset_url = asset.get("browser_download_url")
            rel.asset_size = int(asset.get("size") or 0)
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                rel.sha256 = digest.split(":", 1)[1].lower()
            break
    logger.info(f"Update available: {__version__} -> {version} ({rel.asset_name or 'no asset'})")
    return rel


def download(rel: Release, on_progress: Optional[Callable[[float], None]] = None,
             is_cancelled: Callable[[], bool] = lambda: False) -> Optional[str]:
    """Download this platform's file. Returns its path, or None if cancelled."""
    import requests
    if not rel.asset_url:
        raise UpdateError("This release has no download for your system yet.")
    folder = tempfile.mkdtemp(prefix="youdownloader-update-")
    dest = os.path.join(folder, rel.asset_name)
    sha = hashlib.sha256()
    done = 0
    try:
        with requests.get(rel.asset_url, stream=True, timeout=30,
                          headers={"User-Agent": f"{APP_NAME}-updater"}) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or rel.asset_size or 0)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if is_cancelled():
                        raise _Cancelled()
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if on_progress and total:
                        on_progress(min(1.0, done / total))
    except _Cancelled:
        shutil.rmtree(folder, ignore_errors=True)
        return None
    except (requests.RequestException, OSError) as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError(f"The download failed: {e}")
    if rel.sha256 and sha.hexdigest().lower() != rel.sha256:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError("The downloaded update didn't match its checksum, so it wasn't installed.")
    logger.info(f"Downloaded update {rel.asset_name} ({done} bytes, sha256 "
                f"{'verified' if rel.sha256 else 'not published'})")
    return dest


class _Cancelled(Exception):
    pass


def install(path: str) -> None:
    """Start installing the downloaded update. The caller must quit the app
    right after this returns, so its files can be replaced."""
    if paths.IS_WINDOWS:
        _install_windows(path)
    elif paths.IS_MAC:
        _install_mac(path)
    else:
        raise UpdateError("Automatic updates aren't supported on this system.")


def _install_windows(installer: str) -> None:
    # /SILENT shows only a progress window; the installer closes us if we're
    # still running and its [Run] entry relaunches the app when it's done.
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([installer, "/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART",
                      "/CLOSEAPPLICATIONS"], creationflags=flags, close_fds=True)


def current_app_bundle() -> Optional[str]:
    """/Applications/YouDownloader.app when running from a packaged .app."""
    exe = os.path.abspath(sys.executable)
    marker = ".app/Contents/MacOS/"
    i = exe.find(marker)
    return exe[: i + 4] if i != -1 else None


def _install_mac(archive: str) -> None:
    bundle = current_app_bundle()
    if not bundle:
        raise UpdateError("Couldn't find the running YouDownloader.app.")
    if "/AppTranslocation/" in bundle:
        raise UpdateError("YouDownloader is running from a temporary location. Move it to the "
                          "Applications folder, open it from there, then update.")
    parent = os.path.dirname(bundle)
    if not (os.access(parent, os.W_OK) and os.access(bundle, os.W_OK)):
        raise UpdateError(f"YouDownloader can't replace itself in {parent} (no permission). "
                          "Download the new version and drag it to Applications instead.")
    staging = tempfile.mkdtemp(prefix="youdownloader-new-", dir=None)
    r = subprocess.run(["/usr/bin/ditto", "-x", "-k", archive, staging], capture_output=True, text=True)
    if r.returncode != 0:
        raise UpdateError(f"Couldn't unpack the update: {r.stderr.strip()[-200:]}")
    new_app = next((os.path.join(staging, n) for n in os.listdir(staging) if n.endswith(".app")), None)
    if not new_app:
        raise UpdateError("The update archive didn't contain the app.")

    script = os.path.join(staging, "swap.sh")
    with open(script, "w") as f:
        f.write(_MAC_SWAP_SCRIPT)
    subprocess.Popen(["/bin/sh", script, str(os.getpid()), bundle, new_app, archive],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


# Waits for the app to quit, swaps the bundles (restoring the old one if the
# move fails), clears quarantine, relaunches, and cleans up.
_MAC_SWAP_SCRIPT = r"""#!/bin/sh
pid="$1"; old="$2"; new="$3"; archive="$4"
i=0
while kill -0 "$pid" 2>/dev/null && [ $i -lt 300 ]; do sleep 0.2; i=$((i+1)); done
backup="$old.previous"
rm -rf "$backup"
if mv "$old" "$backup"; then
  if mv "$new" "$old"; then
    rm -rf "$backup"
  else
    mv "$backup" "$old"
  fi
fi
xattr -dr com.apple.quarantine "$old" 2>/dev/null
open "$old"
rm -rf "$(dirname "$new")" "$(dirname "$archive")"
"""
