"""Reusable UI components"""
import customtkinter
from typing import Optional
from PIL import Image
import os
import sys
from src.ui.tokens import SPACING, RADIUS, HEIGHT, MOTION, TYPE
from src.ui.palettes import Palette
from src.utils import paths

# Resolve assets relative to the project / app bundle, not the working directory.
_LOGO_PATH = paths.resource("assets", "logo.png")
_ICON_PATH = paths.resource("assets", "youdownloader.ico")


def set_window_icon(window) -> None:
    """Set the window/taskbar icon.

    Windows: the square .ico (CTk's own iconbitmap() records that an icon was
    set, so CTk won't replace it with its default). macOS: the packaged .app
    has its own .icns in the Dock; from source, set the Dock icon from the
    .ico's largest frame. iconphoto() needs a Tk PhotoImage (not a CTkImage),
    kept alive on the window.
    """
    try:
        if sys.platform == "win32" and os.path.isfile(_ICON_PATH):
            window.iconbitmap(_ICON_PATH)
            return
        if sys.platform == "darwin" and paths.FROZEN:
            return
        from PIL import ImageTk
        if getattr(window, "_icon_photo", None) is None:
            square = paths.resource("assets", "icon.png")
            src = next((p for p in (square, _ICON_PATH, _LOGO_PATH) if os.path.isfile(p)), _LOGO_PATH)
            img = Image.open(src)
            if src.endswith(".ico"):
                img.size = max(img.info.get("sizes") or [img.size])
                img.load()
            img = img.convert("RGBA")
            img.thumbnail((256, 256), Image.Resampling.LANCZOS)
            window._icon_photo = ImageTk.PhotoImage(img)
        window.iconphoto(True, window._icon_photo)
    except Exception:
        pass  # Cosmetic only.


class LogoLoader:
    """Handles logo loading and display"""
    
    @staticmethod
    def load_logo(logo_path: str = _LOGO_PATH) -> Optional[customtkinter.CTkImage]:
        """
        Load logo image if available.
        
        Args:
            logo_path: Path to logo file
            
        Returns:
            CTkImage object or None
        """
        if os.path.exists(logo_path):
            try:
                img = Image.open(logo_path)
                img.thumbnail((200, 120), Image.Resampling.LANCZOS)
                # Convert to CTkImage for proper HighDPI support
                return customtkinter.CTkImage(light_image=img, dark_image=img, size=(200, 120))
            except Exception:
                return None
        return None


class ProgressDisplay:
    """
    Status panel: a status line (left, e.g. "Video stream  42%") and a mono
    stats readout (right, speed · time left), over a thin rounded progress bar.
    Native indeterminate mode covers "Preparing" / "Processing".

    API: reset(), update_progress(percent, details, speed, stage),
    start_indeterminate(text), stop_indeterminate(), set_status(text, color, stats),
    and the `details_label` (status line) / `stats_label` attributes.
    """

    _TICK_MS = max(1, 1000 // MOTION.fps)

    def __init__(self, parent, palette: Palette):
        self.parent = parent
        self.palette = palette
        self.current_progress = 0.0
        self.target_progress = 0.0
        self.animation_id = None
        self._indeterminate = False

        line = customtkinter.CTkFrame(parent, fg_color="transparent")
        line.pack(fill="x")
        self.details_label = customtkinter.CTkLabel(
            line, text="Ready", font=TYPE.body_med, text_color=palette.text_primary, anchor="w",
        )
        self.details_label.pack(side="left")
        self.stats_label = customtkinter.CTkLabel(
            line, text="", font=TYPE.mono, text_color=palette.text_secondary, anchor="e",
        )
        self.stats_label.pack(side="right")

        self.progress_bar = customtkinter.CTkProgressBar(
            parent, height=HEIGHT.progress, corner_radius=RADIUS.pill,
            progress_color=palette.accent, fg_color=palette.surface_hover, border_width=0,
        )
        self.progress_bar.pack(fill="x", pady=(SPACING.sm, 0))
        self._set_bar(0)
        self.progress_bar.bind("<Destroy>", self._on_destroy)
        self._idle_hint = ""

    def set_idle_hint(self, hint: str) -> None:
        self._idle_hint = hint
        if not self._indeterminate and self.target_progress == 0:
            self._show_hint()

    def _show_hint(self) -> None:
        # The idle shortcut hint is quiet body text; the mono face is for live stats.
        self.stats_label.configure(text=self._idle_hint, font=TYPE.caption,
                                   text_color=self.palette.text_tertiary)

    def _on_destroy(self, _event=None) -> None:
        if self.animation_id:
            try:
                self.parent.after_cancel(self.animation_id)
            except Exception:
                pass
            self.animation_id = None

    def _set_bar(self, value: float) -> None:
        # CTk draws a dot for 0; hide it by matching the track color.
        self.progress_bar.configure(progress_color=self.palette.accent if value > 0.004
                                    else self.palette.surface_hover)
        self.progress_bar.set(value)

    def animate_progress(self) -> None:
        if self._indeterminate:
            self.animation_id = None
            return
        if abs(self.current_progress - self.target_progress) < 0.001:
            self._set_bar(self.target_progress)
            self.animation_id = None
            return
        self.current_progress += (self.target_progress - self.current_progress) * MOTION.interp
        self._set_bar(self.current_progress)
        self.animation_id = self.parent.after(self._TICK_MS, self.animate_progress)

    def set_status(self, text: str, color: str = None, stats: str = "") -> None:
        self.details_label.configure(text=text, text_color=color or self.palette.text_primary)
        self.stats_label.configure(text=stats, font=TYPE.mono, text_color=self.palette.text_secondary)

    def start_indeterminate(self, text: str = "Preparing…") -> None:
        self.set_status(text, self.palette.text_primary, "")
        if self._indeterminate:
            return  # already animating; start() again would stack a second loop
        self._indeterminate = True
        if self.animation_id:
            self.parent.after_cancel(self.animation_id)
            self.animation_id = None
        self.progress_bar.configure(mode="indeterminate", indeterminate_speed=0.6,
                                    progress_color=self.palette.accent)
        self.progress_bar.start()

    def stop_indeterminate(self) -> None:
        self._indeterminate = False
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self._set_bar(self.current_progress)

    def update_progress(self, percent: float, details: str = "", speed: float = 0.0,
                        stage: str = None) -> None:
        if self._indeterminate:
            self.stop_indeterminate()
        percent = max(0.0, min(1.0, percent))
        self.target_progress = percent
        if self.animation_id is None:
            self.animate_progress()
        label = stage or "Downloading"
        self.set_status(f"{label}   {int(percent * 100)}%", self.palette.text_primary, details)

    def complete(self) -> None:
        """Snap the bar to full (no easing) for the finished state."""
        if self._indeterminate:
            self.stop_indeterminate()
        if self.animation_id:
            self.parent.after_cancel(self.animation_id)
            self.animation_id = None
        self.current_progress = self.target_progress = 1.0
        self._set_bar(1.0)

    def reset(self) -> None:
        self.stop_indeterminate()
        self.current_progress = 0.0
        self.target_progress = 0.0
        self._set_bar(0)
        self.set_status("Ready", self.palette.text_primary)
        self._show_hint()
        if self.animation_id:
            self.parent.after_cancel(self.animation_id)
            self.animation_id = None
