"""Keep yt-dlp current. YouTube changes often; a few-months-old yt-dlp breaks."""
import subprocess
import sys
from datetime import date
from typing import Optional, Tuple

# Warn once yt-dlp is older than this (its versions are release dates).
STALE_AFTER_DAYS = 60

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def ytdlp_version() -> str:
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:
        return "unknown"


def ytdlp_age_days(version: Optional[str] = None, today: Optional[date] = None) -> Optional[int]:
    """Days since the installed yt-dlp was released, from its YYYY.MM.DD version."""
    version = version or ytdlp_version()
    try:
        y, m, d = (int(p) for p in version.split(".")[:3])
        return ((today or date.today()) - date(y, m, d)).days
    except (ValueError, TypeError):
        return None


def can_update_ytdlp() -> bool:
    """Always: pip from source; the packaged app downloads a newer copy next to
    its built-in one (src/utils/ytdlp_override.py)."""
    return True


def _python() -> str:
    return sys.executable.replace("pythonw.exe", "python.exe")


def update_ytdlp(timeout: int = 600) -> Tuple[bool, str]:
    """
    Get the newest yt-dlp (with its bundled solver): pip-upgrade it from
    source, or download it into the app-data folder in the packaged app.

    Returns (ok, message). The new version is used after the app restarts.
    """
    if getattr(sys, "frozen", False):
        from src.utils import ytdlp_override
        ok, msg, _new = ytdlp_override.install()
        return ok, msg
    before = ytdlp_version()
    cmd = [_python(), "-m", "pip", "install",
           "--disable-pip-version-check", "-U", "yt-dlp[default]"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"Update failed: {e}"
    if r.returncode != 0:
        tail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["pip failed"]
        return False, f"Update failed: {tail[0]}"
    after = _installed_version()
    if after and after != before:
        return True, f"yt-dlp updated {before} → {after}. Restart YouDownloader to use it."
    return True, f"yt-dlp {before} is already the latest version."


def _installed_version() -> Optional[str]:
    """Version on disk (the imported module still reports the old one)."""
    try:
        r = subprocess.run(
            [_python(), "-c",
             "from yt_dlp.version import __version__; print(__version__)"],
            capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
