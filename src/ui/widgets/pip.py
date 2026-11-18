"""StatusPip — a small round dot drawn on a canvas (crisp at any DPI, unlike a
"●" glyph whose size and baseline vary by font). Used for live URL validity and
the sign-in chip. `hide()` blanks it."""
import tkinter

import customtkinter


class StatusPip(tkinter.Canvas):
    def __init__(self, parent, color: str = "#888888", size: int = 8, bg: str = None):
        scale = customtkinter.ScalingTracker.get_widget_scaling(parent) if hasattr(
            customtkinter, "ScalingTracker") else 1.0
        self._d = max(6, int(size * scale))
        pad = int(4 * scale)
        if bg is None:
            bg = _resolve_bg(parent)
        super().__init__(parent, width=self._d + pad, height=self._d + pad, bg=bg,
                         highlightthickness=0, bd=0)
        o = pad // 2
        self._dot = self.create_oval(o, o, o + self._d, o + self._d, fill=color, outline="")
        self._color = color

    def set_color(self, color: str) -> None:
        self._color = color
        self.itemconfigure(self._dot, fill=color, state="normal")

    def hide(self) -> None:
        self.itemconfigure(self._dot, state="hidden")


def _resolve_bg(widget) -> str:
    """The effective background color behind `widget` (CTk 'transparent' walks up)."""
    w = widget
    while w is not None:
        try:
            color = w.cget("fg_color")
        except Exception:
            color = None
        if color and color != "transparent":
            if isinstance(color, (list, tuple)):
                color = color[1]
            return color
        w = getattr(w, "master", None)
    return "#000000"
