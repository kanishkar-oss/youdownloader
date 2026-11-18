"""InlineBanner — a quiet notice row: tinted surface, tone-colored icon,
headline + one-line detail, optional action, dismiss (×)."""
from typing import Callable, Optional

import customtkinter

from src.ui import icons
from src.ui.palettes import Palette
from src.ui.tokens import BORDER, RADIUS, SPACING, TYPE

_TONE_ICON = {"warning": "warning", "error": "error", "info": "info", "success": "check"}


class InlineBanner(customtkinter.CTkFrame):
    def __init__(
        self,
        parent,
        palette: Palette,
        headline: str,
        detail: str = "",
        tone: str = "warning",
        icon: str = None,
        action_text: Optional[str] = None,
        on_action: Optional[Callable] = None,
        on_dismiss: Optional[Callable] = None,
    ):
        tone_color = getattr(palette, tone, palette.warning)
        fill = getattr(palette, f"{tone}_subtle", palette.accent_subtle)
        super().__init__(parent, corner_radius=RADIUS.md, fg_color=fill,
                         border_width=BORDER.hairline, border_color=palette.border_subtle)
        self.grid_columnconfigure(1, weight=1)

        img = icons.icon(_TONE_ICON.get(tone, "info"), 16, tone_color)
        customtkinter.CTkLabel(self, text="" if img else "!", image=img, width=20,
                               text_color=tone_color).grid(
            row=0, column=0, rowspan=2, padx=(SPACING.md, SPACING.sm), pady=SPACING.sm)

        customtkinter.CTkLabel(self, text=headline, font=TYPE.body_med, text_color=palette.text_primary,
                               anchor="w").grid(row=0, column=1, sticky="w", pady=(SPACING.sm, 0))
        if detail:
            customtkinter.CTkLabel(self, text=detail, font=TYPE.caption, text_color=palette.text_secondary,
                                   anchor="w", justify="left").grid(
                row=1, column=1, sticky="w", pady=(0, SPACING.sm))

        if action_text and on_action is not None:
            customtkinter.CTkButton(
                self, text=action_text, command=on_action, width=76, height=30,
                corner_radius=RADIUS.sm, font=TYPE.label, fg_color="transparent",
                border_width=BORDER.hairline, border_color=tone_color,
                text_color=tone_color, hover_color=palette.surface_hover,
            ).grid(row=0, column=2, rowspan=2, padx=SPACING.xs, pady=SPACING.sm)

        close = icons.icon("close", 12, palette.text_secondary)
        customtkinter.CTkButton(
            self, text="" if close else "✕", image=close, command=self._dismiss,
            width=28, height=28, corner_radius=RADIUS.sm, fg_color="transparent",
            text_color=palette.text_secondary, hover_color=palette.surface_hover,
        ).grid(row=0, column=3, rowspan=2, padx=(0, SPACING.sm), pady=SPACING.sm)
        self._on_dismiss = on_dismiss

    def _dismiss(self) -> None:
        if self._on_dismiss is not None:
            self._on_dismiss()
        self.destroy()
