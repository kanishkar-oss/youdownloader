"""youdownloader:// links: "Send to YouDownloader" from any browser.

The browser button (a bookmarklet, set up from Settings) opens
    youdownloader://open?url=<the page's address>
The installer registers the scheme on Windows (HKCU\\Software\\Classes) and the
app's Info.plist on macOS. Windows starts a new process with the link as its
argument; macOS sends the running app an Apple Event (tk::mac::LaunchURL).

A new process hands the link to the window that's already open (single
instance) through a small inbox folder the app checks a few times a second:
no sockets, no firewall prompts.
"""
import os
import re
import tempfile
import time
import uuid
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from src.utils import paths

SCHEME = "youdownloader"
# Runs in the browser: send the current page's address to the app.
BOOKMARKLET = ("javascript:void(location.href='youdownloader://open?url='"
               "+encodeURIComponent(location.href))")


def is_app_link(arg: str) -> bool:
    return (arg or "").strip().lower().startswith(SCHEME + ":")


def video_url_from_link(link: str) -> Optional[str]:
    """The page address carried by a youdownloader:// link (or None)."""
    link = (link or "").strip()
    if not is_app_link(link):
        return None
    query = parse_qs(urlsplit(link).query)
    url = (query.get("url") or [None])[0]
    if not url:  # tolerate youdownloader://https%3A%2F%2F... or ...?https://...
        m = re.search(r"https?(?::|%3A)[^\s]+", link, re.IGNORECASE)
        url = unquote(m.group(0)) if m else None
    return url.strip() if url else None


def inbox_dir() -> str:
    return os.path.join(paths.user_data_dir(), "inbox")


def post(link: str) -> str:
    """Queue a link for the app window (written atomically)."""
    folder = inbox_dir()
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".incoming-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(link)
    final = os.path.join(folder, f"{time.time():.6f}-{uuid.uuid4().hex[:8]}.link")
    os.replace(tmp, final)
    return final


def take(max_age_s: float = 3600) -> List[str]:
    """Links waiting in the inbox, oldest first (removed as they're read).
    Anything older than an hour is dropped unread."""
    folder = inbox_dir()
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".link"))
    except OSError:
        return []
    links = []
    for name in names:
        path = os.path.join(folder, name)
        try:
            fresh = time.time() - os.path.getmtime(path) < max_age_s
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
            os.remove(path)
        except OSError:
            continue
        if fresh and text:
            links.append(text)
    return links
