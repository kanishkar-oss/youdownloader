"""One-click diagnostics for bug reports (Settings > About & updates).

Collects the app/system versions, which tools and yt-dlp copy are in use, the
relevant settings and the recent log, so a tester can paste one block instead
of hunting for files. Never includes cookie values (nothing in the app logs
them), and the home folder is shortened to "~" so usernames don't leak.
"""
import os
import platform
import shutil
import subprocess
import sys
from typing import Optional

from src.utils import paths

LOG_LINES = 150


def _os_name() -> str:
    if paths.IS_MAC:
        return f"macOS {platform.mac_ver()[0]} ({platform.machine()})"
    if paths.IS_WINDOWS:
        build = platform.version()
        try:
            name = "Windows 11" if int(build.split(".")[2]) >= 22000 else "Windows 10"
        except (IndexError, ValueError):
            name = "Windows"
        return f"{name} {build} ({platform.machine()})"
    return f"{platform.system()} {platform.release()} ({platform.machine()})"


def _tool(name: str, *args: str) -> str:
    exe = shutil.which(name)
    if not exe:
        return "not found"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        first = ((r.stdout or r.stderr).strip().splitlines() or ["?"])[0]
    except (OSError, subprocess.SubprocessError) as e:
        first = f"failed to run ({e.__class__.__name__})"
    where = "bundled" if os.path.normcase(exe).startswith(os.path.normcase(paths.bundled_bin_dir())) else exe
    return f"{first[:90]} [{where}]"


def _tail(path: str, n: int) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:])
    except OSError as e:
        return f"(log not readable: {e})\n"


def redact(text: str) -> str:
    home = os.path.expanduser("~")
    for variant in {home, home.replace("\\", "/"), home.replace("/", "\\")}:
        if len(variant) > 3:
            text = text.replace(variant, "~")
    return text


def collect(app=None) -> str:
    """The diagnostics text. `app` (the main window) adds live state."""
    from src.version import __version__
    from src.utils import updater, ytdlp_override, cookies
    try:
        import tkinter
        tk_ver = tkinter.Tcl().eval("info patchlevel")
    except Exception:
        tk_ver = "?"
    st = ytdlp_override.state
    ytdlp = updater.ytdlp_version()
    if paths.FROZEN:
        ytdlp += (f" (downloaded by the app; built-in {st.get('bundled')})" if st.get("active")
                  else " (built in)")
        if st.get("error"):
            ytdlp += f"; a downloaded copy failed to load: {st['error']}"

    lines = [
        f"YouDownloader {__version__} ({'installed app' if paths.FROZEN else 'from source'})",
        f"System: {_os_name()}, Python {platform.python_version()}, Tk {tk_ver}",
        f"yt-dlp: {ytdlp}",
        f"ffmpeg: {_tool('ffmpeg', '-hide_banner', '-version')}",
        f"deno: {_tool('deno', '--version')}",
    ]
    if app is not None:
        cfg = app.config
        info = cookies.inspect(getattr(app, "cookie_file", None))
        if info.get("ok") and info.get("signed_in"):
            exp = info.get("expires")
            signin = "signed in" + (f", valid until {exp:%Y-%m-%d}" if exp else "")
        else:
            signin = "not signed in" + (f" ({info['error']})" if info.get("error") and app.cookie_file else "")
        lines += [
            f"YouTube sign-in: {signin}",
            "Settings: " + ", ".join(f"{k}={cfg.get(k)}" for k in (
                "format", "quality", "embed_metadata", "auto_download_subtitles", "js_runtime_consent",
                "auto_check_updates", "auto_update_ytdlp", "notifications_enabled")),
        ]
        try:
            items = app.queue.get_all()
            counts = {}
            for it in items:
                key = getattr(it.status, "value", str(it.status))
                counts[key] = counts.get(key, 0) + 1
            lines.append(f"Queue: {len(items)} items {counts if counts else ''}".rstrip())
        except Exception:
            pass
    log_path = os.path.join(paths.log_dir(), "youdownloader.log")
    lines += ["", f"--- last {LOG_LINES} log lines ---", _tail(log_path, LOG_LINES).rstrip()]
    update_log = os.path.join(paths.log_dir(), "update.log")
    if os.path.isfile(update_log):
        lines += ["", "--- update.log (last 30 lines) ---", _tail(update_log, 30).rstrip()]
    return redact("\n".join(lines)) + "\n"


def copy_to_clipboard(app, text: Optional[str] = None) -> str:
    """Put the diagnostics on the clipboard (`app` is the main window)."""
    text = text if text is not None else collect(app)
    root = app.winfo_toplevel()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()  # keep it on the clipboard after the dialog closes
    return text
