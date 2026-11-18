"""Where things live, on Windows and macOS, from source or as a packaged app.

- Read-only resources (assets/, bundled bin/ tools) come from the project
  folder when running from source, or from the PyInstaller bundle when frozen.
- Writable state (settings, queue, logs, cookies) stays in the project's
  config/ and logs/ folders when running from source (unchanged dev workflow),
  and moves to the per-user app-data folder in the installed app, whose own
  folder is read-only (Program Files / /Applications):
    Windows: %LOCALAPPDATA%\\YouDownloader\\{config,logs}
    macOS:   ~/Library/Application Support/YouDownloader/config
             ~/Library/Logs/YouDownloader
"""
import os
import sys

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
FROZEN = bool(getattr(sys, "frozen", False))

APP_NAME = "YouDownloader"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resource_root() -> str:
    """Folder holding assets/ and bin/ (the bundle when frozen)."""
    if FROZEN:
        return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    return PROJECT_ROOT


def resource(*parts: str) -> str:
    return os.path.join(resource_root(), *parts)


def user_data_dir() -> str:
    """Per-user, non-synced app data folder (also holds cookies.txt)."""
    home = os.path.expanduser("~")
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    elif IS_MAC:
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, APP_NAME)


def config_dir() -> str:
    if FROZEN:
        return os.path.join(user_data_dir(), "config")
    return os.path.join(PROJECT_ROOT, "config")


def log_dir() -> str:
    # YOUDOWNLOADER_LOG_DIR lets tests log somewhere other than the real log.
    override = os.environ.get("YOUDOWNLOADER_LOG_DIR")
    if override:
        return override
    if not FROZEN:
        return os.path.join(PROJECT_ROOT, "logs")
    if IS_MAC:
        return os.path.join(os.path.expanduser("~"), "Library", "Logs", APP_NAME)
    return os.path.join(user_data_dir(), "logs")


def exe_name(name: str) -> str:
    return name + ".exe" if IS_WINDOWS else name


def bundled_bin_dir() -> str:
    """ffmpeg / ffprobe / deno shipped inside the packaged app (if any)."""
    return resource("bin")


def setup_tool_path() -> None:
    """Put bundled tools first on PATH, then the usual install locations.

    Apps launched from Finder / the Dock get a minimal PATH without Homebrew,
    so on macOS also add /opt/homebrew/bin and /usr/local/bin. Every
    shutil.which('ffmpeg' / 'deno') in the app then just works.
    """
    extra = []
    if os.path.isdir(bundled_bin_dir()):
        extra.append(bundled_bin_dir())
    extra.append(os.path.join(os.path.expanduser("~"), ".deno", "bin"))
    if IS_MAC:
        extra += ["/opt/homebrew/bin", "/usr/local/bin"]
    current = os.environ.get("PATH", "").split(os.pathsep)
    norm = {os.path.normcase(p) for p in current}
    head = [p for p in extra if os.path.isdir(p) and os.path.normcase(p) not in norm]
    # Bundled tools must win even if another copy is already on PATH.
    if os.path.isdir(bundled_bin_dir()):
        current = [p for p in current if os.path.normcase(p) != os.path.normcase(bundled_bin_dir())]
        head = [bundled_bin_dir()] + [p for p in head if p != bundled_bin_dir()]
    os.environ["PATH"] = os.pathsep.join(head + current)


def shortcut(key: str) -> str:
    """Display form of a Ctrl/Cmd shortcut, e.g. 'D' -> 'Ctrl+D' or '⌘D'."""
    return f"⌘{key}" if IS_MAC else f"Ctrl+{key}"
