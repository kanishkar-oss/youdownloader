"""Crisp monochrome icons rendered from an icon font with PIL at 2x and wrapped
in a CTkImage, so they stay sharp at any DPI and can be tinted to any palette
color.

- Windows: Segoe Fluent Icons (Windows 11), falling back to Segoe MDL2 Assets
  (Windows 10) — the system icon fonts.
- macOS (and anything else): Material Icons, bundled in assets/fonts
  (Apache 2.0), since Segoe isn't available and SF Symbols can't be used as a
  font file.

Returns None when no icon font exists (callers then show text only).
"""
import os
import sys
from functools import lru_cache
from typing import Optional

import customtkinter
from PIL import Image, ImageDraw, ImageFont

from src.utils import paths

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
# (font file, Tk family name or None if Tk can't see it, glyph table)
_SEGOE_FILES = [(os.path.join(_FONT_DIR, "SegoeIcons.ttf"), "Segoe Fluent Icons"),
                (os.path.join(_FONT_DIR, "segmdl2.ttf"), "Segoe MDL2 Assets")]
_MATERIAL_FILE = paths.resource("assets", "fonts", "MaterialIcons-Regular.ttf")

SEGOE_GLYPHS = {
    "settings": "\uE713",
    "more": "\uE712",
    "download": "\uE896",
    "add": "\uE710",
    "paste": "\uE77F",
    "link": "\uE71B",
    "folder": "\uE838",
    "play": "\uE768",
    "pause": "\uE769",
    "rename": "\uE8AC",
    "close": "\uE711",
    "check": "\uE73E",
    "error": "\uE783",
    "warning": "\uE7BA",
    "info": "\uE946",
    "clock": "\uE823",
    "stop": "\uE71A",
    "refresh": "\uE72C",
    "delete": "\uE74D",
    "clear": "\uE894",
    "list": "\uEA37",
    "search": "\uE721",
    "chevron_down": "\uE70D",
    "video": "\uE714",
    "audio": "\uE8D6",
    "cut": "\uE8C6",
    "lock": "\uE72E",
    "unlock": "\uE785",
    "sparkle": "\uE945",
    "open": "\uE8A7",
    "copy": "\uE8C8",
    "update": "\uE895",
}

# Same names -> Material Icons codepoints (from the font's .codepoints file).
MATERIAL_GLYPHS = {
    "settings": "\uE8B8",
    "more": "\uE5D3",
    "download": "\uF090",
    "add": "\uE145",
    "paste": "\uE14F",
    "link": "\uE157",
    "folder": "\uE2C7",
    "play": "\uE037",
    "pause": "\uE034",
    "rename": "\uE9A2",
    "close": "\uE5CD",
    "check": "\uE5CA",
    "error": "\uE000",
    "warning": "\uE002",
    "info": "\uE88E",
    "clock": "\uE8B5",
    "stop": "\uE047",
    "refresh": "\uE5D5",
    "delete": "\uE872",
    "clear": "\uE0B8",
    "list": "\uE896",
    "search": "\uE8B6",
    "chevron_down": "\uE5CF",
    "video": "\uE04B",
    "audio": "\uE405",
    "cut": "\uE14E",
    "lock": "\uE897",
    "unlock": "\uE898",
    "sparkle": "\uE65F",
    "open": "\uE89E",
    "copy": "\uE14D",
    "update": "\uE627",
}


@lru_cache(maxsize=1)
def _font() -> Optional[tuple]:
    """(font file, Tk family or None, glyph table) for this platform."""
    if sys.platform == "win32":
        for path, family in _SEGOE_FILES:
            if os.path.isfile(path):
                return path, family, SEGOE_GLYPHS
    if os.path.isfile(_MATERIAL_FILE):
        return _MATERIAL_FILE, None, MATERIAL_GLYPHS
    return None


def _font_path() -> Optional[str]:
    f = _font()
    return f[0] if f else None


def glyph(name: str) -> Optional[str]:
    f = _font()
    return f[2].get(name) if f else None


def tk_family() -> Optional[str]:
    """Tk font family for drawing glyphs as text (Windows only), else None."""
    f = _font()
    return f[1] if f else None


def available() -> bool:
    return _font_path() is not None


# Back-compat: some callers read icons.GLYPHS[name].
class _Glyphs(dict):
    def __getitem__(self, name):
        return glyph(name) or ""

    def __contains__(self, name):
        return glyph(name) is not None


GLYPHS = _Glyphs()


@lru_cache(maxsize=256)
def _render(glyph: str, px: int, color: str) -> Image.Image:
    scale = 2  # supersample for crisp edges
    size = px * scale
    font = ImageFont.truetype(_font_path(), size)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), glyph, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]), glyph, font=font, fill=color)
    return img


@lru_cache(maxsize=256)
def icon(name: str, size: int = 16, color: str = "#FFFFFF") -> Optional[customtkinter.CTkImage]:
    """A CTkImage for `name` at `size` logical px, tinted `color` (or None)."""
    ch = glyph(name)
    if not ch:
        return None
    img = _render(ch, size, color)
    return customtkinter.CTkImage(light_image=img, dark_image=img, size=(size, size))


def pil_icon(name: str, px: int, color: str) -> Optional[Image.Image]:
    """The icon as a PIL image of exactly `px` device pixels (canvas drawing)."""
    ch = glyph(name)
    if not ch:
        return None
    return _render(ch, px, color).resize((px, px), Image.Resampling.LANCZOS)


@lru_cache(maxsize=64)
def badge(name: str, size: int, color: str, fill: str) -> Optional[customtkinter.CTkImage]:
    """Icon centered in a tinted circle (dialog headers, empty states)."""
    ch = glyph(name)
    if not ch:
        return None
    scale = 2
    d = size * scale
    img = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((0, 0, d - 1, d - 1), fill=fill)
    g = _render(ch, int(size * 0.46), color)
    g = g.resize((int(d * 0.46),) * 2, Image.Resampling.LANCZOS)
    img.alpha_composite(g, ((d - g.width) // 2, (d - g.height) // 2))
    return customtkinter.CTkImage(light_image=img, dark_image=img, size=(size, size))


def rounded(img: Image.Image, size: tuple, radius: int) -> customtkinter.CTkImage:
    """Cover-crop `img` to `size` with rounded corners (thumbnails)."""
    scale = 2
    W, H = size[0] * scale, size[1] * scale
    src = img.convert("RGBA")
    ratio = max(W / src.width, H / src.height)
    src = src.resize((max(1, int(src.width * ratio)), max(1, int(src.height * ratio))), Image.Resampling.LANCZOS)
    left, top = (src.width - W) // 2, (src.height - H) // 2
    src = src.crop((left, top, left + W, top + H))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), radius=radius * scale, fill=255)
    src.putalpha(mask)
    return customtkinter.CTkImage(light_image=src, dark_image=src, size=size)
