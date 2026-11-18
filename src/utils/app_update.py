"""Self-update from GitHub Releases.

How releases are published: `scripts/release.ps1 <version>` (or release.sh)
bumps src/version.py, tags vX.Y.Z and pushes; GitHub Actions builds every
platform and attaches the files to a GitHub Release. This module reads the
newest release, picks this platform's file, verifies its SHA-256 and installs it:

- Windows: runs the Inno Setup installer silently (per-user, no admin prompt);
  it replaces the app and relaunches it.
- macOS:   unzips and checks the new .app (bundle id, version, signature) and,
  once this process exits, a small script swaps it in place of the running
  bundle (keeping the old one as <app>.previous until the new one starts)
  and relaunches it.

Flow used by the UI: check() -> download() -> prepare() (slow; worker thread)
-> launch() (then the app quits at once).

Asset names (made by .github/workflows/release.yml):
    YouDownloader-<ver>-windows-setup.exe
    YouDownloader-<ver>-mac-apple-silicon.zip / .dmg
    YouDownloader-<ver>-mac-intel.zip / .dmg
    SHA256SUMS.txt
"""
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from src.utils import paths
from src.utils.logger import get_logger
from src.version import APP_NAME, BUNDLE_ID, GITHUB_REPO, __version__

logger = get_logger()

LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
DOWNLOAD_PREFIX = "youdownloader-update-"
_UA = {"User-Agent": f"{APP_NAME}-updater"}


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


@dataclass
class Prepared:
    """A downloaded, unpacked and checked update, ready for launch()."""
    version: str
    path: str                       # installer (Windows) or new .app (macOS)
    staging: Optional[str] = None   # macOS: folder holding the new .app
    download_dir: Optional[str] = None


# ----- versions / platform ---------------------------------------------------

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
            out = subprocess.run(["/usr/sbin/sysctl", "-n", "sysctl.proc_translated"],
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


def _windows_install_dir() -> str:
    """Where the Inno Setup installer puts the app (packaging/windows/installer.iss)."""
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(local, "Programs", APP_NAME)


def current_app_bundle() -> Optional[str]:
    """/Applications/YouDownloader.app when running from a packaged .app."""
    exe = os.path.abspath(sys.executable)
    marker = ".app/Contents/MacOS/"
    i = exe.find(marker)
    return exe[: i + 4] if i != -1 else None


def install_blocker() -> Optional[str]:
    """Why this copy can't update itself in place (None if it can). Checked
    before downloading, so the dialog can offer the download page instead."""
    if not paths.FROZEN:
        return "You're running YouDownloader from source: update it with git pull."
    if paths.IS_WINDOWS:
        here = os.path.normcase(os.path.dirname(os.path.abspath(sys.executable)))
        if here != os.path.normcase(_windows_install_dir()):
            return ("This copy of YouDownloader wasn't installed with the installer, so it can't "
                    "update itself. Download the new installer instead.")
        return None
    if not paths.IS_MAC:
        return "Automatic updates aren't supported on this system."
    bundle = current_app_bundle()
    if not bundle:
        return "Couldn't find the running YouDownloader.app."
    if "/AppTranslocation/" in bundle or bundle.startswith("/Volumes/"):
        return ("YouDownloader is running from the disk image or a temporary location. Drag it to "
                "the Applications folder, open it from there, then update.")
    parent = os.path.dirname(bundle)
    if not (os.access(parent, os.W_OK) and os.access(bundle, os.W_OK)):
        return (f"YouDownloader can't replace itself in {parent} (no permission). Download the new "
                "version and drag it to Applications instead.")
    return None


def update_log_path() -> str:
    return os.path.join(paths.log_dir(), "update.log")


# ----- check -----------------------------------------------------------------

def check(timeout: float = 12) -> Optional[Release]:
    """The latest release if it's newer than this build, else None."""
    import requests
    try:
        r = requests.get(LATEST_URL, timeout=timeout,
                         headers={"Accept": "application/vnd.github+json", **_UA})
    except requests.RequestException as e:
        raise UpdateError(f"Couldn't reach GitHub to check for updates ({e.__class__.__name__}).")
    if r.status_code == 404:
        return None  # no releases yet
    if r.status_code in (403, 429):
        # The API allows 60 anonymous calls an hour per IP address, which a
        # shared office/school network can use up. The public release pages
        # aren't limited that way.
        logger.info(f"GitHub API refused the update check ({r.status_code}); using the releases page")
        return _check_releases_page(timeout)
    if r.status_code != 200:
        raise UpdateError(f"The update check failed (GitHub returned {r.status_code}).")
    data = r.json()
    version = (data.get("tag_name") or "").lstrip("v")
    if not version or data.get("draft") or data.get("prerelease") or not is_newer(version):
        return None

    rel = Release(version=version, notes=(data.get("body") or "").strip(),
                  page_url=data.get("html_url") or RELEASES_PAGE)
    suffix = asset_suffix()
    assets = data.get("assets") or []
    for asset in assets:
        if suffix and asset.get("name", "").endswith(suffix):
            rel.asset_name = asset["name"]
            rel.asset_url = asset.get("browser_download_url")
            rel.asset_size = int(asset.get("size") or 0)
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                rel.sha256 = digest.split(":", 1)[1].lower()
            break
    if rel.asset_url and not rel.sha256:
        # No API digest: use the release's SHA256SUMS.txt. Never offer a file
        # that can't be verified.
        sums = next((a.get("browser_download_url") for a in assets if a.get("name") == "SHA256SUMS.txt"), None)
        rel.sha256 = _fetch_sha(sums, rel.asset_name, timeout) if sums else None
        if not rel.sha256:
            logger.warning(f"No checksum published for {rel.asset_name}; not offering self-install")
            rel.asset_url = None
    logger.info(f"Update available: {__version__} -> {version} ({rel.asset_name or 'no asset'})")
    return rel


def sha_from_sums(text: str, name: str) -> Optional[str]:
    """The hash for `name` in a `sha256sum` listing ("<hash>  <file>")."""
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    return None


def _fetch_sha(sums_url: str, name: str, timeout: float) -> Optional[str]:
    import requests
    try:
        r = requests.get(sums_url, timeout=timeout, headers=_UA)
        return sha_from_sums(r.text, name) if r.ok else None
    except requests.RequestException:
        return None


def _check_releases_page(timeout: float) -> Optional[Release]:
    """Fallback check without the API: github.com/<repo>/releases/latest
    redirects to the newest tag; files follow the release naming scheme and
    their hashes come from the release's SHA256SUMS.txt."""
    import requests
    try:
        r = requests.get(RELEASES_PAGE, timeout=timeout, headers=_UA, allow_redirects=False)
    except requests.RequestException as e:
        raise UpdateError(f"Couldn't reach GitHub to check for updates ({e.__class__.__name__}).")
    location = r.headers.get("Location", "")
    m = re.search(r"/releases/tag/(v?(\d+(?:\.\d+)*))/?$", location)
    if r.status_code not in (301, 302, 303, 307, 308):
        raise UpdateError(f"The update check failed (GitHub returned {r.status_code}).")
    if not m:
        return None  # redirected to the release list: no releases yet
    tag, version = m.group(1), m.group(2)
    if not is_newer(version):
        return None
    page = location if location.startswith("http") else "https://github.com" + location
    rel = Release(version=version, notes="", page_url=page)
    suffix = asset_suffix()
    if suffix:
        name = f"{APP_NAME}-{version}{suffix}"
        base = f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/"
        sha = _fetch_sha(base + "SHA256SUMS.txt", name, timeout)
        if sha:  # listed in the checksums, so the file exists and can be verified
            rel.asset_name, rel.asset_url, rel.sha256 = name, base + name, sha
    logger.info(f"Update available (releases page): {__version__} -> {version} ({rel.asset_name or 'no asset'})")
    return rel


# ----- download --------------------------------------------------------------

class _Cancelled(Exception):
    pass


def download(rel: Release, on_progress: Optional[Callable[[float], None]] = None,
             is_cancelled: Callable[[], bool] = lambda: False) -> Optional[str]:
    """Download this platform's file. Returns its path, or None if cancelled."""
    import requests
    if not rel.asset_url:
        raise UpdateError("This release has no download for your system yet.")
    if not rel.sha256:
        raise UpdateError("This update has no published checksum, so it can't be installed safely.")
    try:
        folder = tempfile.mkdtemp(prefix=DOWNLOAD_PREFIX)
    except OSError as e:
        raise UpdateError(f"Couldn't create a temporary folder: {e}")
    dest = os.path.join(folder, rel.asset_name)
    sha = hashlib.sha256()
    done = 0
    try:
        with requests.get(rel.asset_url, stream=True, timeout=30, headers=_UA) as r:
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
    if (rel.asset_size and done != rel.asset_size) or sha.hexdigest().lower() != rel.sha256:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError("The downloaded update didn't match its checksum, so it wasn't installed.")
    logger.info(f"Downloaded update {rel.asset_name} ({done} bytes, sha256 verified)")
    return dest


def cleanup_stale_downloads(max_age_hours: float = 12) -> None:
    """Remove old update downloads (Windows installers aren't deleted by the
    installer itself; macOS's swap script cleans up after itself)."""
    root = tempfile.gettempdir()
    cutoff = time.time() - max_age_hours * 3600
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        if name.startswith(DOWNLOAD_PREFIX) or name.startswith("youdownloader-new-"):
            path = os.path.join(root, name)
            try:
                if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass


# ----- install ---------------------------------------------------------------

def prepare(path: str, version: str) -> Prepared:
    """Everything slow or checkable before the app quits (run off the UI
    thread). Raises UpdateError; on error nothing has been changed."""
    blocker = install_blocker()
    if blocker:
        raise UpdateError(blocker)
    if paths.IS_WINDOWS:
        return Prepared(version=version, path=path, download_dir=os.path.dirname(path))
    return _prepare_mac(path, version)


def discard(prep: Prepared) -> None:
    """Throw away a prepared update that won't be installed."""
    for folder in (prep.staging, prep.download_dir):
        if folder and os.path.basename(folder).lstrip(".").startswith(("youdownloader-new-", DOWNLOAD_PREFIX)):
            shutil.rmtree(folder, ignore_errors=True)


def launch(prep: Prepared) -> None:
    """Hand over to the installer / swap script. The caller must quit the app
    immediately afterwards so its files can be replaced."""
    os.makedirs(paths.log_dir(), exist_ok=True)
    if paths.IS_WINDOWS:
        _launch_windows(prep)
    else:
        _launch_mac(prep)


def _launch_windows(prep: Prepared) -> None:
    # /SILENT shows only a progress window; the installer closes us if we're
    # still running and its [Run] entry relaunches the app when it's done.
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([prep.path, "/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART",
                      "/CLOSEAPPLICATIONS", f"/LOG={update_log_path()}"],
                     creationflags=flags, close_fds=True)


def previous_bundle() -> Optional[str]:
    bundle = current_app_bundle()
    return bundle + ".previous" if bundle else None


def cleanup_previous_bundle() -> None:
    """After an update the old app is kept as YouDownloader.app.previous until
    the new one has started properly (so a broken release can be rolled back
    by hand). The new version calls this once it's up."""
    old = previous_bundle()
    if old and old.endswith(".app.previous") and os.path.isdir(old):
        shutil.rmtree(old, ignore_errors=True)
        logger.info(f"Removed the previous version ({old})")


def _bundle_info(app: str) -> dict:
    import plistlib
    with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
        return plistlib.load(f)


def _prepare_mac(archive: str, version: str) -> Prepared:
    bundle = current_app_bundle()
    parent = os.path.dirname(bundle)
    # Stage on the same volume as the app, so both moves in the swap are
    # atomic renames (an app on an external drive would otherwise need a copy
    # that could fail halfway).
    tmp_root = tempfile.gettempdir()
    same_volume = os.stat(parent).st_dev == os.stat(tmp_root).st_dev
    staging = tempfile.mkdtemp(prefix="youdownloader-new-" if same_volume else ".youdownloader-new-",
                               dir=tmp_root if same_volume else parent)
    try:
        r = subprocess.run(["/usr/bin/ditto", "-x", "-k", archive, staging], capture_output=True, text=True)
        if r.returncode != 0:
            raise UpdateError(f"Couldn't unpack the update: {r.stderr.strip()[-200:]}")
        apps = [n for n in os.listdir(staging) if n.endswith(".app")]
        new_app = os.path.join(staging, apps[0]) if len(apps) == 1 else None
        if not new_app or not os.path.isdir(os.path.join(new_app, "Contents", "MacOS")):
            raise UpdateError("The update archive didn't contain the app.")
        info = _bundle_info(new_app)
        if info.get("CFBundleIdentifier") != BUNDLE_ID:
            raise UpdateError("The downloaded update isn't YouDownloader, so it wasn't installed.")
        if info.get("CFBundleShortVersionString") != version:
            raise UpdateError(f"The downloaded update is version {info.get('CFBundleShortVersionString')}, "
                              f"not {version}, so it wasn't installed.")
        needs = info.get("LSMinimumSystemVersion") or ""
        have = platform.mac_ver()[0]
        if needs and have and is_newer(needs, have):
            raise UpdateError(f"YouDownloader {version} needs macOS {needs} or later (this Mac has {have}), "
                              "so it wasn't installed. Your current version keeps working.")
        v = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", new_app],
                           capture_output=True, text=True)
        if v.returncode != 0:
            raise UpdateError(f"The downloaded update failed its signature check: {v.stderr.strip()[-200:]}")
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except (OSError, ValueError) as e:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"Couldn't prepare the update: {e}")
    return Prepared(version=version, path=new_app, staging=staging, download_dir=os.path.dirname(archive))


def _launch_mac(prep: Prepared) -> None:
    script = os.path.join(prep.staging, "swap.sh")
    with open(script, "w") as f:
        f.write(MAC_SWAP_SCRIPT)
    logger.info(f"Handing over to the update script (log: {update_log_path()})")
    subprocess.Popen(swap_command(script, os.getpid(), current_app_bundle(), prep),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


def swap_command(script: str, pid: int, bundle: str, prep: Prepared) -> List[str]:
    return ["/bin/sh", script, str(pid), bundle, prep.path, prep.staging or "", prep.download_dir or "",
            update_log_path()]


# Runs after the app quits. Swaps the bundles, keeping the old one as
# <app>.previous (restored if the swap fails; the new version deletes it once
# it has started), clears quarantine, relaunches and removes its own temp
# folders. Never swaps while the app is still running. Uses absolute tool
# paths (the app's PATH puts Homebrew first) and checks every rm -rf target
# against the expected name. YD_UPDATE_NO_RELAUNCH / YD_UPDATE_WAIT_TICKS are
# for CI's test of this script.
MAC_SWAP_SCRIPT = r"""#!/bin/sh
pid="$1"; old="$2"; new="$3"; staging="$4"; dl="$5"; log="$6"
exec >>"$log" 2>&1
echo "$(/bin/date '+%Y-%m-%d %H:%M:%S') update: $new -> $old (waiting for pid $pid)"
cleanup() {
  case "$staging" in */youdownloader-new-*|*/.youdownloader-new-*) /bin/rm -rf "$staging";; esac
  case "$dl" in */youdownloader-update-*) /bin/rm -rf "$dl";; esac
}
relaunch() {
  /bin/sleep 1
  [ -n "$YD_UPDATE_NO_RELAUNCH" ] || /usr/bin/open -n "$old"
}
ticks="${YD_UPDATE_WAIT_TICKS:-300}"
i=0
while /bin/kill -0 "$pid" 2>/dev/null; do
  i=$((i+1))
  if [ "$i" -gt "$ticks" ]; then echo "app still running; update not applied"; cleanup; exit 1; fi
  /bin/sleep 0.2
done
case "$old" in *.app) ;; *) echo "refusing: $old is not an .app"; cleanup; exit 1;; esac
if [ ! -d "$new/Contents/MacOS" ]; then echo "new app is missing; update not applied"; cleanup; relaunch; exit 1; fi
backup="$old.previous"
/bin/rm -rf "$backup"
if [ -e "$backup" ]; then echo "couldn't remove $backup; update not applied"; cleanup; relaunch; exit 1; fi
if ! /bin/mv "$old" "$backup"; then
  echo "couldn't move the installed app aside (permissions?); update not applied"
  cleanup; relaunch; exit 1
fi
if /bin/mv "$new" "$old"; then
  echo "new version in place; old one kept as $backup until it starts"
else
  echo "couldn't move the new app in; restoring the old one"
  if [ -d "$backup" ]; then /bin/rm -rf "$old"; /bin/mv "$backup" "$old"; fi
fi
/usr/bin/xattr -dr com.apple.quarantine "$old" 2>/dev/null
cleanup
relaunch
echo "done"
"""
