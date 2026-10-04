"""Small stroke icons drawn with Pillow, so no icon font or emoji is needed.

Each icon is rendered on a 24-unit grid at a high resolution and handed to
CTkImage, which resamples it for the current widget scaling. When Pillow is
missing the helpers return None and buttons fall back to text only.
"""
from functools import lru_cache

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - Pillow ships with the test/runtime venvs
    Image = ImageDraw = None

import customtkinter as ctk

_GRID = 24
_RENDER = 96  # px for the 24-unit grid: 4x supersampling


def _hex_to_rgba(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def _sliders(draw, s, rgba):
    w = round(1.8 * s)
    for y, knob in ((6, 15), (12, 8), (18, 13)):
        draw.line((4 * s, y * s, 20 * s, y * s), fill=rgba, width=w)
        r = 2.4 * s
        draw.ellipse((knob * s - r, y * s - r, knob * s + r, y * s + r), fill=(255, 255, 255, 255),
                     outline=rgba, width=w)


def _record(draw, s, rgba):
    r = 5 * s
    draw.ellipse((12 * s - r, 12 * s - r, 12 * s + r, 12 * s + r), fill=rgba)


def _stop(draw, s, rgba):
    draw.rounded_rectangle((7 * s, 7 * s, 17 * s, 17 * s), radius=1.5 * s, fill=rgba)


def _play(draw, s, rgba):
    draw.polygon(((8 * s, 6 * s), (18.5 * s, 12 * s), (8 * s, 18 * s)), fill=rgba)


def _save(draw, s, rgba):
    # Arrow into a tray: "write to disk" without a floppy cliché.
    w = round(1.8 * s)
    draw.line((12 * s, 4 * s, 12 * s, 14 * s), fill=rgba, width=w)
    draw.line((8 * s, 10.5 * s, 12 * s, 14.5 * s, 16 * s, 10.5 * s), fill=rgba, width=w, joint="curve")
    draw.line((5 * s, 15 * s, 5 * s, 19 * s, 19 * s, 19 * s, 19 * s, 15 * s), fill=rgba, width=w, joint="curve")


def _chevron(draw, s, rgba):
    draw.line((7 * s, 10 * s, 12 * s, 15 * s, 17 * s, 10 * s), fill=rgba, width=round(2 * s), joint="curve")


_SHAPES = {"chevron": _chevron, "sliders": _sliders, "record": _record, "stop": _stop, "play": _play, "save": _save}


@lru_cache(maxsize=None)
def _render(name, color):
    if Image is None:
        return None
    image = Image.new("RGBA", (_RENDER, _RENDER), (0, 0, 0, 0))
    _SHAPES[name](ImageDraw.Draw(image), _RENDER / _GRID, _hex_to_rgba(color))
    return image


def icon(name, color, size=16):
    """CTkImage for one icon, or None when Pillow is unavailable."""
    image = _render(name, color)
    if image is None:
        return None
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))
