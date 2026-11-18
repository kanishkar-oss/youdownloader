"""Inputs.

FieldEntry   — themed CTkEntry with an accent focus ring and a themed
               right-click Cut / Copy / Paste menu. Drop-in CTkEntry API.
SelectButton — a dropdown (value + chevron) that opens a PopupMenu. Mimics the
               bits of CTkOptionMenu the app uses: get / set / configure(values=).
"""
from typing import Callable, List, Optional

import customtkinter

from src.ui import icons
from src.ui.tokens import RADIUS, BORDER, HEIGHT, TYPE, SPACING
from src.ui.palettes import Palette
from src.ui.widgets.popup import PopupMenu


class FieldEntry(customtkinter.CTkEntry):
    def __init__(self, parent, palette: Palette, **kwargs):
        opts = dict(
            height=HEIGHT.entry, corner_radius=RADIUS.md, border_width=BORDER.hairline,
            border_color=palette.border_strong, fg_color=palette.surface_raised,
            text_color=palette.text_primary, placeholder_text_color=palette.text_disabled,
            font=TYPE.body,
        )
        opts.update(kwargs)
        super().__init__(parent, **opts)
        self._palette = palette
        self._idle_border = opts["border_color"]
        self._focus_border = palette.accent
        self.bind("<FocusIn>", lambda e: self.configure(border_color=self._focus_border))
        self.bind("<FocusOut>", lambda e: self.configure(border_color=self._idle_border))
        # Tk entries have no right-click menu; add a themed one.
        from src.utils.winsys import context_menu_events
        for seq in context_menu_events():
            self._entry.bind(seq, self._show_context_menu)
        self._entry.configure(insertwidth=2, insertbackground=palette.accent,
                              selectbackground=palette.accent_subtle,
                              selectforeground=palette.text_primary)

    def _show_context_menu(self, event) -> None:
        entry = self._entry
        entry.focus_set()
        menu = PopupMenu(self, self._palette, min_width=150)
        menu.add("Cut", lambda: entry.event_generate("<<Cut>>"), "cut")
        menu.add("Copy", lambda: entry.event_generate("<<Copy>>"), "open")
        menu.add("Paste", lambda: (entry.event_generate("<<Paste>>"),
                                   entry.event_generate("<KeyRelease>")), "paste")
        menu.separator()
        menu.add("Select all", lambda: entry.select_range(0, "end"), "list")
        menu.show_at(event.x_root, event.y_root)


class SelectButton(customtkinter.CTkButton):
    """Dropdown selector styled like an input, with a themed popup list."""

    def __init__(self, parent, palette: Palette, values: List[str],
                 command: Optional[Callable[[str], None]] = None, **kwargs):
        self._p = palette
        self._values = list(values)
        self._value = self._values[0] if self._values else ""
        self._on_select = command  # not _command: CTkButton uses that name
        opts = dict(
            text=self._value, anchor="w", height=HEIGHT.entry, corner_radius=RADIUS.md,
            font=TYPE.body, fg_color=palette.surface_raised, hover_color=palette.surface_raised,
            border_width=BORDER.hairline, border_color=palette.border_strong,
            text_color=palette.text_primary, command=self._open,
        )
        opts.update(kwargs)
        super().__init__(parent, **opts)
        # Chevron pinned to the right edge (a compound image would hug the text).
        chevron = icons.icon("chevron_down", 12, palette.text_secondary)
        self._chevron = customtkinter.CTkLabel(self, text="" if chevron else "v", image=chevron,
                                               width=16, fg_color=palette.surface_raised)
        self._chevron.place(relx=1.0, rely=0.5, x=-14, anchor="e")
        self._chevron.bind("<Button-1>", lambda e: self._open())
        base = super(SelectButton, self)
        for w in (self, self._chevron):
            w.bind("<Enter>", lambda e: base.configure(border_color=palette.text_disabled), add="+")
            w.bind("<Leave>", lambda e: base.configure(border_color=palette.border_strong), add="+")

    def _open(self) -> None:
        menu = PopupMenu(self, self._p, min_width=max(160, self.winfo_width() - 12))
        for v in self._values:
            menu.add(v, lambda v=v: self._pick(v), checked=(v == self._value))
        menu.show_below(self)

    def _pick(self, value: str) -> None:
        self.set(value)
        if self._on_select:
            self._on_select(value)

    # CTkOptionMenu-compatible API
    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value
        super().configure(text=f"{value}")

    def configure(self, require_redraw=False, **kwargs):
        if "values" in kwargs:
            self._values = list(kwargs.pop("values"))
        if kwargs:
            super().configure(require_redraw, **kwargs)

    def cget(self, attribute_name: str):
        if attribute_name == "values":
            return list(self._values)
        return super().cget(attribute_name)
