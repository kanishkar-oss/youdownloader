"""Dialogs. All share one modal shell (_Dialog): dark title bar tinted to the
surface, a tone-colored icon badge, a left-aligned headline and body, and a
right-aligned button row (secondary, then primary). Esc cancels, Enter
confirms. Windows size themselves to their content.

Public API (unchanged call sites): ErrorDialog / InfoDialog / ConfirmDialog /
QualityWarningDialog / ConsentDialog / SettingsDialog / PasteListDialog, plus
RenameDialog.
"""
import os
import tkinter.filedialog
from typing import Callable, List, Optional, Tuple

import customtkinter

from src.ui import icons
from src.ui.palettes import SPACE
from src.ui.tokens import BORDER, HEIGHT, RADIUS, SPACING, TYPE, tracked
from src.ui.widgets.buttons import GhostButton, PrimaryButton, SecondaryButton, DangerButton
from src.ui.widgets.entry import FieldEntry
from src.ui.widgets.pip import StatusPip

P = SPACE

_TONES = {
    "error": ("error", P.error, P.error_subtle),
    "warning": ("warning", P.warning, P.warning_subtle),
    "success": ("check", P.success, P.success_subtle),
    "info": ("info", P.accent_hover, P.accent_subtle),
    "question": ("info", P.accent_hover, P.accent_subtle),
    "bolt": ("sparkle", P.starlight, "#0E2326"),
    "rename": ("rename", P.accent_hover, P.accent_subtle),
    "list": ("list", P.accent_hover, P.accent_subtle),
    "update": ("update", P.accent_hover, P.accent_subtle),
}


class _Dialog:
    """Modal shell. Build content into `self.body`, add buttons, then show()."""

    def __init__(self, parent, title: str, width: int = 420, size: Optional[Tuple[int, int]] = None):
        self.parent = parent
        self.root = parent.winfo_toplevel()
        self.width = width
        self.size = size
        self.on_cancel: Optional[Callable] = None
        self.on_primary: Optional[Callable] = None

        top = customtkinter.CTkToplevel(self.root)
        top.withdraw()
        top.title(title)
        top.configure(fg_color=P.surface)
        top.resizable(bool(size), bool(size))
        top.transient(self.root)
        self.top = top
        self.body = customtkinter.CTkFrame(top, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=SPACING.xl + 4, pady=(SPACING.xl, SPACING.lg))
        top.protocol("WM_DELETE_WINDOW", self._cancel)
        top.bind("<Escape>", lambda e: self._cancel())
        top.bind("<Return>", lambda e: self._primary())

    # ----- building blocks --------------------------------------------------

    def header(self, tone: str, title: str, message: str = "") -> None:
        # Fix the content width so short messages don't make a cramped window.
        customtkinter.CTkFrame(self.body, width=self.width, height=1, fg_color="transparent").pack(anchor="w")
        icon_name, color, fill = _TONES.get(tone, _TONES["info"])
        img = icons.badge(icon_name, 40, color, fill)
        if img:
            customtkinter.CTkLabel(self.body, text="", image=img).pack(anchor="w", pady=(0, SPACING.md))
        customtkinter.CTkLabel(self.body, text=title, font=TYPE.headline, text_color=P.text_primary,
                               anchor="w", justify="left", wraplength=self.width).pack(anchor="w", fill="x")
        if message:
            self.text(message).pack(anchor="w", fill="x", pady=(SPACING.xs + 2, 0))

    def text(self, message: str, color: str = None, font=None, parent=None):
        return customtkinter.CTkLabel(parent or self.body, text=message, font=font or TYPE.body,
                                      text_color=color or P.text_secondary, anchor="w",
                                      justify="left", wraplength=self.width)

    def buttons(self, primary: Tuple[str, Callable], secondary: Optional[Tuple[str, Callable]] = None,
                danger: bool = False, primary_icon: str = None) -> None:
        row = customtkinter.CTkFrame(self.top, fg_color="transparent")
        row.pack(fill="x", padx=SPACING.xl + 4, pady=(0, SPACING.xl))
        cls = DangerButton if danger else PrimaryButton
        btn = cls(row, P, text=primary[0], icon=primary_icon, height=HEIGHT.button_md,
                  font=TYPE.button, width=110, command=lambda: self._run(primary[1]))
        btn.pack(side="right")
        self.on_primary = primary[1]
        if secondary:
            SecondaryButton(row, P, text=secondary[0], command=lambda: self._run(secondary[1])).pack(
                side="right", padx=(0, SPACING.sm))
            self.on_cancel = secondary[1]

    # ----- lifecycle --------------------------------------------------------

    def _run(self, fn: Optional[Callable]) -> None:
        keep_open = fn() if fn else None
        if keep_open is not True:
            self.close()

    def _primary(self) -> None:
        if self.on_primary is not None:
            self._run(self.on_primary)

    def _cancel(self) -> None:
        if self.on_cancel:
            self._run(self.on_cancel)
        else:
            self.close()

    def close(self) -> None:
        try:
            self.top.grab_release()
            self.top.destroy()
        except Exception:
            pass

    def show(self) -> None:
        top = self.top
        if self.size:
            top.geometry(f"{self.size[0]}x{self.size[1]}")
        top.update_idletasks()
        w = top.winfo_reqwidth() if not self.size else top.winfo_width()
        h = top.winfo_reqheight() if not self.size else top.winfo_height()
        r = self.root
        x = r.winfo_rootx() + (r.winfo_width() - w) // 2
        y = r.winfo_rooty() + max(0, (r.winfo_height() - h) // 3)
        top.geometry(f"+{max(0, x)}+{max(0, y)}")
        top.deiconify()
        top.lift()
        from src.utils import winsys
        from src.ui.components import set_window_icon
        # CTkToplevel re-applies its own icon/title bar ~200ms after creation.
        top.after(260, lambda: (set_window_icon(top),
                                winsys.style_window(top, caption=P.surface, text=P.text_primary,
                                                    border=P.border_strong)))
        try:
            top.grab_set()
        except Exception:
            top.after(50, lambda: top.grab_set())
        top.focus_force()


# ----- simple dialogs ----------------------------------------------------------

class ErrorDialog:
    @staticmethod
    def show(parent, title: str, message: str, details: Optional[str] = None) -> None:
        d = _Dialog(parent, title)
        d.header("error", title, message)
        if details:
            box = customtkinter.CTkTextbox(d.body, height=110, width=d.width, font=TYPE.mono,
                                           fg_color=P.surface_raised, text_color=P.text_secondary,
                                           border_width=1, border_color=P.border_subtle)
            box.pack(fill="x", pady=(SPACING.md, 0))
            box.insert("1.0", details)
            box.configure(state="disabled")
        d.buttons(("OK", None))
        d.show()


class InfoDialog:
    @staticmethod
    def show(parent, title: str, message: str, callback: Optional[Callable] = None) -> None:
        d = _Dialog(parent, title)
        d.header("success" if "updated" in message.lower() else "info", title, message)
        d.buttons(("OK", callback))
        d.on_cancel = callback
        d.show()


class ConfirmDialog:
    @staticmethod
    def show(parent, title: str, message: str, callback: Callable[[bool], None],
             confirm_text: str = "Continue", cancel_text: str = "Cancel", danger: bool = False) -> None:
        d = _Dialog(parent, title)
        d.header("warning" if danger else "question", title, message)
        d.buttons((confirm_text, lambda: callback(True)), (cancel_text, lambda: callback(False)),
                  danger=danger)
        d.show()


class QualityWarningDialog:
    @staticmethod
    def show(parent, title: str, requested_quality: str, available_resolutions: list,
             callback: Callable[[bool], None]) -> None:
        d = _Dialog(parent, title)
        best = available_resolutions[0] if available_resolutions else None
        d.header("warning", f"{requested_quality} isn't available",
                 "This video doesn't come in that quality. "
                 + (f"The closest is {best}." if best else "We'll use the best it has."))
        if available_resolutions:
            customtkinter.CTkLabel(d.body, text=tracked("Available"), font=TYPE.overline,
                                   text_color=P.text_tertiary).pack(anchor="w", pady=(SPACING.lg, SPACING.xs))
            chips = customtkinter.CTkFrame(d.body, fg_color="transparent")
            chips.pack(anchor="w")
            for res in available_resolutions[:8]:
                customtkinter.CTkLabel(chips, text=res, font=TYPE.caption_med, text_color=P.text_primary,
                                       fg_color=P.surface_raised, corner_radius=RADIUS.sm,
                                       height=26, padx=10).pack(side="left", padx=(0, SPACING.xs))
        d.buttons(("Download best available", lambda: callback(True)), ("Cancel", lambda: callback(False)))
        d.show()


class ConsentDialog:
    @staticmethod
    def show(parent, callback: Callable[[bool], None]) -> None:
        d = _Dialog(parent, "Speed solver updates", width=440)
        d.header(
            "bolt", "Keep downloads fast?",
            "A small JavaScript solver gets around YouTube's throttling (about 0.3 Mbps "
            "without it). A copy is bundled and runs locally.\n\n"
            "When YouTube changes, yt-dlp can fetch an updated solver from GitHub. That "
            "runs code from the internet, so it's off unless you allow it. You can change "
            "this any time in Settings.")
        d.buttons(("Allow updates", lambda: callback(True)), ("Bundled only", lambda: callback(False)))
        d.on_cancel = None  # closing the window = decide later
        d.show()


class RenameDialog:
    """Ask for a new file name. `on_submit(name)` returns an error string to
    keep the dialog open, or None when the rename succeeded."""

    @staticmethod
    def show(parent, current_stem: str, extension: str,
             on_submit: Callable[[str], Optional[str]], title: str = "Rename file") -> None:
        d = _Dialog(parent, title, width=440)
        d.header("rename", title, "Change the name of the downloaded file. The extension stays the same.")
        row = customtkinter.CTkFrame(d.body, fg_color="transparent")
        row.pack(fill="x", pady=(SPACING.lg, 0))
        entry = FieldEntry(row, P)
        entry.pack(side="left", fill="x", expand=True)
        entry.insert(0, current_stem)
        if extension:
            customtkinter.CTkLabel(row, text=extension, font=TYPE.mono, text_color=P.text_tertiary,
                                   fg_color=P.surface_raised, corner_radius=RADIUS.sm, height=HEIGHT.entry,
                                   padx=10).pack(side="left", padx=(SPACING.sm, 0))
        err = d.text("", color=P.error, font=TYPE.caption)
        err.pack(anchor="w", fill="x", pady=(SPACING.xs, 0))

        def submit():
            message = on_submit(entry.get())
            if message:
                err.configure(text=message)
                return True  # keep open
            return None

        d.buttons(("Rename", submit), ("Cancel", None), primary_icon="rename")
        d.show()
        entry.focus_set()
        entry.select_range(0, "end")


class PasteListDialog:
    """Paste many YouTube links (one per line) to add them all to the queue."""

    @staticmethod
    def show(parent, on_submit: Callable[[str], None]) -> None:
        d = _Dialog(parent, "Paste list", width=480)
        d.header("list", "Add several links",
                 "Paste YouTube links, one per line. They're queued with the current format, "
                 "quality and folder.")
        box = customtkinter.CTkTextbox(d.body, height=170, width=d.width, font=TYPE.body,
                                       fg_color=P.surface_raised, text_color=P.text_primary,
                                       border_width=1, border_color=P.border_input,
                                       corner_radius=RADIUS.md, wrap="none")
        box.pack(fill="x", pady=(SPACING.lg, SPACING.xs))
        count = d.text("", font=TYPE.caption)
        count.pack(anchor="w")

        def recount(_e=None):
            n = sum(1 for t in box.get("1.0", "end").split() if "youtu" in t)
            count.configure(text=f"{n} link{'s' if n != 1 else ''} found")

        try:
            clip = parent.clipboard_get()
            if "youtu" in clip:
                box.insert("1.0", clip)
        except Exception:
            pass
        box.bind("<KeyRelease>", recount)
        recount()
        d.buttons(("Add to queue", lambda: on_submit(box.get("1.0", "end"))), ("Cancel", None),
                  primary_icon="add")
        d.top.unbind("<Return>")  # Enter adds a new line here
        d.show()
        box.focus_set()


class UpdateDialog:
    """A new app version: release notes, then download (with progress), unpack
    and check it off the UI thread, and hand the result to `on_install(prep)`,
    which launches the installer and quits the app."""

    @staticmethod
    def show(parent, release, on_install: Callable) -> None:
        import threading
        from src.utils import app_update, winsys
        from src.version import __version__

        blocker = app_update.install_blocker() if release.asset_url else None
        can_install = bool(release.asset_url) and blocker is None

        d = _Dialog(parent, "Update available", width=460)
        d.header("update", f"YouDownloader {release.version} is available",
                 f"You have {__version__}. Updating takes a minute and restarts the app; "
                 "your queue and settings are kept." if can_install else
                 f"You have {__version__}. " + (blocker or "Download it from the release page."))
        if release.notes:
            customtkinter.CTkLabel(d.body, text=tracked("What's new"), font=TYPE.overline,
                                   text_color=P.text_tertiary).pack(anchor="w", pady=(SPACING.lg, SPACING.xs))
            notes = customtkinter.CTkTextbox(d.body, height=130, width=d.width, font=TYPE.body,
                                             fg_color=P.surface_raised, text_color=P.text_secondary,
                                             border_width=1, border_color=P.border_subtle,
                                             corner_radius=RADIUS.md, wrap="word")
            notes.pack(fill="x")
            notes.insert("1.0", release.notes)
            notes.configure(state="disabled")

        status = d.text("", font=TYPE.caption)
        bar = customtkinter.CTkProgressBar(d.body, height=HEIGHT.progress, corner_radius=RADIUS.pill,
                                           progress_color=P.accent, fg_color=P.surface_hover)
        bar.set(0)

        row = customtkinter.CTkFrame(d.top, fg_color="transparent")
        row.pack(fill="x", padx=SPACING.xl + 4, pady=(0, SPACING.xl))
        primary = PrimaryButton(row, P, text="Update now" if can_install else "Open download page",
                                icon="download", height=HEIGHT.button_md, font=TYPE.button, width=150)
        primary.pack(side="right")
        secondary = SecondaryButton(row, P, text="Later")
        secondary.pack(side="right", padx=(0, SPACING.sm))

        # phase: idle -> downloading -> installing (no way back once installing)
        state = {"cancelled": False, "phase": "idle"}

        def alive() -> bool:
            try:
                return bool(d.top.winfo_exists())
            except Exception:
                return False

        def on_ui(fn):
            try:
                d.root.after(0, lambda: alive() and fn())
            except Exception:
                pass

        def fail(message: str):
            state["phase"] = "idle"
            status.configure(text=message, text_color=P.error)
            primary.configure(state="normal", text="Try again")
            secondary.configure(text="Close")

        def start():
            if not can_install:
                winsys.open_url(release.page_url)
                d.close()
                return
            if state["phase"] != "idle":
                return
            state.update(phase="downloading", cancelled=False)
            primary.configure(state="disabled", text="Downloading…")
            secondary.configure(text="Cancel")
            status.configure(text="Downloading the update…", text_color=P.text_secondary)
            status.pack(anchor="w", fill="x", pady=(SPACING.lg, SPACING.xs))
            bar.pack(fill="x")
            bar.set(0)

            def work():
                try:
                    path = app_update.download(
                        release, on_progress=lambda f: on_ui(lambda: (
                            bar.set(f), status.configure(text=f"Downloading the update…  {int(f * 100)}%"))),
                        is_cancelled=lambda: state["cancelled"])
                    if path is None:
                        return  # cancelled; the dialog already closed
                    on_ui(lambda: status.configure(text="Checking the update…"))
                    prep = app_update.prepare(path, release.version)
                except app_update.UpdateError as e:
                    on_ui(lambda msg=str(e): fail(msg))
                    return
                except Exception as e:  # never leave the dialog stuck on "Downloading…"
                    on_ui(lambda msg=f"The update failed: {e}": fail(msg))
                    return
                if state["cancelled"]:
                    app_update.discard(prep)
                    return

                def finish():
                    state["phase"] = "installing"
                    status.configure(text="Installing… YouDownloader will restart.", text_color=P.text_secondary)
                    primary.configure(text="Installing…")
                    secondary.configure(state="disabled")
                    # On the root, not the dialog: closing the dialog must not cancel this.
                    d.root.after(400, lambda: (d.close(), on_install(prep)))
                on_ui(finish)
            threading.Thread(target=work, daemon=True).start()

        def later():
            if state["phase"] == "installing":
                return  # too late to cancel; the app is about to restart
            if state["phase"] == "downloading":
                state["cancelled"] = True
            d.close()

        primary.configure(command=start)
        secondary.configure(command=later)
        d.on_primary = lambda: (start(), True)[1]
        d.on_cancel = lambda: (later(), state["phase"] == "installing")[1]
        d.show()


def _reveal(path: str) -> None:
    from src.utils import winsys
    try:
        winsys.reveal_file(path)
    except Exception:
        pass


# ----- settings ------------------------------------------------------------------

class SettingsDialog:
    """Settings as grouped cards: Downloads, YouTube sign-in, Downloader, Interface."""

    @staticmethod
    def show(parent) -> None:
        from src.utils import cookies as cookie_store
        from src.utils import updater

        d = _Dialog(parent, "Settings", width=470, size=(560, 720))
        d.body.pack_configure(padx=0, pady=0)
        scroll = customtkinter.CTkScrollableFrame(
            d.body, fg_color="transparent", scrollbar_button_color=P.border_strong,
            scrollbar_button_hover_color=P.text_disabled)
        scroll.pack(fill="both", expand=True, padx=SPACING.md, pady=(SPACING.lg, 0))

        customtkinter.CTkLabel(scroll, text="Settings", font=TYPE.headline, text_color=P.text_primary
                               ).pack(anchor="w", padx=SPACING.md, pady=(SPACING.xs, SPACING.lg))

        def card(title: str):
            customtkinter.CTkLabel(scroll, text=tracked(title), font=TYPE.overline,
                                   text_color=P.text_tertiary).pack(anchor="w", padx=SPACING.md + 2,
                                                                    pady=(SPACING.sm, SPACING.xs))
            frame = customtkinter.CTkFrame(scroll, fg_color=P.surface_raised, corner_radius=RADIUS.lg,
                                           border_width=BORDER.hairline, border_color=P.border_subtle)
            frame.pack(fill="x", padx=SPACING.sm, pady=(0, SPACING.md))
            return frame

        def divider(frame):
            customtkinter.CTkFrame(frame, height=1, fg_color=P.border_subtle).pack(fill="x", padx=SPACING.lg)

        def row(frame, title: str, desc: str = ""):
            r = customtkinter.CTkFrame(frame, fg_color="transparent")
            r.pack(fill="x", padx=SPACING.lg, pady=SPACING.md)
            left = customtkinter.CTkFrame(r, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True)
            customtkinter.CTkLabel(left, text=title, font=TYPE.body_med, text_color=P.text_primary,
                                   anchor="w", height=20).pack(anchor="w")
            desc_lbl = None
            if desc:
                desc_lbl = customtkinter.CTkLabel(left, text=desc, font=TYPE.caption, text_color=P.text_secondary,
                                                  anchor="w", justify="left", wraplength=280, height=18)
                desc_lbl.pack(anchor="w", pady=(2, 0))
            right = customtkinter.CTkFrame(r, fg_color="transparent")
            right.pack(side="right", padx=(SPACING.md, 0))
            return right, desc_lbl

        def switch(parent_frame, key: str, default: bool, on_change=None):
            sw = customtkinter.CTkSwitch(parent_frame, text="", width=46, switch_width=40, switch_height=22,
                                         progress_color=P.accent, button_color="#FFFFFF",
                                         button_hover_color="#E9E7FF", fg_color=P.border_input)
            sw.select() if parent.config.get(key, default) else sw.deselect()

            def changed():
                parent.config.set(key, bool(sw.get()))
                if on_change:
                    on_change(bool(sw.get()))
            sw.configure(command=changed)
            sw.pack()
            return sw

        # --- Downloads ---
        c = card("Downloads")
        right, _ = row(c, "Cover art & tags", "Embed title, artist, date and artwork (MP3, MP4).")
        switch(right, "embed_metadata", True, lambda _v: parent.apply_download_settings())
        divider(c)
        right, _ = row(c, "Subtitles", "Save .srt subtitles next to videos.")
        switch(right, "auto_download_subtitles", False, lambda _v: parent.apply_download_settings())
        divider(c)
        right, _ = row(c, "Subtitle language", "Language code, e.g. en, es, fr, ja.")
        lang = FieldEntry(right, P, width=72, height=HEIGHT.button_sm, justify="center")
        lang.insert(0, parent.config.get("subtitle_language") or "en")
        lang.pack()

        def save_lang(_e=None):
            parent.config.set("subtitle_language", lang.get().strip() or "en")
            parent.apply_download_settings()
        lang.bind("<KeyRelease>", save_lang)  # save as you type
        divider(c)
        from src.utils import paths as _paths
        right, _ = row(c, "Browser button",
                       "A bookmark that sends the YouTube video you're watching straight here, in any browser."
                       + ("" if _paths.FROZEN else " (Works in the installed app.)"))

        def setup_browser_button():
            page = _paths.resource("assets", "browser-button.html")
            try:
                from src.utils import winsys
                winsys.open_path(page)
            except Exception as e:
                ErrorDialog.show(d.top, "Couldn't open the setup page", str(e))
        SecondaryButton(right, P, text="Set up", icon="open", width=96, height=HEIGHT.button_sm,
                        command=setup_browser_button).pack()

        # --- YouTube sign-in ---
        c = card("YouTube sign-in")
        status_row = customtkinter.CTkFrame(c, fg_color="transparent")
        status_row.pack(fill="x", padx=SPACING.lg, pady=(SPACING.md, 0))
        dot = StatusPip(status_row, color=P.text_disabled, size=8, bg=P.surface_raised)
        dot.pack(side="left", padx=(0, SPACING.sm))
        status = customtkinter.CTkLabel(status_row, text="", font=TYPE.body_med, text_color=P.text_primary,
                                        anchor="w")
        status.pack(side="left")

        # Where the active file lives (it's in a hidden folder, so say so).
        where_row = customtkinter.CTkFrame(c, fg_color="transparent")
        where = customtkinter.CTkLabel(where_row, text="", font=TYPE.mono, text_color=P.text_secondary,
                                       anchor="w")
        where.pack(side="left")
        show_btn = GhostButton(where_row, P, text="Show file", icon="folder",
                               command=lambda: parent.cookie_file and _reveal(parent.cookie_file))
        show_btn.pack(side="left", padx=(SPACING.sm, 0))

        help_lbl = customtkinter.CTkLabel(
            c, font=TYPE.caption, text_color=P.text_secondary, anchor="w", justify="left", wraplength=440, text="")
        help_lbl.pack(anchor="w", padx=SPACING.lg, pady=(SPACING.xs, SPACING.md))

        btns = customtkinter.CTkFrame(c, fg_color="transparent")
        btns.pack(fill="x", padx=SPACING.lg, pady=(0, SPACING.lg))
        choose_btn = SecondaryButton(btns, P, text="Choose cookies.txt…", icon="folder",
                                     height=HEIGHT.button_sm, width=236)
        choose_btn.pack(side="left", padx=(0, SPACING.sm))
        remove_btn = GhostButton(btns, P, text="Remove", icon="delete")
        remove_btn.pack(side="left")

        def refresh_cookie_status():
            info = cookie_store.inspect(parent.cookie_file)
            signed_in = bool(parent.cookie_file and info["ok"] and info["signed_in"])
            if not parent.cookie_file:
                dot.set_color(P.text_disabled)
                status.configure(text="Not signed in  ·  some videos may be limited to 360p")
            elif signed_in:
                dot.set_color(P.success)
                exp = info["expires"]
                status.configure(text="Signed in" + (f"  ·  valid until {exp:%d %b %Y}" if exp else ""))
            else:
                dot.set_color(P.warning)
                status.configure(text=info["error"] or "Cookies aren't from a signed-in session")

            if parent.cookie_file:
                where.configure(text=cookie_store.display_path(parent.cookie_file))
                where_row.pack(fill="x", padx=SPACING.lg, pady=(SPACING.xs, 0), after=status_row)
                remove_btn.pack(side="left")
            else:
                where_row.pack_forget()
                remove_btn.pack_forget()

            if signed_in:
                help_lbl.configure(text="You're all set: this file is used automatically and there's nothing "
                                        "to select. Only choose a new file when this one expires or you "
                                        "want to use a different Google account.")
                choose_btn.configure(text="Replace cookies.txt…")
            else:
                help_lbl.configure(text="Most videos download in full quality without signing in, but YouTube "
                                        "limits some (and HD clips) to signed-in sessions. On "
                                        "youtube.com (signed in), use the \u201cGet cookies.txt LOCALLY\u201d "
                                        "browser extension to Export a cookies file, then choose it here. "
                                        "It's copied to a private app folder (not synced by OneDrive or "
                                        "iCloud), so you can delete the export afterwards.")
                choose_btn.configure(text="Choose cookies.txt…")
            if hasattr(parent, "refresh_signin_chip"):
                parent.refresh_signin_chip()

        def choose_cookies():
            # Start where an export actually is: newest *cookie*.txt in Downloads /
            # Desktop / Documents, else the folder of the file in use.
            exports = cookie_store.find_exports()
            if exports:
                initialdir, initialfile = os.path.split(exports[0])
            elif parent.cookie_file:
                initialdir, initialfile = os.path.split(parent.cookie_file)
            else:
                initialdir, initialfile = os.path.join(os.path.expanduser("~"), "Downloads"), ""
            path = tkinter.filedialog.askopenfilename(
                parent=d.top, title="Select your exported cookies.txt",
                initialdir=initialdir, initialfile=initialfile,
                filetypes=[("Cookies file", "*.txt"), ("All files", "*.*")])
            if not path:
                return
            info = cookie_store.inspect(path)
            if not info["ok"]:
                ErrorDialog.show(d.top, "Can't use that file", info["error"])
                return
            try:
                parent.set_cookie_file(cookie_store.import_cookies(path))
            except OSError as e:
                ErrorDialog.show(d.top, "Import failed", f"Couldn't import the file: {e}")
                return
            refresh_cookie_status()

        def clear_cookies():
            def confirmed(yes: bool):
                if not yes:
                    return
                parent.set_cookie_file(None)
                try:
                    if os.path.isfile(cookie_store.DEFAULT_COOKIES_PATH):
                        os.remove(cookie_store.DEFAULT_COOKIES_PATH)
                except OSError:
                    pass
                refresh_cookie_status()
            ConfirmDialog.show(d.top, "Remove sign-in?",
                               "The imported cookies.txt will be deleted. Some videos (and HD clips) may "
                               "be limited to 360p until you choose a new one.", confirmed,
                               confirm_text="Remove", danger=True)

        choose_btn.configure(command=choose_cookies)
        remove_btn.configure(command=clear_cookies)
        refresh_cookie_status()

        # --- Downloader ---
        c = card("Downloader")
        from src.utils import paths, ytdlp_override
        age = updater.ytdlp_age_days()
        released = f"Released {age} days ago. " if age is not None else ""
        if not paths.FROZEN:
            ver_desc = released + "YouTube changes often; keep it current."
        elif ytdlp_override.state.get("active"):
            ver_desc = (released + f"Downloaded by the app (the built-in one is "
                        f"{ytdlp_override.state.get('bundled')}).")
        else:
            ver_desc = released + "Built into the app. Newer versions with YouTube fixes download automatically."
        right, ver_lbl = row(c, f"yt-dlp {updater.ytdlp_version()}", ver_desc)

        def do_update():
            update_btn.configure(state="disabled", text="Updating…")
            if ver_lbl:
                ver_lbl.configure(text="Updating yt-dlp… this can take a minute.")

            def done(ok, msg):
                try:
                    update_btn.configure(state="normal", text="Check for update")
                    if ver_lbl:
                        ver_lbl.configure(text=msg)
                except Exception:
                    pass
            parent._update_ytdlp(on_done=done)

        update_btn = SecondaryButton(right, P, text="Check for update", icon="refresh", width=176,
                                     height=HEIGHT.button_sm, command=do_update)
        update_btn.pack()
        if paths.FROZEN:
            divider(c)
            right, _ = row(c, "Download YouTube fixes automatically",
                           "Get new yt-dlp versions in the background (about 3 MB); they're used "
                           "from the next start.")
            switch(right, "auto_update_ytdlp", True)
            if ytdlp_override.state.get("active"):
                divider(c)
                right, back_lbl = row(c, "Use the built-in yt-dlp",
                                      f"Go back to {ytdlp_override.state.get('bundled')} if the newer one "
                                      "causes problems (takes effect after a restart).")

                def use_builtin():
                    parent.config.set("auto_update_ytdlp", False)
                    ytdlp_override.reset()
                    if back_lbl:
                        back_lbl.configure(text="Done: the built-in yt-dlp is used from the next start, and "
                                                "automatic yt-dlp updates are off.")
                    back_btn.configure(state="disabled")
                back_btn = SecondaryButton(right, P, text="Use built-in", width=120, height=HEIGHT.button_sm,
                                           command=use_builtin)
                back_btn.pack()
        divider(c)
        right, _ = row(c, "Solver updates from GitHub",
                       "Let yt-dlp fetch a newer throttling solver when the bundled one is outdated.")

        def set_consent(on: bool):
            parent.allow_remote = on
            parent.queue.allow_remote_components = on
        switch(right, "js_runtime_consent", False, set_consent)

        # --- Interface ---
        c = card("Interface")
        right, _ = row(c, "Motion", "Twinkling stars, orbit and button transitions.")
        switch(right, "visual_effects_enabled", True)
        divider(c)
        right, _ = row(c, "Notify when downloads finish",
                       "A desktop notification when a download or the queue is done while the app "
                       "is in the background.")
        switch(right, "notifications_enabled", True)
        divider(c)
        right, _ = row(c, "Setup notices", "Show dismissed FFmpeg / Deno / yt-dlp notices again.")

        def reshow():
            for key in ("banner_dismissed_ffmpeg", "banner_dismissed_deno", "banner_dismissed_ytdlp"):
                parent.config.set(key, False)
            d.close()
            parent.rebuild_ui()
        SecondaryButton(right, P, text="Show again", height=HEIGHT.button_sm, command=reshow).pack()

        # --- About & updates ---
        from src.utils import app_update
        from src.version import __version__
        c = card("About & updates")
        if app_update.can_self_install():
            about_desc = "New versions are installed from GitHub releases."
        else:
            about_desc = "Running from source: update with git pull."
        right, about_lbl = row(c, f"YouDownloader {__version__}", about_desc)

        def check_now():
            check_btn.configure(state="disabled", text="Checking…")

            def done(release, error):
                settings_open = False
                try:
                    settings_open = bool(d.top.winfo_exists())
                except Exception:
                    pass
                if not settings_open:
                    # Settings was closed while checking: still tell them.
                    if release is not None:
                        parent.show_update(release)
                    return
                check_btn.configure(state="normal", text="Check for updates")
                if error:
                    about_lbl.configure(text=error)
                elif release is None:
                    about_lbl.configure(text=f"You're up to date ({__version__} is the latest).")
                else:
                    d.close()
                    parent.show_update(release)
            parent.check_for_app_update(manual=True, on_result=done)

        check_btn = SecondaryButton(right, P, text="Check for updates", icon="refresh", width=176,
                                    height=HEIGHT.button_sm, command=check_now)
        check_btn.pack()
        divider(c)
        right, _ = row(c, "Check automatically", "Look for a new version each time the app opens.")
        switch(right, "auto_check_updates", True)
        divider(c)
        right, report_lbl = row(c, "Report a problem",
                                "Copies app and system details plus recent log lines (never cookies or "
                                "passwords). Paste it into your message.")

        def copy_diagnostics():
            from src.utils import diagnostics
            try:
                diagnostics.copy_to_clipboard(parent)
            except Exception as e:
                ErrorDialog.show(d.top, "Couldn't copy the details", str(e))
                return
            diag_btn.configure(text="Copied")
            if report_lbl:
                report_lbl.configure(text="Copied to the clipboard. Paste it into your message, with what you "
                                          "did and the YouTube link.")
            d.top.after(2500, lambda: diag_btn.winfo_exists() and diag_btn.configure(text="Copy diagnostics"))
        diag_btn = SecondaryButton(right, P, text="Copy diagnostics", icon="copy", width=176,
                                   height=HEIGHT.button_sm, command=copy_diagnostics)
        diag_btn.pack()
        divider(c)
        right, _ = row(c, "Open-source licenses", "YouDownloader is MIT-licensed and includes FFmpeg, "
                                                  "Deno, Python and other open-source software.")

        def show_licenses():
            from src.utils import paths, winsys
            notices = paths.resource("licenses", "THIRD-PARTY-NOTICES.txt")
            try:
                if os.path.isfile(notices):
                    winsys.open_path(notices)
                else:  # running from source: the summary in the repo
                    from src.version import GITHUB_REPO
                    winsys.open_url(f"https://github.com/{GITHUB_REPO}/blob/main/THIRD-PARTY-NOTICES.md")
            except Exception as e:
                ErrorDialog.show(d.top, "Couldn't open the licenses", str(e))
        SecondaryButton(right, P, text="View", icon="open", width=96, height=HEIGHT.button_sm,
                        command=show_licenses).pack()

        footer = customtkinter.CTkFrame(d.top, fg_color="transparent")
        footer.pack(fill="x", padx=SPACING.xl + 4, pady=SPACING.lg)
        PrimaryButton(footer, P, text="Done", height=HEIGHT.button_md, font=TYPE.button,
                      width=120, command=d.close).pack(side="right")
        d.show()
