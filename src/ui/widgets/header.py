"""SpaceHeader — the app's hero band.

A full-width canvas: a procedurally generated deep-space backdrop (faint violet
and cyan nebula, a dusting of stars) rendered with PIL, with the wordmark,
tagline, a sign-in status chip and the Settings button drawn on top. Two tiny
animations, both off when visual effects are disabled: a handful of stars
twinkle, and a satellite drifts along a hairline orbit (faster while a
download is running).

Everything is drawn on one canvas, so there are no opaque widget boxes over
the starfield.
"""
import math
import random
import tkinter
from typing import Callable, Optional

import customtkinter
from PIL import Image, ImageDraw, ImageFilter, ImageTk

from src.ui import icons
from src.ui.palettes import Palette
from src.ui.tokens import HEIGHT, MOTION, TYPE


def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = _hex(a), _hex(b)
    return "#%02X%02X%02X" % tuple(round(ra[i] + (rb[i] - ra[i]) * t) for i in range(3))


class SpaceHeader(tkinter.Canvas):
    def __init__(self, parent, palette: Palette, on_settings: Callable[[], None],
                 on_chip: Optional[Callable[[], None]] = None,
                 effects_enabled: Callable[[], bool] = lambda: True,
                 content_width: Callable[[], int] = lambda: 880):
        self.p = palette
        self.scale = customtkinter.ScalingTracker.get_widget_scaling(parent)
        self.h = int(HEIGHT.header * self.scale)
        super().__init__(parent, height=self.h, bg=palette.bg, highlightthickness=0, bd=0)
        self._on_settings = on_settings
        self._on_chip = on_chip
        self._effects = effects_enabled
        self._content_width = content_width
        self._bg_photo = None
        self._width = 0
        self._resize_job = None
        self._twinkle_job = None
        self._orbit_job = None
        self._stars = []
        self._orbit_t = random.random() * math.tau
        self.busy = False
        self._chip_text = ""
        self._chip_color = palette.text_secondary
        self.bind("<Configure>", self._on_configure)
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event) -> None:
        if event.widget is not self:
            return
        for job in (self._twinkle_job, self._orbit_job, self._resize_job):
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
        self._twinkle_job = self._orbit_job = self._resize_job = None

    # ----- public ---------------------------------------------------------

    def set_chip(self, text: str, color: str) -> None:
        self._chip_text, self._chip_color = text, color
        if self._width:
            self._draw_overlay()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy

    # ----- layout ---------------------------------------------------------

    def _on_configure(self, event) -> None:
        if event.width == self._width:
            return
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(60, lambda: self._redraw(event.width))

    def _px(self, v: float) -> int:
        return int(v * self.scale)

    def _font(self, spec, size_override=None):
        family, size, weight = spec
        return (family, -self._px(size_override or size), weight)

    def _column(self):
        """Left/right x of the centered content column, so text aligns with cards."""
        col = min(self._px(self._content_width()), self._width - self._px(56))
        left = (self._width - col) // 2
        return left, left + col

    def _redraw(self, width: int) -> None:
        self._width = width
        self._render_backdrop()
        self._draw_overlay()
        self._start_animations()

    def _render_backdrop(self) -> None:
        W, H = max(1, self._width), self.h
        rnd = random.Random(7)
        bg = _hex(self.p.bg)
        img = Image.new("RGB", (W, H), bg)

        # Nebula: a few large soft blobs, mostly toward the right.
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        g = ImageDraw.Draw(glow)
        for cx, cy, rx, ry, color, alpha in (
            (0.78, 0.10, 0.36, 1.05, _hex(self.p.accent), 70),
            (0.92, 0.55, 0.22, 0.75, _hex(self.p.starlight), 34),
            (0.55, -0.2, 0.30, 0.8, _hex("#3B2F8F"), 46),
        ):
            x0, x1 = (cx - rx) * W, (cx + rx) * W
            y0, y1 = (cy - ry) * H, (cy + ry) * H
            g.ellipse((x0, y0, x1, y1), fill=color + (alpha,))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=max(24, H // 2)))
        img.paste(glow, (0, 0), glow)

        # Static star dust (density scales with area), kept off the wordmark.
        d = ImageDraw.Draw(img)
        left, _right = self._column()
        quiet = (left - self._px(16), H * 0.18, left + self._px(380), H * 0.72)

        def in_quiet(x, y):
            return quiet[0] <= x <= quiet[2] and quiet[1] <= y <= quiet[3]

        for _ in range(int(W * H / 650)):
            x, y = rnd.randrange(W), rnd.randrange(H)
            if in_quiet(x, y):
                continue
            b = rnd.choice((55, 70, 85, 100, 120, 150))
            tint = rnd.random()
            col = (b, b, min(255, b + 18)) if tint < 0.8 else (b + 10, b, min(255, b + 40))
            d.point((x, y), fill=col)
        for _ in range(int(W / 70)):  # a few brighter stars
            x, y = rnd.randrange(W), rnd.randrange(H)
            if in_quiet(x, y):
                continue
            d.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(200, 205, 230))

        # Fade into the page at the bottom so the header has no hard edge.
        fade = Image.new("L", (1, H))
        for yy in range(H):
            t = max(0.0, (yy - H * 0.55) / (H * 0.45))
            fade.putpixel((0, yy), int(255 * min(1.0, t) ** 1.6))
        fade = fade.resize((W, H))
        img = Image.composite(Image.new("RGB", (W, H), bg), img, fade)

        self._bg_photo = ImageTk.PhotoImage(img)
        self.delete("all")
        self.create_image(0, 0, image=self._bg_photo, anchor="nw", tags=("bg",))

        # Twinkling stars are canvas items so they can animate cheaply.
        self._stars = []
        for _ in range(max(8, W // 90)):
            x, y = rnd.randrange(W), rnd.randrange(int(H * 0.75))
            if in_quiet(x, y):
                continue
            r = rnd.choice((1, 1, 1.5))
            item = self.create_oval(x - r, y - r, x + r, y + r, fill="#8C92B0", outline="")
            self._stars.append([item, rnd.random() * math.tau, rnd.uniform(0.04, 0.12)])

    def _draw_overlay(self) -> None:
        self.delete("overlay")
        p = self.p
        left, right = self._column()
        H = self.h

        # Orbit: a hairline ellipse sweeping behind the right side.
        ox, oy = right - self._px(120), H * 0.52
        self._orbit_geom = (ox, oy, self._px(260), self._px(46))
        rx, ry = self._orbit_geom[2], self._orbit_geom[3]
        self.create_oval(ox - rx, oy - ry, ox + rx, oy + ry, outline=_mix(p.bg, p.accent, 0.28),
                         width=1, tags=("overlay", "orbit"))
        self._satellite = self.create_oval(0, 0, 0, 0, fill=p.starlight, outline="",
                                           tags=("overlay", "sat"))
        self._sat_glow = self.create_oval(0, 0, 0, 0, outline=_mix(p.bg, p.starlight, 0.35),
                                          width=1, tags=("overlay", "sat"))
        self._place_satellite()

        # Wordmark + tagline, aligned with the content column.
        ty = H * 0.42
        self.create_text(left, ty, text="YouDownloader", anchor="w", fill=p.text_primary,
                         font=self._font(TYPE.display), tags=("overlay",))
        self.create_text(left + self._px(1), ty + self._px(30), anchor="w", fill=p.text_secondary,
                         text="Video and audio from YouTube  ·  MP4  ·  MOV  ·  MP3  ·  M4A  ·  WAV",
                         font=self._font(TYPE.caption), tags=("overlay",))

        # Settings button (icon font glyph) at the right edge of the column.
        gx, gy = right - self._px(14), ty
        hover_bg = self.create_oval(gx - self._px(17), gy - self._px(17), gx + self._px(17),
                                    gy + self._px(17), fill="", outline="", tags=("overlay", "gear"))
        family = icons.tk_family()
        if family:  # Windows: draw the Segoe glyph as canvas text
            gear = self.create_text(gx, gy, text=icons.glyph("settings"), fill=p.text_secondary,
                                    font=(family, -self._px(17)), tags=("overlay", "gear"))
            hover = (gear, p.text_primary, p.text_secondary)
        elif icons.available():  # macOS: the bundled icon font, drawn as an image
            px = self._px(18)
            self._gear_imgs = (ImageTk.PhotoImage(icons.pil_icon("settings", px, p.text_primary)),
                               ImageTk.PhotoImage(icons.pil_icon("settings", px, p.text_secondary)))
            gear = self.create_image(gx, gy, image=self._gear_imgs[1], tags=("overlay", "gear"))
            hover = (gear, self._gear_imgs[0], self._gear_imgs[1])
        else:
            gear = self.create_text(gx, gy, text="⚙", fill=p.text_secondary,
                                    font=(TYPE.family, -self._px(17)), tags=("overlay", "gear"))
            hover = (gear, p.text_primary, p.text_secondary)
        self._bind_button("gear", lambda: self._on_settings(), hover=hover,
                          bg=(hover_bg, _mix(p.bg, "#FFFFFF", 0.07)))

        # Sign-in chip, left of the gear.
        if self._chip_text:
            cx = gx - self._px(30)
            label = self.create_text(cx, gy, text=self._chip_text, anchor="e", fill=p.text_secondary,
                                     font=self._font(TYPE.caption_med), tags=("overlay", "chip"))
            x0, y0, x1, y1 = self.bbox(label)
            dot_x = x0 - self._px(10)
            pad = self._px(10)
            pill = self._round_rect(dot_x - pad, y0 - self._px(5), x1 + pad, y1 + self._px(5),
                                    r=(y1 - y0 + self._px(10)) // 2,
                                    fill=_mix(p.bg, "#FFFFFF", 0.05), outline=_mix(p.bg, "#FFFFFF", 0.10),
                                    tags=("overlay", "chip"))
            self.tag_lower(pill, label)
            r = self._px(3)
            self.create_oval(dot_x - r, gy - r, dot_x + r, gy + r, fill=self._chip_color, outline="",
                             tags=("overlay", "chip"))
            if self._on_chip:
                self._bind_button("chip", self._on_chip, hover=(label, p.text_primary, p.text_secondary))

    def _round_rect(self, x0, y0, x1, y1, r, **kw):
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
               x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return self.create_polygon(pts, smooth=True, **kw)

    def _bind_button(self, tag, command, hover=None, bg=None):
        def tint(item, value):
            # Text items recolor via fill; image items (macOS gear) swap images.
            key = "image" if self.type(item) == "image" else "fill"
            self.itemconfigure(item, **{key: value})

        def enter(_e):
            self.configure(cursor="hand2")
            if hover:
                tint(hover[0], hover[1])
            if bg:
                self.itemconfigure(bg[0], fill=bg[1])

        def leave(_e):
            self.configure(cursor="")
            if hover:
                tint(hover[0], hover[2])
            if bg:
                self.itemconfigure(bg[0], fill="")

        self.tag_bind(tag, "<Enter>", enter)
        self.tag_bind(tag, "<Leave>", leave)
        self.tag_bind(tag, "<Button-1>", lambda e: command())

    # ----- animation --------------------------------------------------------

    def _start_animations(self) -> None:
        for job in (self._twinkle_job, self._orbit_job):
            if job:
                self.after_cancel(job)
        self._twinkle_job = self.after(MOTION.twinkle_ms, self._twinkle)
        self._orbit_job = self.after(MOTION.orbit_ms, self._orbit)

    def _twinkle(self) -> None:
        if self._effects():
            for star in self._stars:
                star[1] += star[2]
                t = (math.sin(star[1]) + 1) / 2
                self.itemconfigure(star[0], fill=_mix("#2A2E44", "#E6E9FF", t ** 2))
        self._twinkle_job = self.after(MOTION.twinkle_ms, self._twinkle)

    def _orbit(self) -> None:
        if self._effects():
            self._orbit_t += 0.03 if self.busy else 0.006
            self._place_satellite()
        self._orbit_job = self.after(MOTION.orbit_ms, self._orbit)

    def _place_satellite(self) -> None:
        if not hasattr(self, "_orbit_geom"):
            return
        ox, oy, rx, ry = self._orbit_geom
        x = ox + rx * math.cos(self._orbit_t)
        y = oy + ry * math.sin(self._orbit_t)
        r = self._px(2.5)
        g = self._px(6)
        self.coords(self._satellite, x - r, y - r, x + r, y + r)
        self.coords(self._sat_glow, x - g, y - g, x + g, y + g)
        # Passing "behind" the planet-less orbit: dim on the far side.
        far = math.sin(self._orbit_t) < 0
        self.itemconfigure(self._satellite, fill=_mix(self.p.bg, self.p.starlight, 0.45 if far else 1.0))
        self.itemconfigure(self._sat_glow, state="hidden" if far else "normal")
