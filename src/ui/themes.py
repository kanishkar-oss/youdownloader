"""Theme facade over the modern palette system.

All color values live in src/ui/palettes.py. This class is a thin adapter:
- apply_theme() pushes appearance mode into customtkinter,
- get_theme_colors() returns a palette projected into the legacy colors-dict
  shape (so dialogs that read fg_color/accent_color/etc. keep working),
- get_palette()/colors()/resolve() are the preferred API for new code.

Legacy theme names ("tech"/"dark"/"light") are accepted everywhere and resolved
to a modern palette via palettes.LEGACY_THEME_ALIASES.
"""
import customtkinter
from typing import Dict, Any

from src.ui import palettes
from src.ui.palettes import Palette


class ThemeManager:
    """Adapter between the palette system and customtkinter / legacy callers."""

    @classmethod
    def apply_theme(cls, theme_name: str = palettes.DEFAULT_PALETTE) -> None:
        """Push the palette's appearance mode into customtkinter."""
        palette = palettes.get_palette(theme_name)
        customtkinter.set_appearance_mode(palette.appearance_mode)
        customtkinter.set_default_color_theme("blue")

    @classmethod
    def get_theme_colors(cls, theme_name: str = palettes.DEFAULT_PALETTE) -> Dict[str, Any]:
        """Return the active palette in the legacy colors-dict shape."""
        return palettes.legacy_theme_dict(palettes.get_palette(theme_name))

    @classmethod
    def get_palette(cls, theme_name: str = palettes.DEFAULT_PALETTE) -> Palette:
        """Return the Palette object for a (new or legacy) theme name."""
        return palettes.get_palette(theme_name)

    @classmethod
    def resolve(cls, theme_name: str) -> str:
        """Normalize a (possibly legacy) theme name to a modern palette name."""
        return palettes.resolve_name(theme_name)

    @classmethod
    def colors(cls, theme_name: str, role: str) -> str:
        """Look up a single palette role (e.g. "accent", "text_secondary")."""
        return getattr(palettes.get_palette(theme_name), role)
