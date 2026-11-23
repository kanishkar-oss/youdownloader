"""Design tokens — the single source of truth for spacing, radius, motion,
typography and sizing.

Typography is resolved at runtime by `init_fonts(root)` (it needs a Tk root to
see which families are installed): Inter with real weights when available,
then Segoe UI Variable, then Segoe UI. Widgets read `TYPE.<role>` when they're
built, so call `init_fonts` before creating any widgets.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class _Spacing:
    """4px-based spacing scale."""
    xxs: int = 2
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32
    xxxl: int = 48


@dataclass(frozen=True)
class _Radius:
    none: int = 0
    sm: int = 8      # chips, small buttons
    md: int = 10     # inputs, buttons, rows
    lg: int = 16     # cards
    pill: int = 999


@dataclass(frozen=True)
class _Border:
    hairline: int = 1
    medium: int = 2


@dataclass(frozen=True)
class _Motion:
    """Animation timings (ms)."""
    fast: int = 120
    base: int = 180
    slow: int = 280
    fps: int = 60
    interp: float = 0.18      # progress bar easing
    twinkle_ms: int = 140     # header starfield
    orbit_ms: int = 40        # header orbiting satellite


@dataclass(frozen=True)
class _Height:
    entry: int = 40
    url_bar: int = 52
    button_sm: int = 32
    button_md: int = 40
    button_lg: int = 48
    progress: int = 6
    queue_row: int = 60
    header: int = 96


# Content never stretches wider than this, so wide/maximized windows keep a
# calm, centered column instead of edge-to-edge cards.
CONTENT_MAX_WIDTH = 880
CONTENT_GUTTER = 28


class _Type:
    """Typographic scale as CTk font tuples. Filled in by init_fonts()."""

    def __init__(self):
        self._apply("Segoe UI", "Segoe UI", "Segoe UI", "Consolas", semibold_is_bold=True)

    def _apply(self, regular, medium, semibold, mono, semibold_is_bold=False):
        b = "bold" if semibold_is_bold else "normal"
        self.family = regular
        self.family_semibold = semibold
        self.semibold_weight = b
        self.display = (semibold, 26, b)       # header wordmark
        self.headline = (semibold, 18, b)      # dialog titles
        self.title = (semibold, 15, b)         # card titles
        self.body = (regular, 13, "normal")
        self.body_med = (medium, 13, "normal" if not semibold_is_bold else "bold")
        self.body_lg = (regular, 14, "normal")  # URL field
        self.button = (semibold, 13, b)
        self.button_lg = (semibold, 14, b)
        self.label = (medium, 12, "normal" if not semibold_is_bold else "bold")
        self.caption = (regular, 12, "normal")
        self.caption_med = (medium, 12, "normal" if not semibold_is_bold else "bold")
        self.overline = (semibold, 10, b)      # tracked uppercase section labels
        self.mono = (mono, 12, "normal")       # speed / ETA / sizes

    def init(self, root) -> str:
        import sys
        import tkinter.font as tkfont
        families = set(tkfont.families(root))
        mono = next((m for m in ("Cascadia Mono", "Cascadia Code", "Consolas", "SF Mono", "Menlo", "Monaco")
                     if m in families), "Courier")
        if {"Inter", "Inter Medium", "Inter SemiBold"} <= families:
            self._apply("Inter", "Inter Medium", "Inter SemiBold", mono)
            return "Inter"
        if {"Segoe UI Variable Text", "Segoe UI Variable Text Semibold"} <= families:
            self._apply("Segoe UI Variable Text", "Segoe UI Variable Text",
                        "Segoe UI Variable Text Semibold", mono)
            return "Segoe UI Variable"
        if sys.platform == "darwin":
            # macOS: Tk only exposes regular/bold weights. Inter (one family
            # with styles on macOS) if installed, else SF Pro, else Helvetica Neue.
            fam = next((f for f in ("Inter", "SF Pro Text", "SF Pro", "Helvetica Neue") if f in families),
                       "Helvetica")
            self._apply(fam, fam, fam, mono, semibold_is_bold=True)
            return fam
        self._apply("Segoe UI", "Segoe UI", "Segoe UI", mono, semibold_is_bold=True)
        return "Segoe UI"


def tracked(text: str) -> str:
    """Uppercase with hair-space letter-spacing (Tk has no tracking property)."""
    return " ".join(text.upper())


SPACING = _Spacing()
RADIUS = _Radius()
BORDER = _Border()
MOTION = _Motion()
HEIGHT = _Height()
TYPE = _Type()


def init_fonts(root) -> str:
    """Pick the best installed font family. Returns the family used."""
    return TYPE.init(root)


# Back-compat names some modules still import.
FONT_PRIMARY = "Inter"
FONT_MONO = "Cascadia Mono"
