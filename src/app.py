"""Main application window for YouDownloader.

Layout (top to bottom):
  SpaceHeader  — full-width starfield band: wordmark, sign-in chip, Settings
  Compose card — link bar, preview, format/quality, file name, clip, folder, actions
  Status card  — status line + stats, progress bar, Play / Show / Rename
  Queue card   — toolbar + rows (updated in place while downloading)

Cards sit in a centered column capped at CONTENT_MAX_WIDTH, so wide or
maximized windows stay calm instead of stretching edge to edge.
"""
import io
import os
import re
import shutil
import sys
import threading
import tkinter.filedialog
from typing import Any, Callable, Dict, List, Optional

import customtkinter

from src.utils.config import Config
from src.utils.logger import get_logger
from src.utils.validators import validate_youtube_url, validate_path, parse_clip, validate_filename
from src.utils import cookies as cookie_store
from src.utils import app_update, paths, updater, winsys
from src.version import __version__
from src.utils.files import rename_download
from src.utils.helpers import check_ffmpeg, format_duration
from src.ui import icons
from src.ui.tokens import (SPACING, RADIUS, BORDER, HEIGHT, TYPE, MOTION, CONTENT_MAX_WIDTH,
                           CONTENT_GUTTER, init_fonts, tracked)
from src.ui.palettes import SPACE
from src.ui.components import set_window_icon
from src.ui.widgets.banner import InlineBanner
from src.ui.widgets.buttons import PrimaryButton, SecondaryButton, GhostButton, IconButton
from src.ui.widgets.entry import FieldEntry, SelectButton
from src.ui.widgets.header import SpaceHeader
from src.ui.widgets.pip import StatusPip
from src.ui.widgets.popup import PopupMenu
from src.ui.widgets.motion import crossfade
from src.ui.dialogs import (
    ErrorDialog, InfoDialog, ConfirmDialog, QualityWarningDialog, ConsentDialog, SettingsDialog,
    PasteListDialog, RenameDialog, UpdateDialog,
)
from src.downloader.engine import DownloadEngine
from src.downloader.queue import DownloadQueue, progress_fraction
from src.downloader.formats import FormatManager
from src.models.download import DownloadItem, DownloadStatus

logger = get_logger()

# Drag a link onto the window (tkdnd via tkinterdnd2). Optional: without it
# the app works as before.
try:
    from tkinterdnd2 import TkinterDnD, DND_ALL, DND_FILES, DND_TEXT
    _DnDMixin = TkinterDnD.DnDWrapper
except Exception:  # pragma: no cover - missing or broken install
    TkinterDnD = None
    _DnDMixin = object


def drop_types(tkdnd_version: str, is_mac: bool = None) -> tuple:
    """Drag types to accept. Browsers differ in what a dragged link carries:
    Chrome adds plain text, others (Dia, Arc...) may offer only a URL or an
    HTML link, so on macOS accept every type and pick the link out of what
    arrives. Only with tkdnd 2.10+: the tkdnd 2.9 build Intel Macs get is kept
    to text + files, which is known to work there."""
    from src.utils import paths
    is_mac = paths.IS_MAC if is_mac is None else is_mac
    try:
        major, minor = (int(x) for x in str(tkdnd_version).split(".")[:2])
    except ValueError:
        major, minor = 0, 0
    if is_mac and (major, minor) >= (2, 10):
        return (DND_ALL,)
    return (DND_TEXT, DND_FILES)


def links_from_drop(data: str, splitlist=None) -> list:
    """YouTube-looking links in dropped data: plain text / URLs, or dropped
    .url (Windows) / .webloc (macOS) link files."""
    import html
    import re
    text = (data or "").strip()
    if "<" in text or "&amp;" in text:  # an HTML link: <a href="...&amp;t=10">
        text = html.unescape(text)
    urls = re.findall(r"https?://[^\s{}\"'<>]+", text)
    if urls:
        return urls
    paths = splitlist(text) if splitlist else text.split()
    for path in paths:
        try:
            if path.lower().endswith(".url"):
                with open(path, encoding="utf-8", errors="replace") as f:
                    urls += [ln.split("=", 1)[1].strip() for ln in f if ln.upper().startswith("URL=")]
            elif path.lower().endswith(".webloc"):
                import plistlib
                with open(path, "rb") as f:
                    url = plistlib.load(f).get("URL")
                if url:
                    urls.append(url)
        except (OSError, ValueError):
            continue
    return urls


def _mix_hex(a: str, b: str, t: float) -> str:
    ra = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    rb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02X%02X%02X" % tuple(round(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))


_STATUS_ICON = {
    DownloadStatus.PENDING: ("clock", "text_secondary"),
    DownloadStatus.DOWNLOADING: ("download", "accent_hover"),
    DownloadStatus.COMPLETED: ("check", "success"),
    DownloadStatus.FAILED: ("error", "error"),
    DownloadStatus.CANCELLED: ("close", "text_tertiary"),
    DownloadStatus.PAUSED: ("clock", "text_tertiary"),
}


class YouDownloaderApp(customtkinter.CTk, _DnDMixin):
    """Main application window"""

    def __init__(self):
        super().__init__()
        if paths.IS_MAC:
            # youdownloader:// links arrive as an Apple Event. Install the handler
            # the moment Tk exists, so a link that launched the app isn't missed;
            # it's queued and loaded once the window is ready (_check_link_inbox).
            try:
                from src.utils import links as _links
                self.createcommand("::tk::mac::LaunchURL", lambda url, *a: _links.post(str(url)))
            except Exception as e:
                logger.debug(f"LaunchURL handler unavailable: {e}")
        customtkinter.set_appearance_mode("dark")
        self.font_family = init_fonts(self)

        self.config = Config()
        self.logger = logger
        from src.utils import ytdlp_override
        ytdlp_source = "updated in the app" if ytdlp_override.state.get("active") else "built in"
        self.logger.info(f"Starting YouDownloader v{__version__} ({sys.platform}"
                         f"{', packaged' if paths.FROZEN else ', from source'}, "
                         f"yt-dlp {updater.ytdlp_version()}{' ' + ytdlp_source if paths.FROZEN else ''}, "
                         f"font {self.font_family})")
        if ytdlp_override.state.get("error"):
            self.logger.warning(f"The downloaded yt-dlp failed to load and was set aside; using the "
                                f"built-in one: {ytdlp_override.state['error']}")
        self._pending_release: Optional[app_update.Release] = None
        self._update_banner = None
        self._ytdlp_banner = None
        self._ytdlp_ready: Optional[str] = None

        # Remote JS-solver updates (opt-in). None until asked once.
        self.allow_remote = bool(self.config.get("js_runtime_consent"))
        # cookies.txt for signed-in (full quality) downloads; fall back to the
        # one imported into %LOCALAPPDATA%\YouDownloader.
        self.cookie_file = self.config.get("cookies_file") or None
        if self.cookie_file and not os.path.isfile(self.cookie_file):
            self.logger.warning("Configured cookies file is missing; ignoring it")
            self.cookie_file = None
        if not self.cookie_file:
            self.cookie_file = cookie_store.find_default()
            if self.cookie_file:
                self.config.set("cookies_file", self.cookie_file)

        self.queue = DownloadQueue()
        self.queue.allow_remote_components = self.allow_remote
        self.queue.cookie_file = self.cookie_file
        self.queue.set_status_callback(self.on_queue_update)
        self.apply_download_settings()

        self.ffmpeg_available, self.ffmpeg_path = check_ffmpeg()
        if not self.ffmpeg_available:
            self.logger.warning("FFmpeg not found in PATH")
        self.js_runtime_available = self._check_js_runtime()
        if not self.js_runtime_available:
            self.logger.warning("No JavaScript runtime found (deno, node). Downloads may be throttled.")

        # One dark "space" theme.
        self.theme = "space"
        self.palette = SPACE
        p = self.palette

        # Window
        self.title("YouDownloader")
        width = self.config.get("window_width", 940)
        height = self.config.get("window_height", 900)
        x, y = self.config.get("window_x"), self.config.get("window_y")
        try:  # keep it on screen (e.g. a 13" Mac, or a monitor that's gone)
            scale = customtkinter.ScalingTracker.get_window_scaling(self)
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            width = max(760, min(int(width), int(sw / scale) - 40))
            height = max(720, min(int(height), int(sh / scale) - 100))
            if x is not None and y is not None and not (-50 < int(x) < sw - 100 and 0 <= int(y) < sh - 100):
                x = y = None
        except Exception:
            pass
        self.geometry(f"{width}x{height}+{x}+{y}" if x is not None and y is not None else f"{width}x{height}")
        if self.config.get("window_maximized"):
            self.after(0, lambda: self.state("zoomed"))
        self.configure(fg_color=p.bg)
        self.minsize(760, 720)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # State
        self.download_path = self.config.get("download_path") or Config.DEFAULT_CONFIG["download_path"]
        self.current_format = FormatManager.normalize_mode(self.config.get("format"))
        self.current_quality = FormatManager.normalize_quality(self.current_format, self.config.get("quality"))
        self._queue_dirty = False
        self._queue_was_running = False
        self._queue_rows: Dict[int, Dict[str, Any]] = {}
        self._queue_signature = None
        self._last_autofill: Optional[str] = None
        self._link_message_for: Optional[str] = None  # the link the message under the link box is about
        self._link_message_shown = False
        self._link_message_tone = "error"
        self._auto_preview_job = None
        self._previewed_url: Optional[str] = None
        self.download_state = "idle"
        self._run_before: set = set()  # ids of items already finished when the list last started
        self.cached_video_info: Optional[Dict[str, Any]] = None
        self.info_fetch_thread: Optional[threading.Thread] = None

        # Our icon + a title bar tinted to the void (CTk applies its own ~200ms in).
        self.after(300, lambda: (set_window_icon(self),
                                 winsys.style_window(self, caption=p.bg, text=p.text_secondary, border=p.bg)))

        self.create_ui()
        self.setup_shortcuts()
        self._setup_drag_and_drop()
        self.bind("<FocusIn>", self._on_window_focus, add="+")

        self.refresh_queue_display()
        self.after(400, self._poll_queue)
        if self.config.get("js_runtime_consent") is None:
            self.after(600, self._prompt_js_consent)
        if paths.IS_MAC:
            self._setup_mac_app()
        self.exit_for_update = False
        self.after(1500, self._after_start_update_housekeeping)
        if app_update.can_self_install() and self.config.get("auto_check_updates", True):
            self.after(4000, lambda: self.check_for_app_update(manual=False))
        if paths.FROZEN and self.config.get("auto_check_updates", True) and \
                self.config.get("auto_update_ytdlp", True):
            self.after(9000, self._auto_update_ytdlp)

    # ===== platform =========================================================

    @property
    def is_downloading(self) -> bool:
        queue = getattr(self, "queue", None)
        return bool(queue and queue.is_running())

    def _setup_mac_app(self) -> None:
        """macOS app-menu hooks: Quit (⌘Q) saves state like closing the window,
        Preferences… (⌘,) opens Settings, clicking the Dock icon restores us."""
        try:
            self.createcommand("tk::mac::Quit", self.on_closing)
            self.createcommand("tk::mac::ShowPreferences", self._open_settings)
            self.createcommand("tk::mac::ReopenApplication", lambda *a: (self.deiconify(), self.lift()))
        except Exception as e:
            self.logger.debug(f"macOS app hooks unavailable: {e}")

    # ===== app updates ======================================================

    def _after_start_update_housekeeping(self) -> None:
        """Runs once the window is up: report an update that didn't take,
        drop the kept-back previous version (macOS) and old downloads."""
        pending = self.config.get("pending_update_version")
        if pending:
            self.config.set("pending_update_version", None)
            if app_update.is_newer(pending):
                self.logger.error(f"The update to {pending} didn't install (still {__version__}); "
                                  f"see {app_update.update_log_path()}")
                ConfirmDialog.show(
                    self, "The update didn't install",
                    f"YouDownloader {pending} couldn't be installed automatically, so you're still on "
                    f"{__version__}. You can download it from the release page instead.\n\n"
                    f"Details: {app_update.update_log_path()}",
                    lambda yes: yes and winsys.open_url(app_update.RELEASES_PAGE),
                    confirm_text="Open download page", cancel_text="Not now")
            else:
                self.logger.info(f"Updated to {__version__}")
        if paths.FROZEN:
            if paths.IS_MAC:
                app_update.cleanup_previous_bundle()
            app_update.cleanup_stale_downloads()

    def check_for_app_update(self, manual: bool = False,
                             on_result: Optional[Callable] = None) -> None:
        """Ask GitHub for a newer release (background thread).

        Automatic checks show a banner; manual ones (Settings) report back via
        `on_result(release_or_None, error_or_None)`.
        """
        def work():
            try:
                release, error = app_update.check(), None
            except app_update.UpdateError as e:
                release, error = None, str(e)
            except Exception as e:  # never let an update check crash the app
                self.logger.error(f"Update check failed: {e}", exc_info=True)
                release, error = None, "The update check failed."
            self.after(0, lambda: self._on_update_checked(release, error, manual, on_result))
        threading.Thread(target=work, daemon=True).start()

    def _on_update_checked(self, release, error, manual, on_result) -> None:
        if error:
            self.logger.info(f"Update check: {error}")
        if release is not None:
            self._pending_release = release
        if on_result:
            on_result(release, error)
            return
        if release is None:
            if manual and not error:
                InfoDialog.show(self, "You're up to date", f"YouDownloader {__version__} is the latest version.")
            elif manual:
                ErrorDialog.show(self, "Couldn't check for updates", error)
            return
        if manual:
            self.show_update(release)
        elif self.config.get("skipped_update_version") != release.version:
            self._show_update_banner()

    def _show_update_banner(self) -> None:
        rel = self._pending_release
        if not rel or not hasattr(self, "_banner_parent"):
            return
        if self._update_banner is not None:
            try:
                self._update_banner.destroy()
            except Exception:
                pass
        first_line = next((ln.strip(" -*#") for ln in rel.notes.splitlines() if ln.strip(" -*#")), "")
        self._update_banner = InlineBanner(
            self._banner_parent, self.palette, tone="info",
            headline=f"YouDownloader {rel.version} is available",
            detail=(first_line[:90] + ("…" if len(first_line) > 90 else "")) or f"You have {__version__}.",
            action_text="Update", on_action=lambda: self.show_update(rel),
            on_dismiss=lambda: self.config.set("skipped_update_version", rel.version))
        # Just above the link bar, which lives exactly as long as this banner:
        # CustomTkinter re-runs pack(**same kwargs) on DPI changes, so `before`
        # must never point at a widget that can be destroyed first (e.g. a
        # dismissed banner), or the rescale fails and leaves the window faded.
        self._update_banner.pack(fill="x", pady=(0, SPACING.md), before=self._url_row)

    def show_update(self, release) -> None:
        def install(prep) -> None:
            if self.is_downloading or self.queue.is_running():
                # A download started while the update was downloading.
                app_update.discard(prep)
                InfoDialog.show(self, "Update postponed", "A download started in the meantime. Update again "
                                "once it has finished.")
                return
            try:
                app_update.launch(prep)
            except Exception as e:
                self.logger.error(f"Update install failed: {e}", exc_info=True)
                app_update.discard(prep)
                ErrorDialog.show(self, "Couldn't install the update", str(e))
                return
            self.logger.info(f"Installing update {release.version}; quitting")
            self.config.set("pending_update_version", release.version)
            self.exit_for_update = True  # main.py exits the process right after mainloop
            self.on_closing()

        if self.is_downloading or self.queue.is_running():
            # Quitting mid-download would leave ffmpeg running (and on Windows
            # holding files the installer must replace), so don't.
            InfoDialog.show(self, "Finish your downloads first",
                            f"YouDownloader {release.version} is ready to install, but a download is "
                            "still running. Let it finish (or press Stop), then click Update again.")
            return
        UpdateDialog.show(self, release, install)

    # ===== settings / integration ============================================

    def _prompt_js_consent(self) -> None:
        def on_choice(enabled: bool) -> None:
            self.allow_remote = bool(enabled)
            self.queue.allow_remote_components = self.allow_remote
            self.config.set("js_runtime_consent", bool(enabled))
        ConsentDialog.show(self, on_choice)

    def apply_download_settings(self) -> None:
        """Push download preferences from Config into the queue."""
        self.queue.embed_metadata = bool(self.config.get("embed_metadata", True))
        self.queue.download_subtitles = bool(self.config.get("auto_download_subtitles"))
        self.queue.subtitle_language = self.config.get("subtitle_language") or "en"

    def set_cookie_file(self, path: Optional[str]) -> None:
        self.cookie_file = path
        self.queue.cookie_file = path
        self.config.set("cookies_file", path or "")
        self.refresh_signin_chip()

    def refresh_signin_chip(self) -> None:
        info = cookie_store.inspect(self.cookie_file)
        if self.cookie_file and info["ok"] and info["signed_in"]:
            self.header.set_chip("Signed in  ·  full quality", self.palette.success)
        else:
            self.header.set_chip("Not signed in  ·  HD may be limited", self.palette.warning)

    def _effects(self) -> bool:
        return bool(self.config.get("visual_effects_enabled", True))

    def _on_window_focus(self, event) -> None:
        """Auto-fill a copied YouTube link when the link box is empty."""
        if event.widget is not self:
            return
        try:
            if self.url_entry.get().strip():
                return
            clip = self.clipboard_get().strip()
        except Exception:
            return
        if not clip or clip == self._last_autofill or "\n" in clip or len(clip) > 300:
            return
        if validate_youtube_url(clip)[0]:
            self._last_autofill = clip
            self.url_entry.insert(0, clip)
            self._update_url_validity()
            self.fetch_video_info()

    def _paste_link(self) -> None:
        try:
            clip = self.clipboard_get().strip()
        except Exception:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, clip)
        self._update_url_validity()
        if validate_youtube_url(clip)[0]:
            self.fetch_video_info()

    def _update_ytdlp(self, on_done=None) -> None:
        def work():
            ok, msg = updater.update_ytdlp()
            self.logger.info(msg)

            def finish():
                if ok and "Restart" in msg:
                    ConfirmDialog.show(self, "yt-dlp updated", msg,
                                       lambda yes: yes and self.restart_app(),
                                       confirm_text="Restart now", cancel_text="Later")
                else:
                    (InfoDialog if ok else ErrorDialog).show(self, "yt-dlp update", msg)
                if on_done:
                    on_done(ok, msg)
            self.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    def _auto_update_ytdlp(self) -> None:
        """Packaged app: fetch a newer yt-dlp in the background (YouTube fixes
        arrive days after YouTube breaks something); it's used after a restart."""
        from src.utils import ytdlp_override

        def work():
            try:
                ok, msg, new = ytdlp_override.install()
            except Exception as e:
                self.logger.error(f"yt-dlp auto-update failed: {e}", exc_info=True)
                return
            self.logger.info(f"yt-dlp auto-update: {msg}")
            if ok and new:
                self.after(0, lambda: self._show_ytdlp_ready(new))
        threading.Thread(target=work, daemon=True).start()

    def _show_ytdlp_ready(self, version: str) -> None:
        self._ytdlp_ready = version
        if getattr(self, "_ytdlp_banner", None) is not None:
            try:
                self._ytdlp_banner.destroy()
            except Exception:
                pass
        if not hasattr(self, "_url_row"):
            return
        self._ytdlp_banner = InlineBanner(
            self._banner_parent, self.palette, tone="info", headline="YouTube fixes are ready",
            detail=f"yt-dlp {version} is downloaded. Restart YouDownloader to use it.",
            action_text="Restart", on_action=self.restart_app)
        self._ytdlp_banner.pack(fill="x", pady=(0, SPACING.md), before=self._url_row)

    def restart_app(self) -> None:
        if self.is_downloading or self.queue.is_running():
            InfoDialog.show(self, "Finish your downloads first",
                            "A download is still running. Let it finish (or press Stop), then restart.")
            return
        try:
            winsys.relaunch_after_exit()
        except Exception as e:
            self.logger.error(f"Restart failed: {e}", exc_info=True)
            ErrorDialog.show(self, "Couldn't restart", f"{e}\n\nClose and reopen YouDownloader instead.")
            return
        self.logger.info("Restarting")
        self.exit_for_update = True  # main.py exits the process right after mainloop
        self.on_closing()

    def _open_settings(self) -> None:
        SettingsDialog.show(self)

    def rebuild_ui(self) -> None:
        """Re-create the window contents (used when setup notices are re-shown)."""
        url = self.url_entry.get() if hasattr(self, "url_entry") else ""
        loc = self.location_entry.get() if hasattr(self, "location_entry") else self.download_path
        for child in list(self.grid_slaves()):
            child.destroy()
        self._queue_rows, self._queue_signature = {}, None
        self.create_ui()
        try:
            self.url_entry.insert(0, url)
            self.location_entry.delete(0, "end")
            self.location_entry.insert(0, loc)
            self._update_url_validity()
        except Exception:
            pass
        self.refresh_queue_display()
        self._set_primary_state("idle")

    def apply_palette(self, name: str) -> None:
        """Kept for compatibility; there is a single dark palette now."""
        self.rebuild_ui()

    def setup_shortcuts(self) -> None:
        # ⌘ on macOS, Ctrl elsewhere. On macOS ⌘Q and ⌘, come from the app
        # menu (see _setup_mac_app), so they aren't bound here.
        mod = "Command" if paths.IS_MAC else "Control"
        self.bind(f"<{mod}-d>", lambda e: self.start_download())
        self.bind(f"<{mod}-s>", lambda e: self.stop_current())
        self.bind(f"<{mod}-o>", lambda e: self.browse_folder())
        if not paths.IS_MAC:
            self.bind("<Control-q>", lambda e: self.on_closing())
            self.bind("<Control-comma>", lambda e: self._open_settings())
        self.bind("<F5>", lambda e: self.fetch_video_info())
        self.focus_set()

    def _setup_drag_and_drop(self) -> None:
        """Drop a link (from a browser's address bar, a tab, or a link file)
        anywhere on the window: it goes into the link box and is previewed."""
        self.dnd_available = False
        if TkinterDnD is None:
            return
        try:
            version = TkinterDnD.require(self)
            self.drop_target_register(*drop_types(version))
            self.dnd_bind("<<DropEnter>>", self._on_drop_enter)
            self.dnd_bind("<<DropLeave>>", self._on_drop_leave)
            self.dnd_bind("<<Drop>>", self._on_drop)
            self.dnd_available = True
        except Exception as e:
            self.logger.info(f"Drag and drop unavailable: {e}")

    def _on_drop_enter(self, event):
        try:
            self._url_row.configure(border_color=self.palette.accent)
        except Exception:
            pass
        return event.action

    def _on_drop_leave(self, event):
        try:
            self._paint_url_border()
        except Exception:
            pass
        return event.action

    def _on_drop(self, event):
        self._on_drop_leave(event)
        links = [u for u in links_from_drop(event.data, self.tk.splitlist) if validate_youtube_url(u)[0]]
        if not links:
            # Helps support a browser whose drags carry something unexpected
            # (shows up in Copy diagnostics).
            self.logger.info(f"Drop without a YouTube link: type={getattr(event, 'type', '?')!r} "
                             f"offered={getattr(event, 'types', '?')!r} data={str(event.data)[:200]!r}")
            self._show_link_message("That isn't a YouTube link.")
            return event.action
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, links[0])
        self._update_url_validity()
        self.fetch_video_info()
        if len(links) > 1:
            self._show_link_message(f"Dropped {len(links)} links: the first is in the link box. "
                                    "Use Paste list to download them all.", tone="info")
        return event.action

    def _check_js_runtime(self) -> bool:
        # main.py ran paths.setup_tool_path(): bundled deno and ~/.deno/bin are on PATH.
        return any([shutil.which('deno'), shutil.which('node'), shutil.which('bun')])

    # ===== layout ==============================================================

    def create_ui(self) -> None:
        p = self.palette
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self.header = SpaceHeader(self, p, on_settings=self._open_settings, on_chip=self._open_settings,
                                  effects_enabled=self._effects, content_width=lambda: CONTENT_MAX_WIDTH)
        self.header.grid(row=0, column=0, sticky="ew")
        self.refresh_signin_chip()

        # Page: a centered column between two flexible spacers.
        self.page = customtkinter.CTkFrame(self, fg_color=p.bg, corner_radius=0)
        self.page.grid(row=1, column=0, sticky="nsew")
        self.page.grid_columnconfigure(0, weight=1)
        self.page.grid_columnconfigure(2, weight=1)
        self.page.grid_rowconfigure(1, weight=1)
        self.page.bind("<Configure>", self._fit_column)

        # The input card, then one Downloads list (progress and results live in its rows).
        self._build_compose_card(row=0)
        self._build_queue_card(row=1)

    def _fit_column(self, event=None) -> None:
        scale = customtkinter.ScalingTracker.get_widget_scaling(self)
        width = (event.width if event else self.page.winfo_width())
        col = min(int(CONTENT_MAX_WIDTH * scale), max(200, width - int(2 * CONTENT_GUTTER * scale)))
        self.page.grid_columnconfigure(1, minsize=col)

    def _card(self, row: int, pady=(0, SPACING.md), sticky="ew") -> customtkinter.CTkFrame:
        card = customtkinter.CTkFrame(self.page, corner_radius=RADIUS.lg, fg_color=self.palette.surface,
                                      border_width=BORDER.hairline, border_color=self.palette.border_subtle)
        card.grid(row=row, column=1, sticky=sticky, pady=pady)
        return card

    def _overline(self, parent, text: str) -> customtkinter.CTkLabel:
        return customtkinter.CTkLabel(parent, text=tracked(text), font=TYPE.overline,
                                      text_color=self.palette.text_tertiary, anchor="w", height=16)

    def _field(self, parent, label: str) -> customtkinter.CTkFrame:
        box = customtkinter.CTkFrame(parent, fg_color="transparent")
        self._overline(box, label).pack(anchor="w", pady=(0, SPACING.xs + 2))
        return box

    def _build_compose_card(self, row: int) -> None:
        p = self.palette
        card = self._card(row, pady=(0, SPACING.md))
        inner = customtkinter.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=SPACING.xl, pady=SPACING.xl)

        self._build_banners(inner)

        # --- Link bar: icon · entry · validity · Paste · Preview ---
        bar = customtkinter.CTkFrame(inner, fg_color=p.surface_raised, corner_radius=RADIUS.md + 2,
                                     border_width=BORDER.hairline, border_color=p.border_input,
                                     height=HEIGHT.url_bar)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self._url_row = bar
        link_icon = icons.icon("link", 18, p.text_tertiary)
        customtkinter.CTkLabel(bar, text="" if link_icon else "↗", image=link_icon, width=24).pack(
            side="left", padx=(SPACING.md + 2, SPACING.xs))
        self.url_entry = FieldEntry(bar, p, border_width=0, fg_color=p.surface_raised, font=TYPE.body_lg,
                                    placeholder_text=("Paste or drop a YouTube link" if TkinterDnD else "Paste a YouTube link"),
                                    height=HEIGHT.url_bar - 12)
        self.url_entry.pack(side="left", fill="x", expand=True)
        self.url_entry.bind("<FocusIn>", lambda e: self._paint_url_border(focused=True), add="+")
        self.url_entry.bind("<FocusOut>", lambda e: self._paint_url_border(focused=False), add="+")
        self.url_entry.bind("<KeyRelease>", lambda e: self._on_link_edited())
        self.url_entry.bind("<Return>", lambda e: self.fetch_video_info())

        self.url_validity_pip = StatusPip(bar, color=p.text_disabled, size=7, bg=p.surface_raised)
        self.url_validity_pip.hide()
        self.url_validity_pip.pack(side="left", padx=(SPACING.xs, SPACING.sm))
        # No Preview button: a valid link previews by itself (Enter / F5 still do it).
        SecondaryButton(bar, p, text="Paste", icon="paste", height=HEIGHT.button_sm, width=86,
                        fg_color=p.surface_hover, border_width=0, command=self._paste_link
                        ).pack(side="right", padx=(SPACING.xs, SPACING.sm))

        # Problems with the link are explained here, not in a dialog.
        self.link_message = customtkinter.CTkLabel(inner, text="", font=TYPE.caption, text_color=p.error,
                                                   anchor="w", justify="left", wraplength=780, height=18)

        # --- Preview (hidden until fetched) ---
        self.info_frame = customtkinter.CTkFrame(inner, fg_color=p.surface_raised, corner_radius=RADIUS.md + 2)
        self.thumbnail_label = customtkinter.CTkLabel(self.info_frame, text="", width=128, height=72,
                                                      fg_color=p.surface_hover, corner_radius=RADIUS.sm)
        self.thumbnail_label.pack(side="left", padx=SPACING.md, pady=SPACING.md)
        text_col = customtkinter.CTkFrame(self.info_frame, fg_color="transparent")
        text_col.pack(side="left", fill="both", expand=True, padx=(0, SPACING.md), pady=SPACING.md)
        self.info_title = customtkinter.CTkLabel(text_col, text="", font=TYPE.title, text_color=p.text_primary,
                                                 anchor="w", justify="left", wraplength=560)
        self.info_title.pack(anchor="w", fill="x")
        self.info_label = customtkinter.CTkLabel(text_col, text="", font=TYPE.caption,
                                                 text_color=p.text_secondary, anchor="w", justify="left")
        self.info_label.pack(anchor="w", fill="x", pady=(SPACING.xs, 0))

        # --- Form grid ---
        form = customtkinter.CTkFrame(inner, fg_color="transparent")
        form.pack(fill="x", pady=(SPACING.xl, 0))
        form.grid_columnconfigure(0, weight=3, uniform="form")
        form.grid_columnconfigure(1, weight=2, uniform="form")

        f = self._field(form, "Format")
        f.grid(row=0, column=0, sticky="ew", padx=(0, SPACING.md))
        self.format_selector = customtkinter.CTkSegmentedButton(
            f, values=FormatManager.labels(),
            command=lambda label: self.on_format_change(FormatManager.mode_from_label(label)),
            height=HEIGHT.entry, corner_radius=RADIUS.md, font=TYPE.button, border_width=3,
            fg_color=p.surface_raised, selected_color=p.accent_fill, selected_hover_color=p.accent_fill_hover,
            unselected_color=p.surface_raised, unselected_hover_color=p.surface_hover,
            text_color=p.text_primary, text_color_disabled=p.text_disabled,
        )
        self.format_selector.set(FormatManager.label(self.current_format))
        self.format_selector.pack(fill="x")

        f = self._field(form, "Quality")
        f.grid(row=0, column=1, sticky="ew")
        self.quality_combo = SelectButton(f, p, FormatManager.get_quality_options(self.current_format),
                                          command=lambda v: self.config.set("quality", v))
        self.quality_combo.set(self.current_quality)
        self.quality_combo.pack(fill="x")

        f = self._field(form, "File name")
        f.grid(row=1, column=0, sticky="ew", padx=(0, SPACING.md), pady=(SPACING.lg, 0))
        self.name_entry = FieldEntry(f, p, placeholder_text="Same as the video title")
        self.name_entry.pack(fill="x")

        f = self._field(form, "Clip  (optional)")
        f.grid(row=1, column=1, sticky="ew", pady=(SPACING.lg, 0))
        clip_row = customtkinter.CTkFrame(f, fg_color="transparent")
        clip_row.pack(fill="x")
        clip_row.grid_columnconfigure((0, 2), weight=1)
        self.clip_start_entry = FieldEntry(clip_row, p, placeholder_text="Start  0:00", justify="center")
        self.clip_start_entry.grid(row=0, column=0, sticky="ew")
        customtkinter.CTkLabel(clip_row, text="→", font=TYPE.body, text_color=p.text_tertiary, width=24
                               ).grid(row=0, column=1)
        self.clip_end_entry = FieldEntry(clip_row, p, placeholder_text="End", justify="center")
        self.clip_end_entry.grid(row=0, column=2, sticky="ew")

        f = self._field(form, "Save to")
        f.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(SPACING.lg, 0))
        loc_row = customtkinter.CTkFrame(f, fg_color="transparent")
        loc_row.pack(fill="x")
        self.location_entry = FieldEntry(loc_row, p)
        self.location_entry.insert(0, self.download_path or "")
        self.location_entry.pack(side="left", fill="x", expand=True, padx=(0, SPACING.sm))
        SecondaryButton(loc_row, p, text="Browse", icon="folder", width=112, command=self.browse_folder).pack(side="left")

        # --- Actions ---
        actions = customtkinter.CTkFrame(inner, fg_color="transparent")
        actions.pack(fill="x", pady=(SPACING.xl, 0))
        self.primary_btn = PrimaryButton(actions, p, text="Download", icon="download",
                                         command=self.on_primary_action)
        self.primary_btn._cur_fg = p.accent_fill
        self.primary_btn.pack(side="left", fill="x", expand=True, padx=(0, SPACING.sm))
        self.queue_btn = SecondaryButton(actions, p, text="Add for later", icon="add", width=168,
                                         height=HEIGHT.button_lg, command=self.add_to_queue)
        self.queue_btn.pack(side="left")

    def _build_banners(self, parent) -> None:
        self._banner_parent = parent
        self._update_banner = None
        self._ytdlp_banner = None
        if self._pending_release and self.config.get("skipped_update_version") != self._pending_release.version:
            self.after_idle(self._show_update_banner)
        if getattr(self, "_ytdlp_ready", None):
            self.after_idle(lambda: self._show_ytdlp_ready(self._ytdlp_ready))
        banners = []
        if not self.ffmpeg_available and not self.config.get("banner_dismissed_ffmpeg"):
            detail = "Needed for MOV, MP3 and WAV, and to merge HD video with its audio."
            if paths.IS_MAC:
                detail += " Install it with: brew install ffmpeg"
            banners.append(dict(tone="warning", headline="FFmpeg not found", detail=detail,
                                on_dismiss=lambda: self.config.set("banner_dismissed_ffmpeg", True)))
        age = updater.ytdlp_age_days()
        if age is not None and age > updater.STALE_AFTER_DAYS and \
                self.config.get("banner_dismissed_ytdlp") != updater.ytdlp_version():
            holder = {}
            detail, on_action = ("YouTube changes often and old versions start failing.",
                                 lambda: (holder["b"].destroy(), self._update_ytdlp()))
            banners.append(dict(tone="warning", headline=f"yt-dlp is {age} days old",
                                detail=detail, action_text="Update", on_action=on_action,
                                on_dismiss=lambda: self.config.set("banner_dismissed_ytdlp",
                                                                   updater.ytdlp_version()),
                                _holder=holder))
        if not self.js_runtime_available and not self.config.get("banner_dismissed_deno"):
            banners.append(dict(tone="info", headline="Deno not found",
                                detail="Install it for much faster downloads"
                                       + (" (brew install deno)." if paths.IS_MAC else "."),
                                action_text="Install", on_action=self._run_deno_install,
                                on_dismiss=lambda: self.config.set("banner_dismissed_deno", True)))
        for spec in banners:
            holder = spec.pop("_holder", None)
            b = InlineBanner(parent, self.palette, **spec)
            b.pack(fill="x", pady=(0, SPACING.md))
            if holder is not None:
                holder["b"] = b

    def _build_queue_card(self, row: int) -> None:
        p = self.palette
        card = self._card(row, pady=(0, SPACING.xl), sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        header = customtkinter.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.lg + 2, SPACING.sm))
        customtkinter.CTkLabel(header, text="Downloads", font=TYPE.title, text_color=p.text_primary).pack(side="left")
        self.queue_count = customtkinter.CTkLabel(header, text="0", font=TYPE.caption_med, height=22,
                                                  text_color=p.text_secondary, fg_color=p.surface_raised,
                                                  corner_radius=RADIUS.sm, padx=8)
        self.queue_count.pack(side="left", padx=(SPACING.sm, 0))
        self.queue_summary = customtkinter.CTkLabel(header, text="", font=TYPE.caption, height=22,
                                                    text_color=p.text_secondary)
        self.queue_summary.pack(side="left", padx=(SPACING.sm, 0))

        # Start all / Pause all: shown only when there's something to start or pause.
        self.start_queue_btn = SecondaryButton(header, p, text="Start all", icon="play", width=112,
                                               height=HEIGHT.button_sm, command=self.start_queue)
        self._start_btn_shown = False
        self._clear_btn = GhostButton(header, p, text="Clear finished", icon="clear", command=self.clear_completed)
        self._clear_btn.pack(side="right", padx=(0, SPACING.sm))
        GhostButton(header, p, text="Paste list", icon="list", command=self._paste_list).pack(
            side="right", padx=(0, SPACING.xs))

        self.queue_scroll = customtkinter.CTkScrollableFrame(
            card, fg_color="transparent", scrollbar_button_color=p.border_strong,
            scrollbar_button_hover_color=p.text_disabled)
        self.queue_scroll.grid(row=1, column=0, sticky="nsew", padx=SPACING.md, pady=(0, SPACING.md))
        # Rows changing size, and the card itself growing or shrinking (e.g. when a preview opens).
        self.queue_scroll.bind("<Configure>", lambda e: self.after_idle(self._sync_queue_scrollbar), add="+")
        try:
            self.queue_scroll._parent_canvas.bind("<Configure>", lambda e: self.after_idle(self._sync_queue_scrollbar),
                                                  add="+")
        except Exception:
            pass

    def _sync_queue_scrollbar(self) -> None:
        """Show the queue's scrollbar only when the rows don't fit (CTk always shows it)."""
        try:
            scroll = self.queue_scroll
            canvas, bar = scroll._parent_canvas, scroll._scrollbar
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            fits = bbox is None or (bbox[3] - bbox[1]) <= canvas.winfo_height() + 1
            if fits:
                canvas.yview_moveto(0)
                bar.grid_remove()
            else:
                bar.grid()
        except Exception:
            pass  # Private CTk internals; a visible scrollbar is the harmless fallback.

    def _run_deno_install(self) -> None:
        bat = os.path.join(paths.PROJECT_ROOT, "install_deno.bat")
        try:
            if paths.IS_WINDOWS and os.path.isfile(bat):
                os.startfile(bat)  # type: ignore[attr-defined]
            else:
                winsys.open_url("https://docs.deno.com/runtime/getting_started/installation/")
        except Exception as e:
            self.logger.error(f"Could not launch Deno installer: {e}")
            ErrorDialog.show(self, "Couldn't start the installer", str(e))

    # ===== link + preview =========================================================

    def _update_url_validity(self) -> None:
        url = self.url_entry.get().strip()
        if url != self._link_message_for:
            self._clear_link_message()
        if not url:
            self.url_validity_pip.hide()
            return
        is_valid, _ = validate_youtube_url(url)
        self.url_validity_pip.set_color(self.palette.success if is_valid else self.palette.error)

    def _paint_url_border(self, focused: Optional[bool] = None) -> None:
        if focused is None:
            try:
                focused = self.focus_get() is self.url_entry._entry
            except Exception:
                focused = False
        p = self.palette
        error = self._link_message_for is not None and self._link_message_tone == "error"
        color = p.error if error else (p.accent if focused else p.border_input)
        self._url_row.configure(border_color=color)

    def _show_link_message(self, text: str, tone: str = "error") -> None:
        """A line under the link box: a problem with the link (instead of a dialog), or a note.

        It goes away as soon as the link box changes.
        """
        self._link_message_for = self.url_entry.get().strip()
        self._link_message_tone = tone
        self.link_message.configure(text=text, text_color=self.palette.error if tone == "error"
                                    else self.palette.text_secondary)
        if not self._link_message_shown:
            self._link_message_shown = True
            self.link_message.pack(fill="x", padx=(SPACING.xs, 0), pady=(SPACING.xs + 2, 0), after=self._url_row)
        self._paint_url_border()

    def _clear_link_message(self) -> None:
        if self._link_message_for is None:
            return
        self._link_message_for = None
        if self._link_message_shown:
            self._link_message_shown = False
            self.link_message.pack_forget()
        self._paint_url_border()

    @staticmethod
    def _sentence(text: Optional[str]) -> str:
        text = (text or "Check the link and try again").strip()
        return text if text.endswith((".", "!", "?")) else text + "."

    @staticmethod
    def _short_error(error: Exception) -> str:
        """First line of a yt-dlp error, without its "ERROR: [youtube] id:" prefix."""
        text = (str(error).strip().splitlines() or [""])[0]
        text = re.sub(r"^ERROR:\s*", "", text)
        text = re.sub(r"^\[[^\]]+\]\s*[\w-]+:\s*", "", text)
        return text[:200] + ("…" if len(text) > 200 else "")

    def _on_link_edited(self) -> None:
        """Typing or pasting into the link box: preview a valid link after a short pause."""
        self._update_url_validity()
        if self._auto_preview_job:
            self.after_cancel(self._auto_preview_job)
            self._auto_preview_job = None
        url = self.url_entry.get().strip()
        if url and url != self._previewed_url and validate_youtube_url(url)[0]:
            self._auto_preview_job = self.after(600, self._auto_preview)

    def _auto_preview(self) -> None:
        self._auto_preview_job = None
        url = self.url_entry.get().strip()
        if not url or url == self._previewed_url or not validate_youtube_url(url)[0]:
            return
        if self.info_fetch_thread and self.info_fetch_thread.is_alive():
            self._auto_preview_job = self.after(400, self._auto_preview)  # try again once it finishes
            return
        self.fetch_video_info()

    def fetch_video_info(self) -> None:
        if self._auto_preview_job:
            self.after_cancel(self._auto_preview_job)
            self._auto_preview_job = None
        url = self.url_entry.get().strip()
        if not url:
            self._show_link_message("Paste a YouTube link first.")
            self.url_entry.focus_set()
            return
        is_valid, error_msg = validate_youtube_url(url)
        if not is_valid:
            self._show_link_message(f"That isn't a YouTube link. {self._sentence(error_msg)}")
            return
        if self.info_fetch_thread and self.info_fetch_thread.is_alive():
            return
        self._previewed_url = url
        self._clear_link_message()

        def still_current() -> bool:
            return self.url_entry.get().strip() == url

        def failed(message: str) -> None:
            if still_current():
                self.info_frame.pack_forget()
                self.name_entry.configure(placeholder_text="Same as the video title")
                self.url_validity_pip.set_color(self.palette.error)
                self._show_link_message(message)

        def fetch_thread():
            try:
                engine = DownloadEngine(allow_remote_components=self.allow_remote, cookie_file=self.cookie_file)
                info = engine.get_video_info(url)
                if info:
                    self.cached_video_info = info
                    self.after(0, lambda: still_current() and self.display_video_info(info))
                else:
                    self.after(0, lambda: failed("Couldn't load that video. It may be private, removed, "
                                                 "or not available in your country."))
            except Exception as e:
                self.logger.error(f"Error fetching video info: {e}", exc_info=True)
                message = f"Couldn't load that video: {self._short_error(e)}"
                self.after(0, lambda: failed(message))

        self.info_fetch_thread = threading.Thread(target=fetch_thread, daemon=True)
        self.info_fetch_thread.start()
        self.info_title.configure(text="Looking up video…")
        self.info_label.configure(text="")
        self.thumbnail_label.configure(image=None)
        self.info_frame.pack(fill="x", pady=(SPACING.md, 0), after=self._url_row)

    def display_video_info(self, info: Dict[str, Any]) -> None:
        title = info.get('title') or 'Untitled'
        duration = info.get('duration')
        parts = [x for x in (info.get('uploader') or "", format_duration(duration) if duration else "") if x]
        if info.get('is_playlist'):
            parts.append(f"Playlist  ·  {info.get('playlist_count', 0)} videos")
        self.info_title.configure(text=title if len(title) <= 110 else title[:108] + "…")
        self.info_label.configure(text="   ·   ".join(parts))
        self.name_entry.configure(placeholder_text=f"{title[:60]}")

        thumbnail_url = info.get('thumbnail')
        if thumbnail_url:
            import requests
            from PIL import Image

            def load_thumbnail():
                try:
                    response = requests.get(thumbnail_url, timeout=6)
                    if response.status_code == 200:
                        img = icons.rounded(Image.open(io.BytesIO(response.content)), (128, 72), RADIUS.sm)
                        self.after(0, lambda: self.thumbnail_label.configure(image=img, fg_color="transparent"))
                except Exception:
                    pass
            threading.Thread(target=load_thumbnail, daemon=True).start()
        self.info_frame.pack(fill="x", pady=(SPACING.md, 0), after=self._url_row)

    def browse_folder(self) -> None:
        folder = tkinter.filedialog.askdirectory(initialdir=self.download_path)
        if folder:
            self.download_path = folder
            self.location_entry.delete(0, "end")
            self.location_entry.insert(0, folder)
            self.config.set("download_path", folder)

    def on_format_change(self, value: str) -> None:
        self.current_format = value
        self.config.set("format", value)
        options = FormatManager.get_quality_options(value)
        self.quality_combo.configure(values=options)
        current = self.quality_combo.get()
        quality = current if current in options else FormatManager.normalize_quality(value, None)
        self.quality_combo.set(quality)
        self.current_quality = quality
        self.config.set("quality", quality)

    def _cached_info_for(self, url: str) -> Optional[Dict[str, Any]]:
        info = self.cached_video_info
        return info if info and info.get('url') == url else None

    def _check_ffmpeg_for(self, format_mode: str) -> bool:
        if FormatManager.needs_ffmpeg(format_mode) and not self.ffmpeg_available:
            ErrorDialog.show(self, "FFmpeg required",
                             f"{FormatManager.label(format_mode)} downloads need FFmpeg. "
                             "Install it, add it to your PATH, then restart the app.")
            return False
        return True

    # ===== form inputs ============================================================

    def _validated_inputs(self):
        """Common validation for Download / Add to queue. Returns a dict or None."""
        url = self.url_entry.get().strip()
        if not url:
            self._show_link_message("Paste a YouTube link first.")
            self.url_entry.focus_set()
            return None
        ok, err = validate_youtube_url(url)
        if not ok:
            self._show_link_message(f"That isn't a YouTube link. {self._sentence(err)}")
            return None
        output_path = self.location_entry.get().strip()
        ok, err = validate_path(output_path)
        if not ok:
            ErrorDialog.show(self, "Can't save there", err or "Choose another folder.")
            return None
        output_path = os.path.abspath(os.path.expanduser(output_path))
        if not self._check_ffmpeg_for(self.current_format):
            return None
        clip = self._read_clip()
        if clip is False:
            return None
        name = self._read_name()
        if name is False:
            return None
        return {"url": url, "output_path": output_path, "clip": clip, "name": name}

    def _read_clip(self):
        try:
            return parse_clip(self.clip_start_entry.get(), self.clip_end_entry.get())
        except ValueError as e:
            ErrorDialog.show(self, "Check the clip times", str(e))
            return False

    def _read_name(self):
        """Custom file name, None if blank, or False if invalid (after showing why)."""
        raw = self.name_entry.get().strip()
        if not raw:
            return None
        clean, err = validate_filename(raw, "." + FormatManager.extension(self.current_format))
        if err:
            ErrorDialog.show(self, "Check the file name", err)
            return False
        return clean

    def _clear_per_download_fields(self) -> None:
        """Clip and name apply to one download; clear them so the next isn't affected."""
        self.name_entry.configure(placeholder_text="Same as the video title")
        for entry in (self.clip_start_entry, self.clip_end_entry, self.name_entry):
            entry.delete(0, "end")
            # CTk only restores a placeholder on focus-out; do it now.
            if self.focus_get() is not getattr(entry, "_entry", None):
                try:
                    entry._activate_placeholder()
                except Exception:
                    pass

    # ===== queue adding ===========================================================

    def add_to_queue(self) -> None:
        """Add for later: into the list without starting (Start all or the row's play button starts it)."""
        self._add_from_form(start=False)

    def start_download(self) -> None:
        """Download: into the list, which starts it now (or right after what's downloading)."""
        self._add_from_form(start=True)

    def on_primary_action(self) -> None:
        self.start_download()

    def _add_from_form(self, start: bool, confirmed_playlist: bool = False) -> None:
        v = self._validated_inputs()
        if not v:
            return
        url = v["url"]
        format_mode, quality = self.current_format, self.quality_combo.get()
        cached = self._cached_info_for(url)

        if DownloadEngine.is_playlist_url(url) and not confirmed_playlist:
            count = cached.get("playlist_count") if cached and cached.get("is_playlist") else None
            what = f"all {count} videos" if count else "every video in it"
            ConfirmDialog.show(self, "Download the whole playlist?",
                               f"This link is a playlist. YouDownloader will save {what} into a new folder.",
                               lambda yes: yes and self._add_from_form(start, confirmed_playlist=True),
                               confirm_text="Download playlist" if start else "Add playlist")
            return

        def add(chosen_quality: str) -> None:
            item = DownloadItem(
                url=url, title=cached.get('title') if cached else None,
                format=format_mode, quality=chosen_quality, output_path=v["output_path"],
                clip_start=v["clip"][0], clip_end=v["clip"][1], custom_name=v["name"],
                status=DownloadStatus.PENDING if start else DownloadStatus.PAUSED,
            )
            try:
                self.queue.add(item)
            except Exception as e:
                self.logger.error(f"Error adding to the list: {e}", exc_info=True)
                ErrorDialog.show(self, "Couldn't add the download", str(e))
                return
            # Ready for the next link (unless one was typed in the meantime).
            if self.url_entry.get().strip() == url:
                self.url_entry.delete(0, "end")
                self.info_frame.pack_forget()
                self._previewed_url = None
                self._clear_per_download_fields()
                self._update_url_validity()
            name = item.custom_name or item.title
            what = f"“{name}”" if name else "It"
            if start:
                waiting = self.queue.is_running()
                self._start_list()
                if waiting:
                    self._show_link_message(f"{what} will download when the one before it finishes.", tone="info")
            else:
                self._show_link_message(f"Added for later. {what} starts when you press its play button "
                                        "or Start.", tone="info")
            self.refresh_queue_display()

        if not cached:
            # Not previewed: add right away (the quality is a preference; the
            # closest one is used). Checking first would mean a slow lookup.
            add(quality)
            return

        # Previewed: warn (as before) when the video doesn't come in the chosen quality.
        def check_quality_thread():
            try:
                engine = DownloadEngine(allow_remote_components=self.allow_remote, cookie_file=self.cookie_file)
                ok, _, available = engine.check_available_quality(url, format_mode, quality, info=cached)
            except Exception as e:
                self.logger.error(f"Error checking quality: {e}", exc_info=True)
                ok, available = True, []
            self.after(0, lambda: checked(ok, available))

        def checked(ok: bool, available: list) -> None:
            if ok:
                add(quality)
                return
            QualityWarningDialog.show(self, "Quality not available", quality, available,
                                      lambda proceed: proceed and add(quality))

        threading.Thread(target=check_quality_thread, daemon=True).start()

    def _paste_list(self) -> None:
        output_path = self.location_entry.get().strip()
        ok, err = validate_path(output_path)
        if not ok:
            ErrorDialog.show(self, "Can't save there", err or "Choose another folder.")
            return
        output_path = os.path.abspath(os.path.expanduser(output_path))
        if not self._check_ffmpeg_for(self.current_format):
            return

        def on_submit(text: str) -> None:
            added, bad, seen = 0, 0, set()
            for raw in text.replace(",", "\n").split():
                url = raw.strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                if not validate_youtube_url(url)[0]:
                    bad += 1
                    continue
                self.queue.add(DownloadItem(url=url, format=self.current_format,
                                            quality=self.quality_combo.get(), output_path=output_path))
                added += 1
            if added:
                self._start_list()
            self.refresh_queue_display()
            msg = f"Downloading {added} link{'s' if added != 1 else ''} as " \
                  f"{FormatManager.label(self.current_format)} · {self.quality_combo.get()}."
            if bad:
                msg += f" Skipped {bad} line{'s' if bad != 1 else ''} that aren't YouTube links."
            self._show_link_message(msg, tone="info")

        PasteListDialog.show(self, on_submit)

    def _start_list(self) -> None:
        """Start the list if it's idle (the next waiting item downloads)."""
        if not self.queue.is_running():
            self._run_before = {id(i) for i in self.queue.get_all()
                                if i.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED,
                                                DownloadStatus.CANCELLED)}
        if self.queue.start():
            self._queue_was_running = True
        self._update_queue_button()

    def stop_current(self) -> None:
        """Ctrl+S / a row's stop button: stop what's downloading; the list moves on."""
        if self.queue.cancel_current():
            self.refresh_queue_display()

    def _notify(self, title: str, body: str) -> None:
        """Desktop notification, only when the app is in the background."""
        if not self.config.get("notifications_enabled", True):
            return
        try:
            if self.focus_displayof() is not None:
                return  # they're looking at it
        except Exception:
            pass
        from src.utils import notify
        notify.notify(title, body)

    def _crossfade_fg(self, widget, to_hex: str) -> None:
        frm = getattr(widget, "_cur_fg", to_hex)
        widget._cur_fg = to_hex
        if frm != to_hex and self._effects():
            crossfade(widget, "fg_color", frm, to_hex, duration_ms=MOTION.base)
        else:
            widget.configure(fg_color=to_hex)

    def _set_primary_state(self, state: str = "idle") -> None:
        """The Download button is always ready: every click adds to the list."""
        self.download_state = "idle"
        p = self.palette
        btn = self.primary_btn
        btn.configure(text="Download", state="normal", hover_color=p.accent_fill_hover,
                      border_width=0, text_color=p.on_accent)
        btn.set_icon("download", p.on_accent)
        self._crossfade_fg(btn, p.accent_fill)
        self.queue_btn.configure(state="normal")
        self._update_header_busy()

    def _update_header_busy(self) -> None:
        try:
            self.header.set_busy(self.queue.is_running())
        except Exception:
            pass

    # ===== queue ==================================================================

    def start_queue(self) -> None:
        """Header button: Pause all while downloading, otherwise Start all."""
        if self.queue.is_running():
            self.queue.pause()
            self._update_queue_button()
            self.refresh_queue_display()
            return
        waiting = self.queue.get_waiting()
        if not waiting:
            return
        needs = [i for i in waiting if FormatManager.needs_ffmpeg(i.format)]
        if needs and not self._check_ffmpeg_for(needs[0].format):
            return
        self._run_before = {id(i) for i in self.queue.get_all()
                            if i.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED,
                                            DownloadStatus.CANCELLED)}
        if self.queue.start_all():
            self._queue_was_running = True
        self.refresh_queue_display()
        self._update_queue_button()

    def _update_queue_button(self) -> None:
        try:
            running = self.queue.is_running()
            waiting = 0 if running else len(self.queue.get_waiting())
            want = "Pause all" if running else (f"Start all ({waiting})" if waiting > 1 else "Start")
            show = running or waiting > 0
            if show != self._start_btn_shown:
                self._start_btn_shown = show
                if show:
                    self.start_queue_btn.pack(side="right", before=self._clear_btn, padx=(0, 0))
                    self._clear_btn.pack_configure(padx=(0, SPACING.sm))
                else:
                    self.start_queue_btn.pack_forget()
            if self.start_queue_btn.cget("text") != want:
                self.start_queue_btn.configure(text=want)
                self.start_queue_btn.set_icon("pause" if running else "play", self.palette.text_primary)
            self._update_header_busy()
        except Exception:
            pass

    def clear_completed(self) -> None:
        try:
            if self.queue.clear_completed():
                self.after_idle(self.refresh_queue_display)
        except Exception as e:
            self.logger.error(f"Error clearing finished downloads: {e}", exc_info=True)
            ErrorDialog.show(self, "Couldn't clear the list", str(e))

    @staticmethod
    def _item_title(item: DownloadItem) -> str:
        raw = item.custom_name or item.title or item.url
        return raw if len(raw) <= 64 else raw[:63] + "…"

    @staticmethod
    def display_order(items: List[DownloadItem]) -> List[DownloadItem]:
        """What's downloading, then what's waiting (in the order it will run), then
        everything finished, newest first."""
        active = [i for i in items if i.status == DownloadStatus.DOWNLOADING]
        waiting = [i for i in items if i.status == DownloadStatus.PENDING]
        held = [i for i in items if i.status == DownloadStatus.PAUSED]
        done = [i for i in items if i not in active and i not in waiting and i not in held]
        done.sort(key=lambda i: i.completed_at or i.created_at, reverse=True)
        return active + waiting + held + done

    @staticmethod
    def _size_text(n: Optional[float]) -> str:
        if not n:
            return ""
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit in ("B", "KB") or n >= 100 else f"{n:.1f} {unit}"
            n /= 1024
        return ""

    @staticmethod
    def row_stats(item: DownloadItem) -> str:
        """The live readout on a downloading row: "Video 42% · 8.4 MB/s · 1:12 left"."""
        stage = item.stage or "Starting"
        parts = [f"{stage} {int(item.progress * 100)}%" if stage in ("Video", "Audio", "Downloading")
                 else stage]
        if item.speed:
            parts.append(f"{item.speed / 1048576:.1f} MB/s")
        if item.eta:
            e = int(item.eta)
            parts.append(f"{e // 60}:{e % 60:02d} left" if e < 3600 else f"{e // 3600}h {e % 3600 // 60}m left")
        return "  ·  ".join(parts)

    def _row_signature(self, item: DownloadItem, position: int):
        return (id(item), item.status, self._item_title(item), item.format, item.quality,
                item.error_message, item.clip_start, item.clip_end, item.file_path, position)

    def refresh_queue_display(self) -> None:
        """Rebuild rows only when the list or a row's state changed; otherwise
        update the live progress of the downloading row in place."""
        try:
            if not hasattr(self, 'queue_scroll') or not self.queue_scroll.winfo_exists():
                return
            items = self.display_order(self.queue.get_all())
            self.queue_count.configure(text=str(len(items)))
            running = self.queue.is_running()
            waiting = sum(1 for i in items if i.status in (DownloadStatus.PENDING, DownloadStatus.PAUSED))
            bits = (["1 downloading"] if running else []) + ([f"{waiting} waiting"] if waiting else [])
            self.queue_summary.configure(text="  ·  ".join(bits))
            first_pending = next((i for i in items if i.status == DownloadStatus.PENDING), None)
            signature = [self._row_signature(i, n) for n, i in enumerate(items)] + [running, id(first_pending)]
            if signature == self._queue_signature:
                for item in items:
                    if item.status == DownloadStatus.DOWNLOADING:
                        self._update_row_progress(item)
                return
            self._queue_signature = signature
            for widget in list(self.queue_scroll.winfo_children()):
                widget.destroy()
            self._queue_rows = {}
            if not items:
                self._build_empty_queue()
            for item in items:
                self.create_queue_item_widget(item, next_up=(item is first_pending and running))
            self.after_idle(self._sync_queue_scrollbar)
            self._update_queue_button()
        except Exception as e:
            self.logger.error(f"Error refreshing the downloads list: {e}", exc_info=True)

    def _build_empty_queue(self) -> None:
        p = self.palette
        # Compact and horizontal: the list card can be short (it gets what the
        # form leaves), and a tall empty state was cut off at common sizes.
        box = customtkinter.CTkFrame(self.queue_scroll, fg_color="transparent")
        box.pack(pady=SPACING.lg)
        img = icons.badge("download", 36, p.text_secondary, p.surface_raised)
        if img:
            customtkinter.CTkLabel(box, text="", image=img).pack(side="left", padx=(0, SPACING.md))
        text = customtkinter.CTkFrame(box, fg_color="transparent")
        text.pack(side="left")
        customtkinter.CTkLabel(text, text="Nothing here yet", font=TYPE.body_med, anchor="w",
                               text_color=p.text_primary, height=18).pack(anchor="w")
        customtkinter.CTkLabel(text, text="Paste a link above or drop one on the window. "
                                          "Finished downloads stay here with Play and Show in folder.",
                               font=TYPE.caption, text_color=p.text_secondary, anchor="w", height=18
                               ).pack(anchor="w", pady=(SPACING.xxs, 0))

    def _row_status(self, item: DownloadItem, next_up: bool):
        """(text, color) for a row's second line (not used while downloading)."""
        p = self.palette
        st = item.status
        if st == DownloadStatus.FAILED:
            return self._short_error(Exception(item.error_message or "Download failed")), p.error
        if st == DownloadStatus.COMPLETED:
            path = item.file_path
            if path and not os.path.exists(path):
                return "Saved, but the file has been moved or deleted", p.text_tertiary
            folder = os.path.basename(os.path.dirname(path)) if path else os.path.basename(item.output_path or "")
            if item.file_count > 1:
                what = f"{item.file_count} files"
            else:
                try:
                    what = self._size_text(os.path.getsize(path)) if path else ""
                except OSError:
                    what = ""
            return "  ·  ".join(x for x in ("Saved", what, folder) if x), p.text_secondary
        if st == DownloadStatus.CANCELLED:
            return "Stopped", p.text_secondary
        if st == DownloadStatus.PAUSED:
            return "Not started", p.text_secondary
        if next_up:
            return "Waiting  ·  starts next", p.text_secondary
        return ("Waiting" if self.queue.is_running() else "Waiting  ·  paused"), p.text_secondary

    def create_queue_item_widget(self, item: DownloadItem, next_up: bool = False) -> None:
        p = self.palette
        st = item.status
        active = st == DownloadStatus.DOWNLOADING
        row = customtkinter.CTkFrame(self.queue_scroll, fg_color=p.surface_raised, corner_radius=RADIUS.md + 2,
                                     border_width=BORDER.hairline if active else 0,
                                     border_color=_mix_hex(p.surface_raised, p.accent, 0.35))
        row.pack(fill="x", pady=(0, SPACING.xs + 2), padx=SPACING.xs)
        row.grid_columnconfigure(1, weight=1)

        icon_name, role = _STATUS_ICON.get(st, ("clock", "text_secondary"))
        color = getattr(p, role)
        img = icons.icon(icon_name, 17, color)
        customtkinter.CTkLabel(row, text="" if img else "•", image=img, width=28, text_color=color).grid(
            row=0, column=0, rowspan=2, padx=(SPACING.md, SPACING.sm), pady=SPACING.md)

        customtkinter.CTkLabel(row, text=self._item_title(item), font=TYPE.body_med, text_color=p.text_primary,
                               anchor="w").grid(row=0, column=1, sticky="ew", pady=(SPACING.sm + 2, 0))

        widgets: Dict[str, Any] = {"row": row}
        if active:
            line = customtkinter.CTkFrame(row, fg_color="transparent")
            line.grid(row=1, column=1, sticky="ew", pady=(SPACING.xs, SPACING.sm + 2))
            line.grid_columnconfigure(0, weight=1)
            bar = customtkinter.CTkProgressBar(line, height=4, corner_radius=RADIUS.pill,
                                               progress_color=p.accent, fg_color=p.surface_hover)
            bar.grid(row=0, column=0, sticky="ew", padx=(0, SPACING.md))
            stat = customtkinter.CTkLabel(line, text="", font=TYPE.mono, text_color=p.text_secondary,
                                          anchor="e", width=240)
            stat.grid(row=0, column=1, sticky="e")
            widgets.update(bar=bar, stat=stat)
        else:
            text, tcolor = self._row_status(item, next_up)
            if item.clip_start or item.clip_end:
                text += "  ·  clip"
            customtkinter.CTkLabel(row, text=text, font=TYPE.caption, text_color=tcolor, anchor="w").grid(
                row=1, column=1, sticky="ew", pady=(0, SPACING.sm + 2))

        chip = f"{FormatManager.label(item.format)}  ·  {item.quality.split(' (')[0]}"
        customtkinter.CTkLabel(row, text=chip, font=TYPE.caption_med, text_color=p.text_secondary,
                               fg_color=p.surface, corner_radius=RADIUS.sm, height=24, padx=10).grid(
            row=0, column=2, rowspan=2, padx=SPACING.sm)

        # The action you're most likely to want, right on the row; the rest are under ⋯.
        actions = customtkinter.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=3, rowspan=2, padx=(0, SPACING.sm))
        exists = bool(item.file_path and os.path.exists(item.file_path))
        if active:
            IconButton(actions, p, icon="stop", size=32, command=self.stop_current).pack(side="left")
        elif st in (DownloadStatus.PENDING, DownloadStatus.PAUSED):
            IconButton(actions, p, icon="play", size=32, color=p.text_primary,
                       command=lambda it=item: self._start_item(it)).pack(side="left")
        elif st == DownloadStatus.COMPLETED and exists:
            IconButton(actions, p, icon="play" if item.file_count <= 1 else "open", size=32, color=p.text_primary,
                       command=lambda it=item: self._open_item(it)).pack(side="left")
            IconButton(actions, p, icon="folder", size=32, color=p.text_primary,
                       command=lambda it=item: self._reveal_item(it)).pack(side="left")
        elif st in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
            GhostButton(actions, p, text="Retry", icon="refresh", text_color=p.text_primary,
                        command=lambda it=item: self._start_item(it)).pack(side="left")
        menu_btn = IconButton(actions, p, icon="more", size=32)
        menu_btn.configure(command=lambda b=menu_btn, it=item: self._show_queue_menu(b, it))
        menu_btn.pack(side="left")

        self._queue_rows[id(item)] = widgets
        if active:
            self._update_row_progress(item)

    def _update_row_progress(self, item: DownloadItem) -> None:
        w = self._queue_rows.get(id(item))
        if not w or "bar" not in w:
            return
        w["bar"].set(max(0.0, min(1.0, item.progress)))
        w["stat"].configure(text=self.row_stats(item))

    def _start_item(self, item: DownloadItem) -> None:
        """A row's play / Retry: download it now, or next if something's downloading."""
        if FormatManager.needs_ffmpeg(item.format) and not self._check_ffmpeg_for(item.format):
            return
        if not self.queue.is_running():
            self._run_before = {id(i) for i in self.queue.get_all()
                                if i.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED,
                                                DownloadStatus.CANCELLED) and i is not item}
        if self.queue.start_item(item) and self.queue.is_running():
            self._queue_was_running = True
        self.refresh_queue_display()

    def _open_item(self, item: DownloadItem) -> None:
        try:
            if item.file_count > 1:
                winsys.open_path(os.path.dirname(item.file_path))
            else:
                winsys.open_path(item.file_path)
        except Exception as e:
            ErrorDialog.show(self, "Couldn't open it", str(e))

    def _show_queue_menu(self, anchor_widget, item: DownloadItem) -> None:
        menu = PopupMenu(self, self.palette)
        st = item.status
        if st == DownloadStatus.DOWNLOADING:
            menu.add("Stop", self.stop_current, "stop")
        if st in (DownloadStatus.PENDING, DownloadStatus.PAUSED):
            menu.add("Start now" if not self.queue.is_running() else "Download next",
                     lambda: self._start_item(item), "play")
        if st in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
            menu.add("Retry", lambda: self._start_item(item), "refresh")
        if st == DownloadStatus.FAILED and item.error_message:
            menu.add("What went wrong…", lambda: ErrorDialog.show(self, "Download failed", item.error_message),
                     "info")
        if st == DownloadStatus.COMPLETED:
            menu.add("Show in folder", lambda: self._reveal_item(item), "folder")
            if item.file_path and os.path.exists(item.file_path):
                menu.add("Play" if item.file_count <= 1 else "Open folder", lambda: self._open_item(item),
                         "play" if item.file_count <= 1 else "open")
                if item.file_count <= 1:
                    menu.add("Rename file…", lambda: self._rename_queue_item(item), "rename")
        menu.add("Copy link", lambda: (self.clipboard_clear(), self.clipboard_append(item.url)), "link")
        if st != DownloadStatus.DOWNLOADING:
            menu.separator()
            menu.add("Remove from list", lambda: self.remove_queue_item(item), "delete", danger=True)
        menu.show_below(anchor_widget, align="right")

    def _rename_queue_item(self, item: DownloadItem) -> None:
        path = item.file_path

        def submit(new_name: str) -> Optional[str]:
            new_path, err = rename_download(path, new_name)
            if err:
                return err
            item.file_path = new_path
            item.custom_name = os.path.splitext(os.path.basename(new_path))[0]
            self.queue.save()
            self.refresh_queue_display()
            return None

        stem, ext = os.path.splitext(os.path.basename(path))
        RenameDialog.show(self, stem, ext, submit)

    def _reveal_item(self, item: DownloadItem) -> None:
        try:
            if item.file_path and os.path.exists(item.file_path):
                winsys.reveal_file(item.file_path)
            else:
                winsys.open_path(item.output_path or self.download_path)
        except Exception as e:
            self.logger.error(f"Could not open folder: {e}")

    def remove_queue_item(self, item: DownloadItem) -> None:
        index = self.queue.index_of(item)
        if index >= 0:
            self.queue.remove(index)
        self.refresh_queue_display()

    def on_queue_update(self) -> None:
        """Queue status callback (may be a worker thread): only flag a redraw."""
        self._queue_dirty = True

    def _check_link_inbox(self) -> None:
        """Links from the browser button (see src/utils/links.py)."""
        from src.utils import links
        for link in links.take():
            self.handle_app_link(link)

    def handle_app_link(self, link: str) -> None:
        """A youdownloader:// link: bring the window forward and load the video."""
        from src.utils import links
        url = links.video_url_from_link(link) or (link if link.lower().startswith("http") else None)
        self.logger.info(f"Link from the browser button: {url or link[:120]}")
        self.bring_to_front()
        if not url or not validate_youtube_url(url)[0]:
            self._show_link_message("That page isn't a YouTube video.")
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, url)
        self._update_url_validity()
        self.fetch_video_info()

    def bring_to_front(self) -> None:
        try:
            if self.state() == "iconic":
                self.deiconify()
            self.lift()
            if paths.IS_WINDOWS:  # Windows only lets a window jump forward like this
                self.attributes("-topmost", True)
                self.after(200, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception:
            pass

    def _poll_queue(self) -> None:
        try:
            self._check_link_inbox()
        except Exception as e:
            self.logger.debug(f"Link inbox error (non-critical): {e}")
        try:
            if self._queue_dirty:
                self._queue_dirty = False
                self.refresh_queue_display()
            running = self.queue.is_running()
            if self._queue_was_running and not running and not self.queue.get_pending():
                self._on_list_finished()
            self._queue_was_running = running
            self._update_queue_button()
        except Exception as e:
            self.logger.debug(f"Queue poll error (non-critical): {e}")
        self.after(300, self._poll_queue)

    def _on_list_finished(self) -> None:
        """Everything that was started has finished: flash the taskbar and notify."""
        items = [i for i in self.queue.get_all() if id(i) not in self._run_before
                 and i.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED)]
        done = [i for i in items if i.status == DownloadStatus.COMPLETED]
        failed = [i for i in items if i.status == DownloadStatus.FAILED]
        if not items:
            return  # stopped or paused by hand
        winsys.flash_taskbar(self)
        if len(items) == 1:
            item = items[0]
            if done:
                self._notify("Download finished", os.path.basename(item.file_path or "") or self._item_title(item))
            else:
                self._notify("Download failed", self._short_error(Exception(item.error_message or "")) or
                             "Open YouDownloader for details.")
        else:
            self._notify("Downloads finished", f"{len(done)} downloaded"
                         + (f", {len(failed)} failed" if failed else "") + ".")
        self._run_before = {id(i) for i in self.queue.get_all()}

    def on_closing(self) -> None:
        try:
            if self.state() == "zoomed":
                self.config.set("window_maximized", True)
            else:
                # winfo_* are physical pixels; CTk's geometry() expects logical ones.
                scale = customtkinter.ScalingTracker.get_window_scaling(self)
                self.config.update({
                    "window_maximized": False,
                    "window_width": int(self.winfo_width() / scale),
                    "window_height": int(self.winfo_height() / scale),
                    "window_x": self.winfo_x(),
                    "window_y": self.winfo_y(),
                })
        except Exception as e:
            self.logger.debug(f"Could not save window geometry: {e}")
        # What was downloading goes back to waiting; it restarts with Start next time.
        self.queue.pause()
        self.logger.info("Closing YouDownloader")
        self.destroy()
