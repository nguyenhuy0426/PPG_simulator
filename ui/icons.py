"""Small stroke icons drawn with Pillow, so no icon font or emoji is needed.

One consistent set: 24-unit grid, 1.8-unit strokes with round caps and
joins, a single colour per icon. Each icon is rendered at 4x and handed to
CTkImage, which resamples it for the current widget scaling. A colour may be
a (light, dark) pair; CTkImage then swaps images with the appearance mode.
When Pillow is missing the helpers return None and callers fall back to text.
"""
from functools import lru_cache
import math

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - Pillow ships with the runtime venvs
    Image = ImageDraw = None

import customtkinter as ctk

_GRID = 24
_RENDER = 96  # px for the 24-unit grid: 4x supersampling
_STROKE = 1.8


def _hex_to_rgba(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def _stroke(draw, s, rgba, points, closed=False):
    """Polyline with round caps and joins (Pillow lines have square ends)."""
    pts = [(x * s, y * s) for x, y in points]
    if closed:
        pts.append(pts[0])
    width = round(_STROKE * s)
    draw.line(pts, fill=rgba, width=width, joint="curve")
    r = width / 2
    for x, y in pts:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=rgba)


def _circle(draw, s, rgba, cx, cy, radius, fill=False):
    box = ((cx - radius) * s, (cy - radius) * s, (cx + radius) * s, (cy + radius) * s)
    if fill:
        draw.ellipse(box, fill=rgba)
    else:
        draw.ellipse(box, outline=rgba, width=round(_STROKE * s))


def _menu(draw, s, rgba):
    for y in (7, 12, 17):
        _stroke(draw, s, rgba, ((4, y), (20, y)))


def _monitor(draw, s, rgba):
    # Live trace: the vital-signs "activity" line.
    _stroke(draw, s, rgba, ((3, 12), (7, 12), (9.5, 6), (13.5, 18), (16, 12), (21, 12)))


def _calibration(draw, s, rgba):
    # Target with cross-hair ticks: setting a known reference.
    _circle(draw, s, rgba, 12, 12, 6.5)
    _circle(draw, s, rgba, 12, 12, 1.6, fill=True)
    for a, b in (((12, 2.5), (12, 5)), ((12, 19), (12, 21.5)), ((2.5, 12), (5, 12)), ((19, 12), (21.5, 12))):
        _stroke(draw, s, rgba, (a, b))


def _recordings(draw, s, rgba):
    # Stacked list of saved sessions.
    for y in (7, 12, 17):
        _circle(draw, s, rgba, 5, y, 1.3, fill=True)
        _stroke(draw, s, rgba, ((9, y), (20, y)))


def _morphology(draw, s, rgba):
    # One PPG pulse: systolic peak, dicrotic notch, diastolic wave.
    points = []
    for i in range(37):
        x = 3 + 18 * i / 36
        y = 18.5 - 11.5 * math.exp(-((x - 8.5) / 2.3) ** 2) - 4.2 * math.exp(-((x - 14.2) / 2.4) ** 2)
        points.append((x, y))
    _stroke(draw, s, rgba, points)


def _sliders(draw, s, rgba):
    for y, knob in ((6, 15), (12, 8), (18, 13)):
        _stroke(draw, s, rgba, ((4, y), (knob - 2.6, y)))
        _stroke(draw, s, rgba, ((knob + 2.6, y), (20, y)))
        _circle(draw, s, rgba, knob, y, 2.2)


def _sun(draw, s, rgba):
    _circle(draw, s, rgba, 12, 12, 4)
    for k in range(8):
        a = k * math.pi / 4
        _stroke(draw, s, rgba, ((12 + 7 * math.cos(a), 12 + 7 * math.sin(a)),
                                (12 + 9 * math.cos(a), 12 + 9 * math.sin(a))))


def _moon(draw, s, rgba):
    _circle(draw, s, rgba, 11.5, 12.5, 7.5, fill=True)
    _circle(draw, s, (0, 0, 0, 0), 15.5, 9, 6.5, fill=True)   # cut the crescent


def _chevron(draw, s, rgba):
    _stroke(draw, s, rgba, ((7, 10), (12, 15), (17, 10)))


def _collapse(draw, s, rgba):
    _stroke(draw, s, rgba, ((14, 6), (8, 12), (14, 18)))


def _record(draw, s, rgba):
    _circle(draw, s, rgba, 12, 12, 5, fill=True)


def _stop(draw, s, rgba):
    draw.rounded_rectangle((7 * s, 7 * s, 17 * s, 17 * s), radius=1.5 * s, fill=rgba)


def _play(draw, s, rgba):
    draw.polygon(((8 * s, 6 * s), (18.5 * s, 12 * s), (8 * s, 18 * s)), fill=rgba)


def _save(draw, s, rgba):
    # Arrow into a tray: "write to disk" without a floppy cliché.
    _stroke(draw, s, rgba, ((12, 4), (12, 14)))
    _stroke(draw, s, rgba, ((8, 10.5), (12, 14.5), (16, 10.5)))
    _stroke(draw, s, rgba, ((5, 15), (5, 19), (19, 19), (19, 15)))


_SHAPES = {
    "menu": _menu, "monitor": _monitor, "calibration": _calibration, "recordings": _recordings,
    "morphology": _morphology, "sliders": _sliders, "sun": _sun, "moon": _moon, "chevron": _chevron,
    "collapse": _collapse, "record": _record, "stop": _stop, "play": _play, "save": _save,
}
NAMES = tuple(_SHAPES)


@lru_cache(maxsize=None)
def _render(name, color):
    if Image is None:
        return None
    image = Image.new("RGBA", (_RENDER, _RENDER), (0, 0, 0, 0))
    _SHAPES[name](ImageDraw.Draw(image), _RENDER / _GRID, _hex_to_rgba(color))
    return image


def icon(name, color, size=16):
    """CTkImage for one icon, or None when Pillow is unavailable."""
    light, dark = (color[0], color[1]) if isinstance(color, (tuple, list)) else (color, color)
    light_image, dark_image = _render(name, light), _render(name, dark)
    if light_image is None:
        return None
    return ctk.CTkImage(light_image=light_image, dark_image=dark_image, size=(size, size))
