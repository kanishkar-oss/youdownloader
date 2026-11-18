"""Validation utilities for YouDownloader"""
import os
import re
import shutil
from pathlib import Path
from typing import Tuple, Optional
from urllib.parse import urlparse, parse_qs

# Hosts we accept. Parsing the URL and checking the host (rather than running a
# substring regex over the whole string) is what rejects injection attempts like
# "http://evil.com/?youtube.com/watch?v=X" — there the host is evil.com.
_ALLOWED_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
})

# Per-path-shape checks for youtube.com paths. Compiled once at import time.
_YOUTUBE_PATH_PATTERNS = (
    re.compile(r"^/embed/[\w-]+"),
    re.compile(r"^/v/[\w-]+"),
    re.compile(r"^/shorts/[\w-]+"),
)


def validate_youtube_url(url: str) -> Tuple[bool, Optional[str]]:
    """
    Validate a YouTube URL by parsing it and verifying the host + path shape.

    Args:
        url: URL string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not url or not url.strip():
        return False, "Please enter a YouTube URL"

    url = url.strip()

    # Allow scheme-less input ("youtube.com/watch?v=...") by assuming https,
    # but never silently upgrade a non-web scheme such as file:/javascript:/data:.
    parsed = urlparse(url if "://" in url else "https://" + url)

    if parsed.scheme not in ("http", "https"):
        return False, "Only http(s) YouTube links are supported"

    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        return False, "Invalid YouTube URL format"

    path = parsed.path or ""
    query = parse_qs(parsed.query)

    # youtu.be/<id>
    if host in ("youtu.be", "www.youtu.be"):
        if len(path.strip("/")) > 0:
            return True, None
        return False, "Invalid YouTube URL format"

    # youtube.com/...
    if path == "/watch":
        if query.get("v", [""])[0] or query.get("list", [""])[0]:
            return True, None
        return False, "Invalid YouTube URL format"
    if path == "/playlist":
        if query.get("list", [""])[0]:
            return True, None
        return False, "Invalid YouTube URL format"
    if any(pattern.match(path) for pattern in _YOUTUBE_PATH_PATTERNS):
        return True, None

    return False, "Invalid YouTube URL format"


def validate_path(path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate a download directory: expand ~, normalize, and confirm it is an
    existing writable directory.

    Args:
        path: Path string to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not path or not path.strip():
        return False, "Path cannot be empty"

    # expanduser handles "~" (previously left literal); resolve normalizes away
    # any ".." traversal segments to a canonical absolute path.
    try:
        resolved = Path(path.strip()).expanduser().resolve()
    except (OSError, RuntimeError) as e:
        return False, f"Invalid path: {e}"

    if not resolved.exists():
        return False, f"Path does not exist: {resolved}"

    if not resolved.is_dir():
        return False, f"Path is not a directory: {resolved}"

    if not os.access(resolved, os.W_OK):
        return False, f"No write permission for: {resolved}"

    return True, None


def check_disk_space(path: str, required_bytes: int = 0) -> Tuple[bool, Optional[str]]:
    """
    Check available disk space using shutil.disk_usage (cross-platform — the
    previous os.statvfs call always raised AttributeError on Windows and was
    silently treated as "enough space").

    Args:
        path: Path to check
        required_bytes: Required bytes (0 to just verify the path is reachable)

    Returns:
        Tuple of (has_space, error_message)
    """
    try:
        available = shutil.disk_usage(path).free
    except OSError:
        # Path unreachable — let the dedicated path validator report the problem.
        return True, None

    if required_bytes > 0 and available < required_bytes:
        return False, (
            f"Insufficient disk space. Required: {required_bytes / (1024 ** 3):.2f} GB, "
            f"Available: {available / (1024 ** 3):.2f} GB"
        )

    return True, None


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing characters that are invalid on common
    filesystems and bounding its length.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename
    """
    # Remove invalid characters for Windows/Linux/Mac
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", filename)

    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip(" .")

    # Limit length (Windows has a 260-char path limit)
    if len(sanitized) > 200:
        sanitized = sanitized[:200]

    return sanitized


def parse_timestamp(text: str) -> Optional[float]:
    """
    Parse "90", "1:30", "1:02:03" or "1:30.5" into seconds.

    Returns None for blank input; raises ValueError for anything else invalid.
    """
    text = (text or "").strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3 or any(p.strip() == "" for p in parts):
        raise ValueError(f"Invalid time '{text}' (use 1:30 or 1:02:03)")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"Invalid time '{text}' (use 1:30 or 1:02:03)")
    if any(n < 0 for n in nums) or any(n >= 60 for n in nums[1:]):
        raise ValueError(f"Invalid time '{text}'")
    seconds = 0.0
    for n in nums:
        seconds = seconds * 60 + n
    return seconds


def format_timestamp(seconds: float) -> str:
    """Inverse of parse_timestamp: 83 -> "1:23", 3723 -> "1:02:03"."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def parse_clip(start_text: str, end_text: str):
    """(start, end) seconds for a clip, or (None, None) for the whole video."""
    start, end = parse_timestamp(start_text), parse_timestamp(end_text)
    if start is None and end is None:
        return None, None
    if end is not None and end <= (start or 0):
        raise ValueError("Clip end must be after the start")
    return start or 0.0, end


_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                   *(f"LPT{i}" for i in range(1, 10))}
_BAD_CHARS = set('<>:"/|?*') | {chr(92)}  # plus backslash


def validate_filename(name: str, extension: str = "") -> Tuple[Optional[str], Optional[str]]:
    """
    Check a user-typed file name (without folder). Returns (clean_name, error).

    A trailing extension matching `extension` (e.g. ".mp3") is dropped, as are
    trailing spaces/dots (Windows strips them silently anyway).
    """
    name = (name or "").strip()
    if extension and name.lower().endswith(extension.lower()):
        name = name[: -len(extension)]
    name = name.rstrip(" .")
    if not name:
        return None, "Enter a file name"
    bad = sorted({c for c in name if c in _BAD_CHARS or ord(c) < 32})
    if bad:
        shown = " ".join(c if ord(c) >= 32 else "?" for c in bad)
        return None, f"A file name can't contain {shown}"
    if name.split(".")[0].upper() in _RESERVED_NAMES:
        return None, f"“{name}” is reserved by Windows"
    if len(name) > 180:
        return None, "That name is too long (180 characters max)"
    return name, None
