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
import shutil
import sys
import threading
import tkinter.filedialog
from typing import Any, Callable, Dict, Optional

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
from src.ui.components import ProgressDisplay, set_window_icon
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

_STATUS_ICON = {
    DownloadStatus.PENDING: ("clock", "text_secondary"),
    DownloadStatus.DOWNLOADING: ("download", "accent_hover"),
    DownloadStatus.COMPLETED: ("check", "success"),
    DownloadStatus.FAILED: ("error", "error"),
    DownloadStatus.CANCELLED: ("close", "text_disabled"),
    DownloadStatus.PAUSED: ("clock", "text_secondary"),
}


class YouDownloaderApp(customtkinter.CTk):
    """Main application window"""

    def __init__(self):
        super().__init__()
        customtkinter.set_appearance_mode("dark")
        self.font_family = init_fonts(self)

        self.config = Config()
        self.logger = logger
        self.logger.info(f"Starting YouDownloader v{__version__} ({sys.platform}"
                         f"{', packaged' if paths.FROZEN else ', from source'}, "
                         f"yt-dlp {updater.ytdlp_version()}, font {self.font_family})")
        self._pending_release: Optional[app_update.Release] = None
        self._update_banner = None

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
        self.is_downloading = False
        self.cancelled = False
        self._download_token = 0
        self._download_opts: Dict[str, Any] = {}
        self._queue_dirty = False
        self._queue_was_running = False
        self._queue_rows: Dict[int, Dict[str, Any]] = {}
        self._queue_signature = None
        self.last_files: list = []
        self._last_autofill: Optional[str] = None
        self.download_state = "idle"
        self.ydl_instance: Optional[DownloadEngine] = None
        self.download_thread_ref: Optional[threading.Thread] = None
        self.cached_video_info: Optional[Dict[str, Any]] = None
        self.info_fetch_thread: Optional[threading.Thread] = None

        # Our icon + a title bar tinted to the void (CTk applies its own ~200ms in).
        self.after(300, lambda: (set_window_icon(self),
                                 winsys.style_window(self, caption=p.bg, text=p.text_secondary, border=p.bg)))

        self.create_ui()
        self.setup_shortcuts()
        self.bind("<FocusIn>", self._on_window_focus, add="+")

        self.refresh_queue_display()
        self.after(400, self._poll_queue)
        if self.config.get("js_runtime_consent") is None:
            self.after(600, self._prompt_js_consent)
        if paths.IS_MAC:
            self._setup_mac_app()
        if app_update.can_self_install() and self.config.get("auto_check_updates", True):
            self.after(4000, lambda: self.check_for_app_update(manual=False))

    # ===== platform =========================================================

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
        if on_result:
            on_result(release, error)
            return
        if release is None:
            if manual and not error:
                InfoDialog.show(self, "You're up to date", f"YouDownloader {__version__} is the latest version.")
            elif manual:
                ErrorDialog.show(self, "Couldn't check for updates", error)
            return
        self._pending_release = release
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
        children = self._banner_parent.winfo_children()
        before = next((w for w in children if w is not self._update_banner), None)
        self._update_banner.pack(fill="x", pady=(0, SPACING.md), **({"before": before} if before else {}))

    def show_update(self, release) -> None:
        def install(path: str) -> None:
            try:
                app_update.install(path)
            except app_update.UpdateError as e:
                ErrorDialog.show(self, "Couldn't install the update", str(e))
                return
            except Exception as e:
                self.logger.error(f"Update install failed: {e}", exc_info=True)
                ErrorDialog.show(self, "Couldn't install the update", str(e))
                return
            self.logger.info(f"Installing update {release.version}; quitting")
            self.on_closing()

        def go():
            UpdateDialog.show(self, release, install)

        if self.is_downloading or self.queue.is_running():
            ConfirmDialog.show(self, "Stop downloads and update?",
                               "A download is still running. Updating restarts YouDownloader and "
                               "stops it (queued items stay in the queue).",
                               lambda yes: yes and go(), confirm_text="Continue")
        else:
            go()

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
        if event.widget is not self or self.is_downloading:
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
                (InfoDialog if ok else ErrorDialog).show(self, "yt-dlp update", msg)
                if on_done:
                    on_done(ok, msg)
            self.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    def _open_settings(self) -> None:
        SettingsDialog.show(self)

    def rebuild_ui(self) -> None:
        """Re-create the window contents (used when setup notices are re-shown)."""
        if hasattr(self, "progress_display"):
            try:
                self.progress_display.reset()
            except Exception:
                pass
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
        self._set_primary_state(self.download_state)

    def apply_palette(self, name: str) -> None:
        """Kept for compatibility; there is a single dark palette now."""
        self.rebuild_ui()

    def setup_shortcuts(self) -> None:
        # ⌘ on macOS, Ctrl elsewhere. On macOS ⌘Q and ⌘, come from the app
        # menu (see _setup_mac_app), so they aren't bound here.
        mod = "Command" if paths.IS_MAC else "Control"
        self.bind(f"<{mod}-d>", lambda e: self.start_download())
        self.bind(f"<{mod}-s>", lambda e: self.stop_download())
        self.bind(f"<{mod}-o>", lambda e: self.browse_folder())
        if not paths.IS_MAC:
            self.bind("<Control-q>", lambda e: self.on_closing())
            self.bind("<Control-comma>", lambda e: self._open_settings())
        self.bind("<F5>", lambda e: self.fetch_video_info())
        self.focus_set()

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
        self.page.grid_rowconfigure(2, weight=1)
        self.page.bind("<Configure>", self._fit_column)

        self._build_compose_card(row=0)
        self._build_status_card(row=1)
        self._build_queue_card(row=2)

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
                                      text_color=self.palette.text_disabled, anchor="w", height=16)

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
                                     border_width=BORDER.hairline, border_color=p.border_strong,
                                     height=HEIGHT.url_bar)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self._url_row = bar
        link_icon = icons.icon("link", 18, p.text_disabled)
        customtkinter.CTkLabel(bar, text="" if link_icon else "↗", image=link_icon, width=24).pack(
            side="left", padx=(SPACING.md + 2, SPACING.xs))
        self.url_entry = FieldEntry(bar, p, border_width=0, fg_color=p.surface_raised, font=TYPE.body_lg,
                                    placeholder_text="Paste a YouTube link", height=HEIGHT.url_bar - 12)
        self.url_entry.pack(side="left", fill="x", expand=True)
        self.url_entry.bind("<FocusIn>", lambda e: bar.configure(border_color=p.accent), add="+")
        self.url_entry.bind("<FocusOut>", lambda e: bar.configure(border_color=p.border_strong), add="+")
        self.url_entry.bind("<KeyRelease>", lambda e: self._update_url_validity())
        self.url_entry.bind("<Return>", lambda e: self.fetch_video_info())

        self.url_validity_pip = StatusPip(bar, color=p.text_disabled, size=7, bg=p.surface_raised)
        self.url_validity_pip.hide()
        self.url_validity_pip.pack(side="left", padx=(SPACING.xs, SPACING.sm))
        self.preview_btn = SecondaryButton(bar, p, text="Preview", height=HEIGHT.button_sm, width=86,
                                           fg_color=p.surface_hover, border_width=0,
                                           command=self.fetch_video_info)
        self.preview_btn.pack(side="right", padx=(SPACING.xs, SPACING.sm))
        GhostButton(bar, p, text="Paste", icon="paste", width=78, command=self._paste_link).pack(side="right")

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
            fg_color=p.surface_raised, selected_color=p.accent, selected_hover_color=p.accent_hover,
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
        customtkinter.CTkLabel(clip_row, text="→", font=TYPE.body, text_color=p.text_disabled, width=24
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
        self.primary_btn._cur_fg = p.accent
        self.primary_btn.pack(side="left", fill="x", expand=True, padx=(0, SPACING.sm))
        self.queue_btn = SecondaryButton(actions, p, text="Add to queue", icon="add", width=168,
                                         height=HEIGHT.button_lg, command=self.add_to_queue)
        self.queue_btn.pack(side="left")

    def _build_banners(self, parent) -> None:
        self._banner_parent = parent
        self._update_banner = None
        if self._pending_release and self.config.get("skipped_update_version") != self._pending_release.version:
            self.after_idle(self._show_update_banner)
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
            if updater.can_update_ytdlp():
                detail, on_action = ("YouTube changes often and old versions start failing.",
                                     lambda: (holder["b"].destroy(), self._update_ytdlp()))
            else:  # packaged app: yt-dlp is refreshed by app updates
                detail, on_action = ("YouTube changes often. Update YouDownloader to get a newer one.",
                                     lambda: self.check_for_app_update(manual=True))
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

    def _build_status_card(self, row: int) -> None:
        p = self.palette
        card = self._card(row)
        inner = customtkinter.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=SPACING.xl, pady=(SPACING.lg + 2, SPACING.lg + 2))
        self.progress_display = ProgressDisplay(inner, p)
        self.progress_display.set_idle_hint(f"{paths.shortcut('D')} download  ·  F5 preview")

        self.result_actions = customtkinter.CTkFrame(inner, fg_color="transparent")
        self.open_file_btn = GhostButton(self.result_actions, p, text="Play", icon="play",
                                         text_color=p.text_primary, command=self._open_last_file)
        self.open_file_btn.pack(side="left", padx=(0, SPACING.xs))
        GhostButton(self.result_actions, p, text="Show in folder", icon="folder",
                    text_color=p.text_primary, command=self._reveal_last_file).pack(side="left", padx=(0, SPACING.xs))
        self.rename_last_btn = GhostButton(self.result_actions, p, text="Rename", icon="rename",
                                           text_color=p.text_primary, command=self._rename_last_file)
        self.rename_last_btn.pack(side="left")

    def _build_queue_card(self, row: int) -> None:
        p = self.palette
        card = self._card(row, pady=(0, SPACING.xl), sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        header = customtkinter.CTkFrame(card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.lg + 2, SPACING.sm))
        customtkinter.CTkLabel(header, text="Queue", font=TYPE.title, text_color=p.text_primary).pack(side="left")
        self.queue_count = customtkinter.CTkLabel(header, text="0", font=TYPE.caption_med, height=22,
                                                  text_color=p.text_secondary, fg_color=p.surface_raised,
                                                  corner_radius=RADIUS.sm, padx=8)
        self.queue_count.pack(side="left", padx=(SPACING.sm, 0))

        self.start_queue_btn = SecondaryButton(header, p, text="Start", icon="play", width=96,
                                               height=HEIGHT.button_sm, command=self.start_queue)
        self.start_queue_btn.pack(side="right")
        GhostButton(header, p, text="Clear done", icon="clear", command=self.clear_completed).pack(
            side="right", padx=(0, SPACING.sm))
        GhostButton(header, p, text="Paste list", icon="list", command=self._paste_list).pack(
            side="right", padx=(0, SPACING.xs))

        self.queue_scroll = customtkinter.CTkScrollableFrame(
            card, fg_color="transparent", scrollbar_button_color=p.border_strong,
            scrollbar_button_hover_color=p.text_disabled)
        self.queue_scroll.grid(row=1, column=0, sticky="nsew", padx=SPACING.md, pady=(0, SPACING.md))

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
        if not url:
            self.url_validity_pip.hide()
            return
        is_valid, _ = validate_youtube_url(url)
        self.url_validity_pip.set_color(self.palette.success if is_valid else self.palette.error)

    def fetch_video_info(self) -> None:
        url = self.url_entry.get().strip()
        if not url:
            ErrorDialog.show(self, "No link yet", "Paste a YouTube link first.")
            return
        is_valid, error_msg = validate_youtube_url(url)
        if not is_valid:
            ErrorDialog.show(self, "That isn't a YouTube link", error_msg or "Check the link and try again.")
            return
        if self.info_fetch_thread and self.info_fetch_thread.is_alive():
            return

        self.preview_btn.configure(state="disabled", text="Loading…")

        def fetch_thread():
            try:
                engine = DownloadEngine(allow_remote_components=self.allow_remote, cookie_file=self.cookie_file)
                info = engine.get_video_info(url)
                if info:
                    self.cached_video_info = info
                    self.after(0, lambda: self.display_video_info(info))
                else:
                    self.after(0, lambda: (self.info_frame.pack_forget(), ErrorDialog.show(
                        self, "Couldn't load that video", "It may be private, removed, or region-locked.")))
            except Exception as e:
                self.logger.error(f"Error fetching video info: {e}", exc_info=True)
                self.after(0, lambda: (self.info_frame.pack_forget(),
                                       ErrorDialog.show(self, "Couldn't load that video", str(e))))
            finally:
                self.after(0, lambda: self.preview_btn.configure(state="normal", text="Preview"))

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
            ErrorDialog.show(self, "No link yet", "Paste a YouTube link first.")
            return None
        ok, err = validate_youtube_url(url)
        if not ok:
            ErrorDialog.show(self, "That isn't a YouTube link", err or "Check the link and try again.")
            return None
        output_path = self.location_entry.get().strip()
        ok, err = validate_path(output_path)
        if not ok:
            ErrorDialog.show(self, "Can't save there", err or "Choose another folder.")
            return None
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
        v = self._validated_inputs()
        if not v:
            return
        cached = self._cached_info_for(v["url"])
        item = DownloadItem(
            url=v["url"], title=cached.get('title') if cached else None,
            format=self.current_format, quality=self.quality_combo.get(),
            output_path=v["output_path"], clip_start=v["clip"][0], clip_end=v["clip"][1],
            custom_name=v["name"],
        )
        try:
            self.queue.add(item)
        except Exception as e:
            self.logger.error(f"Error adding to queue: {e}", exc_info=True)
            ErrorDialog.show(self, "Couldn't add to the queue", str(e))
            return
        self.refresh_queue_display()
        if not self.is_downloading:
            self.progress_display.set_status(f"Added to queue  ·  {item.custom_name or item.title or 'link'}",
                                             self.palette.text_secondary)
        self.url_entry.delete(0, "end")
        self.info_frame.pack_forget()
        self._clear_per_download_fields()
        self._update_url_validity()

    def _paste_list(self) -> None:
        output_path = self.location_entry.get().strip()
        ok, err = validate_path(output_path)
        if not ok:
            ErrorDialog.show(self, "Can't save there", err or "Choose another folder.")
            return
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
            self.refresh_queue_display()
            msg = f"Queued {added} link{'s' if added != 1 else ''} as " \
                  f"{FormatManager.label(self.current_format)} · {self.quality_combo.get()}."
            if bad:
                msg += f"\nSkipped {bad} line{'s' if bad != 1 else ''} that aren't YouTube links."
            InfoDialog.show(self, "Added to queue", msg)

        PasteListDialog.show(self, on_submit)

    # ===== direct download ===========================================================

    def start_download(self) -> None:
        if self.is_downloading:
            return
        v = self._validated_inputs()
        if not v:
            return
        url, output_path, clip = v["url"], v["output_path"], v["clip"]
        format_mode, quality = self.current_format, self.quality_combo.get()

        cached = self._cached_info_for(url)
        if DownloadEngine.is_playlist_url(url) and not getattr(self, "_playlist_confirmed", False):
            count = cached.get("playlist_count") if cached and cached.get("is_playlist") else None
            what = f"all {count} videos" if count else "every video in it"

            def on_choice(yes: bool) -> None:
                if yes:
                    self._playlist_confirmed = True
                    try:
                        self.start_download()
                    finally:
                        self._playlist_confirmed = False
            ConfirmDialog.show(self, "Download the whole playlist?",
                               f"This link is a playlist. YouDownloader will save {what} "
                               "into a new folder.", on_choice, confirm_text="Download playlist")
            return

        self._download_opts = {
            "embed_metadata": bool(self.config.get("embed_metadata", True)),
            "download_subtitles": bool(self.config.get("auto_download_subtitles")),
            "subtitle_language": self.config.get("subtitle_language") or "en",
            "clip_start": clip[0],
            "clip_end": clip[1],
            "filename": v["name"],
        }
        self.result_actions.pack_forget()
        self._download_token += 1
        token = self._download_token
        self.is_downloading = True
        self.cancelled = False
        self._set_primary_state("preparing")
        self.queue_btn.configure(state="disabled")
        self.progress_display.reset()
        self.progress_display.start_indeterminate("Preparing…")

        def check_quality_thread():
            try:
                engine = DownloadEngine(allow_remote_components=self.allow_remote, cookie_file=self.cookie_file)
                is_available, _, all_available = engine.check_available_quality(
                    url, format_mode, quality, info=cached)
            except Exception as e:
                self.logger.error(f"Error checking quality: {e}", exc_info=True)
                is_available, all_available = True, []
            if is_available:
                self.after(0, lambda: self._start_download_after_check(token, url, output_path, format_mode, quality))
            else:
                self.after(0, lambda: self._show_quality_warning(token, quality, all_available, url,
                                                                 output_path, format_mode))

        threading.Thread(target=check_quality_thread, daemon=True).start()

    def _is_current(self, token: int) -> bool:
        return token == self._download_token and self.is_downloading and not self.cancelled

    def _show_quality_warning(self, token, requested_quality, available_resolutions, url, output_path, format_mode):
        if not self._is_current(token):
            return

        def on_choice(proceed: bool):
            if proceed:
                self._start_download_after_check(token, url, output_path, format_mode, requested_quality)
            elif self._is_current(token):
                self.cleanup_download()
                self.progress_display.reset()

        QualityWarningDialog.show(self, "Quality not available", requested_quality, available_resolutions, on_choice)

    def _start_download_after_check(self, token, url, output_path, format_mode, quality) -> None:
        if not self._is_current(token):
            return
        self._set_primary_state("downloading")
        engine = DownloadEngine(progress_callback=lambda d: self.progress_callback(d, token),
                                allow_remote_components=self.allow_remote, cookie_file=self.cookie_file)
        self.ydl_instance = engine
        opts = dict(self._download_opts)

        def download_thread():
            try:
                ok = engine.download(url=url, output_path=output_path, format_mode=format_mode,
                                     quality=quality, **opts)
            except Exception as e:
                if not engine.cancelled:
                    self.after(0, lambda msg=str(e): self.on_download_error(msg, token))
                return
            if ok:
                self.last_files = list(engine.downloaded_files)
                self.after(0, lambda: self.on_download_complete(token))
            elif not engine.cancelled:
                self.after(0, lambda: self.on_download_error("The download didn't finish.", token))

        self.download_thread_ref = threading.Thread(target=download_thread, daemon=True)
        self.download_thread_ref.start()

    def on_primary_action(self) -> None:
        if self.download_state == "downloading":
            self.stop_download()
        elif self.download_state in ("idle", "done"):
            self.start_download()

    def _crossfade_fg(self, widget, to_hex: str) -> None:
        frm = getattr(widget, "_cur_fg", to_hex)
        widget._cur_fg = to_hex
        if frm != to_hex and self._effects():
            crossfade(widget, "fg_color", frm, to_hex, duration_ms=MOTION.base)
        else:
            widget.configure(fg_color=to_hex)

    def _set_primary_state(self, state: str) -> None:
        """idle / done: violet Download · preparing: dimmed · downloading: red-outlined Stop."""
        self.download_state = state
        p = self.palette
        btn = self.primary_btn
        if state == "downloading":
            btn.configure(text="Stop", state="normal", hover_color="#3A1824", text_color=p.error,
                          border_width=BORDER.hairline, border_color=p.error)
            btn.set_icon("stop", p.error)
            self._crossfade_fg(btn, p.error_subtle)
        elif state == "preparing":
            btn.configure(text="Preparing…", state="disabled", hover_color=p.accent_pressed,
                          border_width=0, text_color=p.on_accent)
            btn.set_icon(None)
            self._crossfade_fg(btn, p.accent_pressed)
        else:
            btn.configure(text="Download", state="normal", hover_color=p.accent_hover,
                          border_width=0, text_color=p.on_accent)
            btn.set_icon("download", p.on_accent)
            self._crossfade_fg(btn, p.accent)
            self.queue_btn.configure(state="normal")
            self.progress_display.stop_indeterminate()
        self._update_header_busy()

    def _update_header_busy(self) -> None:
        try:
            self.header.set_busy(self.is_downloading or self.queue.is_running())
        except Exception:
            pass

    def progress_callback(self, d: Dict[str, Any], token: Optional[int] = None) -> None:
        """Progress from the engine (worker thread)."""
        if token is not None and token != self._download_token:
            return
        if not self.is_downloading or self.cancelled:
            return
        status = d.get('status')
        if status == 'downloading':
            percent = progress_fraction(d) or 0.0
            speed = d.get('speed') or 0
            eta = d.get('eta')
            info = d.get('info_dict') or {}
            if info.get('vcodec') == 'none':
                stage = "Audio stream"
            elif info.get('acodec') == 'none':
                stage = "Video stream"
            else:
                stage = "Downloading"
            parts = []
            if speed:
                parts.append(f"{speed / 1048576:.1f} MB/s")
            if eta:
                e = int(eta)
                parts.append(f"{e // 60}:{e % 60:02d} left" if e < 3600 else f"{e // 3600}h {e % 3600 // 60}m left")
            details = "   ·   ".join(parts)
            self.after(0, lambda: self.progress_display.update_progress(percent, details, speed, stage))
        elif status == 'finished':
            self.after(0, lambda: self.progress_display.start_indeterminate("Processing…"))
        elif status == 'converting':
            fraction = d.get('progress', 0.0)
            action = d.get('action', "Converting")
            self.after(0, lambda: self.progress_display.update_progress(fraction, "", 0, action))

    def _existing_last_files(self):
        return [f for f in self.last_files if os.path.exists(f)]

    def on_download_complete(self, token: Optional[int] = None) -> None:
        if token is not None and token != self._download_token:
            return
        self.cleanup_download()
        self.progress_display.complete()
        files = self._existing_last_files()
        name = os.path.basename(files[-1]) if len(files) == 1 else f"{len(files)} files"
        self.progress_display.set_status(f"Saved  ·  {name}" if files else "Download complete",
                                         self.palette.success, "")
        if files:
            single = len(files) == 1
            self.open_file_btn.configure(text="Play" if single else "Open folder")
            self.open_file_btn.set_icon("play" if single else "folder", self.palette.text_primary)
            if single:
                self.rename_last_btn.pack(side="left")
            else:
                self.rename_last_btn.pack_forget()
            self.result_actions.pack(anchor="w", pady=(SPACING.md, 0))
        self._clear_per_download_fields()
        winsys.flash_taskbar(self)

    def _open_last_file(self) -> None:
        files = self._existing_last_files()
        try:
            if len(files) == 1:
                winsys.open_path(files[0])
            elif files:
                winsys.open_path(os.path.dirname(files[0]))
        except Exception as e:
            ErrorDialog.show(self, "Couldn't open it", str(e))

    def _reveal_last_file(self) -> None:
        files = self._existing_last_files()
        if files:
            try:
                winsys.reveal_file(files[-1])
            except Exception as e:
                ErrorDialog.show(self, "Couldn't open the folder", str(e))

    def _rename_last_file(self) -> None:
        files = self._existing_last_files()
        if len(files) != 1:
            return
        path = files[0]

        def submit(new_name: str) -> Optional[str]:
            new_path, err = rename_download(path, new_name)
            if err:
                return err
            self.last_files = [new_path]
            self.progress_display.set_status(f"Saved  ·  {os.path.basename(new_path)}", self.palette.success, "")
            return None

        stem, ext = os.path.splitext(os.path.basename(path))
        RenameDialog.show(self, stem, ext, submit)

    def on_download_error(self, error_msg: str, token: Optional[int] = None) -> None:
        if token is not None and token != self._download_token:
            return
        self.cleanup_download()
        self.progress_display.reset()
        self.progress_display.set_status("Download failed", self.palette.error)
        ErrorDialog.show(self, "Download failed", error_msg)

    def stop_download(self) -> None:
        if not self.is_downloading:
            return
        self.cancelled = True
        if self.ydl_instance:
            self.ydl_instance.cancel()
        self.cleanup_download()
        self.progress_display.reset()
        self.progress_display.set_status("Cancelled", self.palette.text_secondary)

    def cleanup_download(self) -> None:
        self.is_downloading = False
        self.cancelled = False
        self.ydl_instance = None
        self.download_thread_ref = None
        self._set_primary_state("idle")

    # ===== queue ==================================================================

    def start_queue(self) -> None:
        if self.queue.is_running():
            self.queue.stop()
            self._update_queue_button()
            return
        pending = self.queue.get_pending()
        if not pending:
            InfoDialog.show(self, "Nothing to start", "Add links to the queue first.")
            return
        needs = [i for i in pending if FormatManager.needs_ffmpeg(i.format)]
        if needs and not self._check_ffmpeg_for(needs[0].format):
            return
        self.queue.start()
        self.refresh_queue_display()
        self._update_queue_button()

    def _update_queue_button(self) -> None:
        try:
            running = self.queue.is_running()
            want = "Stop" if running else "Start"
            if self.start_queue_btn.cget("text") != want:
                self.start_queue_btn.configure(text=want)
                self.start_queue_btn.set_icon("stop" if running else "play", self.palette.text_primary)
            self._update_header_busy()
        except Exception:
            pass

    def clear_completed(self) -> None:
        try:
            if self.queue.clear_completed():
                self.after_idle(self.refresh_queue_display)
        except Exception as e:
            self.logger.error(f"Error clearing completed items: {e}", exc_info=True)
            ErrorDialog.show(self, "Couldn't clear the queue", str(e))

    @staticmethod
    def _item_title(item: DownloadItem) -> str:
        raw = item.custom_name or item.title or item.url
        return raw if len(raw) <= 64 else raw[:63] + "…"

    def _row_signature(self, item: DownloadItem):
        return (id(item), item.status, self._item_title(item), item.format, item.quality,
                item.error_message, item.clip_start, item.clip_end)

    def refresh_queue_display(self) -> None:
        """Rebuild rows only when the list or a row's state changed; otherwise
        update the live progress of the downloading row in place."""
        try:
            if not hasattr(self, 'queue_scroll') or not self.queue_scroll.winfo_exists():
                return
            items = self.queue.get_all()
            self.queue_count.configure(text=str(len(items)))
            signature = [self._row_signature(i) for i in items]
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
                return
            for i, item in enumerate(items):
                self.create_queue_item_widget(i, item)
        except Exception as e:
            self.logger.error(f"Error refreshing queue display: {e}", exc_info=True)

    def _build_empty_queue(self) -> None:
        p = self.palette
        box = customtkinter.CTkFrame(self.queue_scroll, fg_color="transparent")
        box.pack(fill="x", pady=(SPACING.xxl, SPACING.xl))
        img = icons.badge("download", 44, p.text_secondary, p.surface_raised)
        if img:
            customtkinter.CTkLabel(box, text="", image=img).pack()
        customtkinter.CTkLabel(box, text="Your queue is empty", font=TYPE.body_med,
                               text_color=p.text_primary).pack(pady=(SPACING.md, SPACING.xxs))
        customtkinter.CTkLabel(box, text="Add links with “Add to queue” or “Paste list”, then press Start.",
                               font=TYPE.caption, text_color=p.text_secondary).pack()

    def create_queue_item_widget(self, index: int, item: DownloadItem) -> None:
        p = self.palette
        row = customtkinter.CTkFrame(self.queue_scroll, fg_color=p.surface_raised, corner_radius=RADIUS.md + 2,
                                     border_width=0)
        row.pack(fill="x", pady=(0, SPACING.xs + 2), padx=SPACING.xs)
        row.grid_columnconfigure(1, weight=1)

        icon_name, role = _STATUS_ICON.get(item.status, ("clock", "text_secondary"))
        color = getattr(p, role)
        img = icons.icon(icon_name, 17, color)
        customtkinter.CTkLabel(row, text="" if img else "•", image=img, width=28, text_color=color).grid(
            row=0, column=0, rowspan=2, padx=(SPACING.md, SPACING.sm), pady=SPACING.md)

        customtkinter.CTkLabel(row, text=self._item_title(item), font=TYPE.body_med, text_color=p.text_primary,
                               anchor="w").grid(row=0, column=1, sticky="ew", pady=(SPACING.sm + 2, 0))

        widgets: Dict[str, Any] = {"row": row}
        if item.status == DownloadStatus.DOWNLOADING:
            line = customtkinter.CTkFrame(row, fg_color="transparent")
            line.grid(row=1, column=1, sticky="ew", pady=(SPACING.xs, SPACING.sm + 2))
            line.grid_columnconfigure(0, weight=1)
            bar = customtkinter.CTkProgressBar(line, height=4, corner_radius=RADIUS.pill,
                                               progress_color=p.accent, fg_color=p.surface_hover)
            bar.grid(row=0, column=0, sticky="ew", padx=(0, SPACING.md))
            stat = customtkinter.CTkLabel(line, text="", font=TYPE.mono, text_color=p.text_secondary, width=150,
                                          anchor="e")
            stat.grid(row=0, column=1, sticky="e")
            widgets.update(bar=bar, stat=stat)
        else:
            if item.status == DownloadStatus.FAILED:
                text, tcolor = (item.error_message or "Download failed").splitlines()[0][:90], p.error
            elif item.status == DownloadStatus.COMPLETED:
                text, tcolor = (os.path.basename(item.file_path) if item.file_path else "Saved"), p.text_secondary
            elif item.status == DownloadStatus.CANCELLED:
                text, tcolor = "Cancelled", p.text_secondary
            else:
                text, tcolor = "Waiting", p.text_secondary
            if item.clip_start or item.clip_end:
                text += "   ·   clip"
            customtkinter.CTkLabel(row, text=text, font=TYPE.caption, text_color=tcolor, anchor="w").grid(
                row=1, column=1, sticky="ew", pady=(0, SPACING.sm + 2))

        chip = f"{FormatManager.label(item.format)}  ·  {item.quality.split(' (')[0]}"
        customtkinter.CTkLabel(row, text=chip, font=TYPE.caption_med, text_color=p.text_secondary,
                               fg_color=p.surface, corner_radius=RADIUS.sm, height=24, padx=10).grid(
            row=0, column=2, rowspan=2, padx=SPACING.sm)

        menu_btn = IconButton(row, p, icon="more", size=32)
        menu_btn.configure(command=lambda b=menu_btn, idx=index, it=item: self._show_queue_menu(b, idx, it))
        menu_btn.grid(row=0, column=3, rowspan=2, padx=(0, SPACING.sm))

        self._queue_rows[id(item)] = widgets
        if item.status == DownloadStatus.DOWNLOADING:
            self._update_row_progress(item)

    def _update_row_progress(self, item: DownloadItem) -> None:
        w = self._queue_rows.get(id(item))
        if not w or "bar" not in w:
            return
        w["bar"].set(max(0.0, min(1.0, item.progress)))
        stage = item.stage if item.stage and item.stage != "Downloading" else ""
        spd = f"{item.speed / 1048576:.1f} MB/s" if item.speed else ""
        w["stat"].configure(text="  ".join(x for x in (stage, f"{int(item.progress * 100)}%", spd) if x))

    def _show_queue_menu(self, anchor_widget, index: int, item: DownloadItem) -> None:
        menu = PopupMenu(self, self.palette)
        if item.status in (DownloadStatus.FAILED, DownloadStatus.CANCELLED):
            menu.add("Retry", lambda: self._retry_queue_item(index), "refresh")
        if item.status == DownloadStatus.COMPLETED:
            menu.add("Show in folder", lambda: self._reveal_item(item), "folder")
            if item.file_path and os.path.exists(item.file_path):
                menu.add("Play", lambda: winsys.open_path(item.file_path), "play")
                menu.add("Rename file…", lambda: self._rename_queue_item(item), "rename")
        menu.add("Copy link", lambda: (self.clipboard_clear(), self.clipboard_append(item.url)), "link")
        if item.status != DownloadStatus.DOWNLOADING:
            menu.separator()
            menu.add("Remove", lambda: self.remove_queue_item(index), "delete", danger=True)
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

    def _retry_queue_item(self, index: int) -> None:
        if self.queue.retry(index):
            self.refresh_queue_display()

    def _reveal_item(self, item: DownloadItem) -> None:
        try:
            if item.file_path and os.path.exists(item.file_path):
                winsys.reveal_file(item.file_path)
            else:
                winsys.open_path(item.output_path or self.download_path)
        except Exception as e:
            self.logger.error(f"Could not open folder: {e}")

    def remove_queue_item(self, index: int) -> None:
        self.queue.remove(index)
        self.refresh_queue_display()

    def on_queue_update(self) -> None:
        """Queue status callback (may be a worker thread): only flag a redraw."""
        self._queue_dirty = True

    def _poll_queue(self) -> None:
        try:
            if self._queue_dirty:
                self._queue_dirty = False
                self.refresh_queue_display()
            running = self.queue.is_running()
            if self._queue_was_running and not running and not self.queue.get_pending():
                winsys.flash_taskbar(self)
            self._queue_was_running = running
            self._update_queue_button()
        except Exception as e:
            self.logger.debug(f"Queue poll error (non-critical): {e}")
        self.after(300, self._poll_queue)

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
        if self.is_downloading:
            self.stop_download()
        self.queue.stop()
        self.logger.info("Closing YouDownloader")
        self.destroy()
