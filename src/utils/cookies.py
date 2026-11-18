"""cookies.txt handling: import to a private location and summarize validity.

YouTube serves 720p+ only to signed-in sessions (SABR / bot-check gating), so a
Netscape-format cookies.txt exported from a signed-in browser unlocks full
quality. The file holds live session tokens, so it's kept in the per-user app
data folder (%LOCALAPPDATA%\\YouDownloader on Windows, ~/Library/Application
Support/YouDownloader on macOS), not a synced project folder, and nothing here
ever logs or displays cookie values.
"""
import os
import shutil
import time
from datetime import datetime
from typing import Any, Dict, Optional

from src.utils import paths

APP_DATA_DIR = paths.user_data_dir()
DEFAULT_COOKIES_PATH = os.path.join(APP_DATA_DIR, "cookies.txt")

# Cookies that only exist for a signed-in Google/YouTube session.
_AUTH_NAMES = {"SID", "HSID", "SSID", "APISID", "SAPISID", "LOGIN_INFO",
               "__Secure-1PSID", "__Secure-3PSID"}


def inspect(path: Optional[str]) -> Dict[str, Any]:
    """
    Summarize a cookies.txt without exposing values.

    Returns {ok, signed_in, youtube_count, expires (datetime|None), error}.
    `expires` is the earliest expiry among the sign-in cookies.
    """
    result: Dict[str, Any] = {"ok": False, "signed_in": False, "youtube_count": 0,
                              "expires": None, "error": None}
    if not path:
        result["error"] = "No cookies file set"
        return result
    if not os.path.isfile(path):
        result["error"] = "Cookies file not found"
        return result
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError as e:
        result["error"] = f"Can't read cookies file: {e}"
        return result

    now = time.time()
    auth_expiries = []
    for line in lines:
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _, _, _, expiry, name, _ = parts
        if not (domain.endswith("youtube.com") or domain.endswith("google.com")):
            continue
        try:
            exp = int(float(expiry))
        except ValueError:
            continue
        if exp and exp < now:
            continue  # already expired
        if domain.endswith("youtube.com"):
            result["youtube_count"] += 1
            if name in _AUTH_NAMES:
                result["signed_in"] = True
                if exp:
                    auth_expiries.append(exp)

    if result["youtube_count"] == 0:
        result["error"] = ("No (unexpired) YouTube cookies in this file. Export it "
                           "while on youtube.com and signed in.")
        return result
    result["ok"] = True
    if auth_expiries:
        result["expires"] = datetime.fromtimestamp(min(auth_expiries))
    if not result["signed_in"]:
        result["error"] = "These YouTube cookies aren't from a signed-in session."
    return result


def describe(path: Optional[str]) -> str:
    """One-line human summary for the Settings sheet."""
    info = inspect(path)
    if not info["ok"]:
        return f"Cookies: {info['error']}"
    if not info["signed_in"]:
        return f"Cookies: {info['youtube_count']} YouTube cookies, but not signed in"
    exp = info["expires"]
    when = f", valid until {exp:%d %b %Y}" if exp else ""
    return f"Cookies: signed in to YouTube{when}"


def import_cookies(src: str) -> str:
    """Copy an exported cookies.txt into the private app-data location."""
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    if os.path.abspath(src) != os.path.abspath(DEFAULT_COOKIES_PATH):
        shutil.copyfile(src, DEFAULT_COOKIES_PATH)
    return DEFAULT_COOKIES_PATH


def find_default() -> Optional[str]:
    """The imported cookies file, if one exists."""
    return DEFAULT_COOKIES_PATH if os.path.isfile(DEFAULT_COOKIES_PATH) else None


def find_exports(limit: int = 5):
    """Newest cookie exports (*cookie*.txt) in Downloads / Desktop / Documents."""
    home = os.path.expanduser("~")
    folders = [os.path.join(home, d) for d in ("Downloads", "Desktop", "Documents")]
    folders += [os.path.join(home, "OneDrive", d) for d in ("Desktop", "Documents")]
    found = []
    for folder in folders:
        try:
            for name in os.listdir(folder):
                if "cookie" in name.lower() and name.lower().endswith(".txt"):
                    path = os.path.join(folder, name)
                    found.append((os.path.getmtime(path), path))
        except OSError:
            continue
    return [p for _, p in sorted(found, reverse=True)[:limit]]


def display_path(path: str) -> str:
    """Path with %LOCALAPPDATA% / ~ shortened for display."""
    local = os.environ.get("LOCALAPPDATA") if paths.IS_WINDOWS else None
    if local and path.lower().startswith(local.lower()):
        return "%LOCALAPPDATA%" + path[len(local):]
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.lower().startswith(home.lower()) else path
