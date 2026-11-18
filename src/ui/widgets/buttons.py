"""Button family. Every variant reads tokens + palette and takes an optional
`icon=` name (rendered from the icon font, left of the label).

- PrimaryButton   — filled violet; the one main action on screen
- SecondaryButton — raised surface with a hairline border
- GhostButton     — text only, surface tint on hover (toolbar actions)
- IconButton      — square, icon only
- DangerButton    — outlined in the error color (Stop)
"""
import customtkinter

from src.ui import icons
from src.ui.tokens import RADIUS, BORDER, HEIGHT, TYPE
from src.ui.palettes import Palette


def _with_icon(opts: dict, icon_name, size: int, color: str) -> dict:
    if icon_name:
        img = icons.icon(icon_name, size, color)
        if img is not None:
            opts.setdefault("image", img)
            opts.setdefault("compound", "left")
    return opts


class _IconTextButton(customtkinter.CTkButton):
    """Remembers its icon so it can be re-tinted when the text color changes."""

    def __init__(self, parent, icon_name=None, icon_size=16, **opts):
        self._icon_name = icon_name
        self._icon_size = icon_size
        super().__init__(parent, **opts)

    def set_icon(self, icon_name, color=None) -> None:
        self._icon_name = icon_name
        img = icons.icon(icon_name, self._icon_size, color or self.cget("text_color")) if icon_name else None
        self.configure(image=img)


class PrimaryButton(_IconTextButton):
    def __init__(self, parent, palette: Palette, icon=None, **kwargs):
        opts = dict(
            height=HEIGHT.button_lg, corner_radius=RADIUS.md, font=TYPE.button_lg,
            fg_color=palette.accent, hover_color=palette.accent_hover,
            text_color=palette.on_accent, text_color_disabled="#C9C3FF",
            border_width=0,
        )
        opts.update(kwargs)
        super().__init__(parent, icon_name=icon, icon_size=18,
                         **_with_icon(opts, icon, 18, palette.on_accent))


class SecondaryButton(_IconTextButton):
    def __init__(self, parent, palette: Palette, icon=None, **kwargs):
        opts = dict(
            height=HEIGHT.button_md, corner_radius=RADIUS.md, font=TYPE.button,
            fg_color=palette.surface_raised, border_width=BORDER.hairline,
            border_color=palette.border_strong, text_color=palette.text_primary,
            text_color_disabled=palette.text_disabled, hover_color=palette.surface_hover,
        )
        opts.update(kwargs)
        super().__init__(parent, icon_name=icon,
                         **_with_icon(opts, icon, 16, opts["text_color"]))


class GhostButton(_IconTextButton):
    def __init__(self, parent, palette: Palette, icon=None, **kwargs):
        opts = dict(
            height=HEIGHT.button_sm, width=40, corner_radius=RADIUS.sm, font=TYPE.label,
            fg_color="transparent", text_color=palette.text_secondary,
            text_color_disabled=palette.text_disabled, hover_color=palette.surface_hover,
            border_width=0,
        )
        opts.update(kwargs)
        super().__init__(parent, icon_name=icon, icon_size=15,
                         **_with_icon(opts, icon, 15, opts["text_color"]))


class DangerButton(_IconTextButton):
    def __init__(self, parent, palette: Palette, icon=None, **kwargs):
        opts = dict(
            height=HEIGHT.button_md, corner_radius=RADIUS.md, font=TYPE.button,
            fg_color=palette.error_subtle, border_width=BORDER.hairline,
            border_color=palette.error, text_color=palette.error,
            hover_color="#3A1824",
        )
        opts.update(kwargs)
        super().__init__(parent, icon_name=icon,
                         **_with_icon(opts, icon, 16, palette.error))


class IconButton(_IconTextButton):
    def __init__(self, parent, palette: Palette, icon=None, size=34, icon_size=17,
                 color=None, **kwargs):
        color = color or palette.text_secondary
        img = icons.icon(icon, icon_size, color) if icon else None
        opts = dict(
            width=size, height=size, corner_radius=RADIUS.sm, font=TYPE.button,
            fg_color="transparent", text_color=color, hover_color=palette.surface_hover,
            border_width=0, text="" if img else kwargs.pop("text", "•"), image=img,
        )
        opts.update(kwargs)
        super().__init__(parent, icon_name=icon, icon_size=icon_size, **opts)
