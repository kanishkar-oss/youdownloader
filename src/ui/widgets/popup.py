"""PopupMenu — a themed replacement for tk.Menu (which renders as a native
Windows-95-style menu that ignores the palette).

A borderless, rounded (Windows 11) floating panel of icon + label rows. It never
takes keyboard focus (taking focus made it close itself whenever focus briefly
moved). It closes on selection, Esc, a click anywhere else in the app, the
window moving, or switching to another app.
"""
import tkinter
from typing import Callable, List, Optional, Tuple

import customtkinter

from src.ui import icons
from src.ui.palettes import SPACE
from src.ui.tokens import RADIUS, SPACING, TYPE

# (label, callback, icon name, options) ; label None = separator.
MenuItem = Tuple[Optional[str], Optional[Callable], Optional[str], dict]


class PopupMenu:
    _open: Optional["PopupMenu"] = None

    def __init__(self, master, palette=SPACE, min_width: int = 190):
        self.master = master
        self.p = palette
        self.min_width = min_width
        self.items: List[MenuItem] = []
        self.win = None

    def add(self, label: str, command: Callable, icon: str = None, danger: bool = False,
            checked: bool = False, enabled: bool = True) -> "PopupMenu":
        self.items.append((label, command, icon, {"danger": danger, "checked": checked,
                                                  "enabled": enabled}))
        return self

    def separator(self) -> "PopupMenu":
        self.items.append((None, None, None, {}))
        return self

    def show_below(self, widget, align: str = "left") -> None:
        widget.update_idletasks()
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        self.show_at(x, y, align_right_edge=(x + widget.winfo_width()) if align == "right" else None)

    def show_at(self, x: int, y: int, align_right_edge: Optional[int] = None) -> None:
        if PopupMenu._open is not None:
            PopupMenu._open.close()
        p = self.p
        root = self.master.winfo_toplevel()
        _install_root_hooks(root)
        # A plain Toplevel: CTkToplevel re-styles itself ~200ms after creation
        # (title bar / icon), which isn't wanted on a borderless popup.
        win = tkinter.Toplevel(root, bg=p.surface_raised, highlightthickness=0, bd=0)
        win.withdraw()
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        self.win = win
        PopupMenu._open = self

        box = customtkinter.CTkFrame(win, fg_color=p.surface_raised, corner_radius=0,
                                     border_width=1, border_color=p.border_strong)
        box.pack(fill="both", expand=True)
        inner = customtkinter.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=SPACING.xs + 1, pady=SPACING.xs + 1)

        for label, command, icon_name, opt in self.items:
            if label is None:
                customtkinter.CTkFrame(inner, height=1, fg_color=p.border_subtle).pack(
                    fill="x", padx=SPACING.sm, pady=SPACING.xs)
                continue
            color = p.error if opt.get("danger") else (p.text_primary if opt.get("enabled", True) else p.text_disabled)
            name = "check" if opt.get("checked") else icon_name
            img = icons.icon(name, 15, p.accent if opt.get("checked") else (
                p.error if opt.get("danger") else p.text_secondary)) if name else None
            btn = customtkinter.CTkButton(
                inner, text=label, anchor="w", height=32, corner_radius=RADIUS.sm,
                font=TYPE.body, fg_color="transparent", hover_color=p.surface_hover,
                text_color=color, text_color_disabled=p.text_disabled,
                image=img if img else icons.icon("check", 15, p.surface_raised),
                compound="left", width=self.min_width,
                state="normal" if opt.get("enabled", True) else "disabled",
                command=lambda c=command: self._choose(c),
            )
            btn.pack(fill="x")

        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        if align_right_edge is not None:
            x = align_right_edge - w
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(0, min(x, sw - w - 4))
        if y + h > sh - 40:
            y = max(0, y - h - 40)
        win.geometry(f"+{x}+{y}")
        win.deiconify()
        win.lift()
        from src.utils import winsys
        winsys.style_window(win, rounded=True, border=p.border_strong)
        win.bind("<Escape>", lambda e: self.close())
        # Opened from a click: ignore that same click reaching the root hook.
        self._opened_at = win.tk.call("clock", "milliseconds")

    def _choose(self, command: Optional[Callable]) -> None:
        self.close()
        if command:
            self.master.after(10, command)

    def close(self) -> None:
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None
        if PopupMenu._open is self:
            PopupMenu._open = None


def _install_root_hooks(root) -> None:
    """Bind once per window: close the open popup on outside clicks, Esc, the
    window moving, or the app losing focus. (Bound once and never unbound:
    on Python 3.12 unbind(seq, funcid) would also drop CTk's own bindings.)"""
    if getattr(root, "_popup_hooks_installed", False):
        return
    root._popup_hooks_installed = True

    def current():
        return PopupMenu._open

    def on_click(event):
        menu = current()
        if menu and menu.win is not None:
            try:
                if root.tk.call("clock", "milliseconds") - menu._opened_at < 150:
                    return
            except Exception:
                pass
            menu.close()

    def on_configure(event):
        if event.widget is root and current():
            current().close()

    def on_focus_out(_event):
        def check():
            menu = current()
            if menu and root.focus_get() is None:
                menu.close()  # switched to another app
        root.after(60, check)

    root.bind("<Button-1>", on_click, add="+")
    from src.utils.winsys import context_menu_events
    for seq in context_menu_events():
        root.bind(seq, lambda e: None, add="+")
    root.bind("<Escape>", lambda e: current() and current().close(), add="+")
    root.bind("<Configure>", on_configure, add="+")
    root.bind("<FocusOut>", on_focus_out, add="+")
