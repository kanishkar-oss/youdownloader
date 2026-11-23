"""Color palette — one dark "space" theme.

Deep void background, near-black navy surfaces separated by hairlines rather
than shadows, cool desaturated text, and a single luminous violet accent (with a
cyan "starlight" secondary used only in the header). State colors are softened
so they read on dark without glowing.

Kept: the Palette dataclass, `get_palette`, `resolve_name` and
`legacy_theme_dict`, so older call sites and saved settings ("midnight",
"daylight", "graphite", "tech", ...) all resolve to SPACE.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    appearance_mode: str

    bg: str               # window / page (the void)
    surface: str          # cards
    surface_raised: str   # inputs, queue rows, menus
    surface_hover: str    # hover on raised elements
    border_subtle: str    # card hairlines
    border_strong: str    # popup outlines, scrollbars
    border_input: str     # input / control edges (3:1 against cards)
    border_input_hover: str

    text_primary: str
    text_secondary: str
    text_tertiary: str    # labels, placeholders, hints (4.5:1 on cards and inputs)
    text_disabled: str    # genuinely disabled text only

    accent: str
    accent_hover: str
    accent_pressed: str
    accent_subtle: str    # tinted fills (selected chips, banners)
    accent_fill: str      # filled controls with white text (4.5:1+)
    accent_fill_hover: str
    accent_fill_pressed: str
    on_accent: str        # text on accent fills

    starlight: str        # cyan secondary — header glow, focus details
    success: str
    warning: str
    error: str
    info: str

    error_subtle: str
    success_subtle: str
    warning_subtle: str


SPACE = Palette(
    name="space", appearance_mode="dark",
    bg="#05060B",
    surface="#0B0D15",
    surface_raised="#11141F",
    surface_hover="#181C2A",
    border_subtle="#171A26",
    border_strong="#262B3D",
    border_input="#565E80",
    border_input_hover="#6E7699",
    text_primary="#EDEFF7",
    text_secondary="#9197AD",
    text_tertiary="#7E849E",
    text_disabled="#555B72",
    accent="#7B6CF6",
    accent_hover="#8F82FF",
    accent_pressed="#6556DE",
    accent_subtle="#17152E",
    accent_fill="#6556DE",
    accent_fill_hover="#6C5DE6",
    accent_fill_pressed="#5A4BD0",
    on_accent="#FFFFFF",
    starlight="#6FE3EA",
    success="#45D6A0",
    warning="#F1B65E",
    error="#FF6B81",
    info="#72B7FF",
    error_subtle="#2A121A",
    success_subtle="#0F241D",
    warning_subtle="#2A2012",
)

PALETTES = {"space": SPACE}
DEFAULT_PALETTE = "space"

# Every old theme name maps to the one palette.
LEGACY_THEME_ALIASES = {n: "space" for n in ("tech", "dark", "light", "midnight", "daylight", "graphite", "space")}


def resolve_name(name: str) -> str:
    return LEGACY_THEME_ALIASES.get(name, DEFAULT_PALETTE)


def get_palette(name: str = DEFAULT_PALETTE) -> Palette:
    return PALETTES[resolve_name(name)]


def legacy_theme_dict(palette: Palette) -> dict:
    """The palette in the old colors-dict shape (for any legacy caller)."""
    return {
        "appearance_mode": palette.appearance_mode,
        "color_theme": "blue",
        "fg_color": palette.surface,
        "text_color": palette.text_primary,
        "accent_color": palette.accent,
        "hover_color": palette.accent_hover,
        "error_color": palette.error,
        "warning_color": palette.warning,
        "success_color": palette.success,
        "border_color": palette.border_subtle,
        "gradient_start": palette.accent,
        "gradient_end": palette.accent_hover,
    }
