"""Tiny motion helper. The only animation primitive in the app besides the
progress bar — a linear RGB crossfade of a widget color attribute across a few
`after()` ticks. Callers gate it behind config["visual_effects_enabled"]."""


def _to_rgb(hex_color: str):
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def crossfade(widget, attr: str, from_hex: str, to_hex: str,
              duration_ms: int = 180, steps: int = 8, on_done=None) -> None:
    """
    Animate widget.configure(<attr>=color) from from_hex to to_hex.

    Stops early (and silently) if the widget is destroyed mid-animation.
    """
    a = _to_rgb(from_hex)
    b = _to_rgb(to_hex)
    interval = max(1, duration_ms // max(1, steps))

    def step(i: int) -> None:
        try:
            t = i / steps
            cur = tuple(round(a[j] + (b[j] - a[j]) * t) for j in range(3))
            widget.configure(**{attr: "#%02X%02X%02X" % cur})
        except Exception:
            return  # widget gone — abort quietly
        if i < steps:
            widget.after(interval, lambda: step(i + 1))
        elif on_done:
            on_done()

    step(1)
