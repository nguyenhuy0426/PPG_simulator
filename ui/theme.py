"""Instrument palette with light and dark modes; signal plots stay charcoal.

Surface and text tokens are (light, dark) pairs, which every CTk widget
accepts directly and repaints when the appearance mode changes. Plain Tk
canvases cannot take a pair, so they read `resolve()` while rendering and
register with `track_canvas()` to be redrawn on a mode switch.
"""
import tkinter.font as tkfont
import weakref

import customtkinter as ctk

LIGHT, DARK_MODE = "light", "dark"
THEMES = (LIGHT, DARK_MODE)

# Surfaces
BG = ("#EDF0F2", "#111619")       # window / page background
PANEL = ("#FFFFFF", "#1A2126")    # cards, rail, footer
SUBTLE = ("#F3F5F7", "#232C32")   # hover and selected fills
LINE = ("#D9DFE3", "#2A343B")     # 1 px card borders and dividers
BORDER = ("#C9D1D7", "#3A464E")   # outlined buttons and selectors
# Text
INK = ("#1E252B", "#E4EAEE")
MUTED = ("#66727C", "#9AA7B0")
FAINT = ("#98A3AB", "#6C7882")
# Filled neutral buttons
BUTTON = ("#1E252B", "#2E3940")
BUTTON_HOVER = ("#245D60", "#3A4850")
ON_BUTTON = ("#FFFFFF", "#E4EAEE")
# Signal surfaces: charcoal in both modes, recessed further in dark mode
DARK = ("#1B2328", "#0D1215")
GRID = "#2E3A41"
AXIS = "#8C9AA3"
PLOT_TEXT = "#D3DCE1"
IR = "#7FD8BE"
RED = "#F4958C"
# Actions and states
ACCENT = ("#245D60", "#3A8A8D")
HOVER = ("#34777A", "#4A9EA1")
ERROR = ("#B13737", "#C84848")
ERROR_HOVER = ("#952C2C", "#A93A3A")
OK = ("#2F9466", "#4CC08A")
OK_BG = ("#E3F3EB", "#173A2A")
ERROR_BG = ("#F8E1E1", "#48201F")
WARN = ("#C98A12", "#E0A63A")
WARN_BG = ("#FBEED3", "#3B3017")
WARN_INK = ("#8A5A00", "#F0C46A")
WHITE = "#FFFFFF"

# First installed family wins. Ubuntu ships "Ubuntu"; DejaVu is the portable
# fallback that the project used before and always covers Vietnamese.
FONT_PREFERENCE = ("Inter", "Ubuntu", "Noto Sans", "DejaVu Sans")
_font_family = None
_canvases = weakref.WeakSet()


def normalise_theme(value):
    return value if value in THEMES else LIGHT


def is_dark():
    return ctk.get_appearance_mode().lower() == DARK_MODE


def resolve(color):
    """Concrete colour for the current mode (for Tk canvases and Pillow)."""
    if isinstance(color, (tuple, list)):
        return color[1] if is_dark() else color[0]
    return color


def track_canvas(canvas):
    _canvases.add(canvas)


def apply_mode(theme):
    """Switch every widget to `theme`; canvases redraw with the new colours."""
    ctk.set_appearance_mode("Dark" if normalise_theme(theme) == DARK_MODE else "Light")
    for canvas in list(_canvases):
        try:
            canvas.render()
        except Exception:  # destroyed between switch and redraw
            pass


def font_family():
    """Resolve the UI family once a Tk root exists (needs tkfont.families())."""
    global _font_family
    if _font_family is None:
        try:
            available = set(tkfont.families())
        except RuntimeError:  # no default root yet; do not cache the guess
            return FONT_PREFERENCE[-1]
        _font_family = next((f for f in FONT_PREFERENCE if f in available), FONT_PREFERENCE[-1])
    return _font_family


def font(size=13, bold=False):
    return ctk.CTkFont(family=font_family(), size=size, weight="bold" if bold else "normal")


def install(theme=LIGHT):
    ctk.set_appearance_mode("Dark" if normalise_theme(theme) == DARK_MODE else "Light")
    ctk.set_default_color_theme("blue")
    t = ctk.ThemeManager.theme
    pair = list
    t["CTk"].update(fg_color=pair(BG))
    t["CTkToplevel"].update(fg_color=pair(BG))
    t["CTkFrame"].update(fg_color=pair(PANEL), top_fg_color=pair(BG), border_color=pair(LINE), corner_radius=8)
    t["CTkLabel"].update(text_color=pair(INK))
    t["CTkButton"].update(fg_color=pair(BUTTON), hover_color=pair(BUTTON_HOVER), text_color=pair(ON_BUTTON),
                          text_color_disabled=pair(FAINT), border_color=pair(BORDER), corner_radius=6)
    t["CTkEntry"].update(fg_color=pair(PANEL), text_color=pair(INK), border_color=pair(LINE), corner_radius=5)
    t["CTkOptionMenu"].update(fg_color=pair(BUTTON), text_color=pair(ON_BUTTON), button_color=pair(ACCENT),
                              button_hover_color=pair(HOVER))
    t["CTkSegmentedButton"].update(fg_color=pair(BUTTON), text_color=pair(ON_BUTTON), selected_color=pair(ACCENT),
                                   selected_hover_color=pair(HOVER), unselected_color=pair(BUTTON),
                                   unselected_hover_color=pair(MUTED))
    t["CTkSlider"].update(progress_color=pair(ACCENT), button_color=pair(ACCENT), button_hover_color=pair(HOVER),
                          fg_color=pair(LINE))
    t["CTkCheckBox"].update(fg_color=pair(ACCENT), hover_color=pair(HOVER), text_color=pair(INK),
                            border_color=pair(MUTED))
    t["CTkScrollableFrame"].update(label_fg_color=pair(SUBTLE))
    t["CTkScrollbar"].update(button_color=pair(BORDER), button_hover_color=pair(FAINT))
    t["DropdownMenu"].update(fg_color=pair(PANEL), hover_color=pair(SUBTLE), text_color=pair(INK))


def label(parent, text, size=13, bold=False, **kwargs):
    return ctk.CTkLabel(parent, text=text, font=font(size, bold), **kwargs)


def hairline():
    """Border width that CTk draws as exactly 1 px at the current scaling.

    CTk rounds border_width * scaling and draws nothing below ~1.4 logical
    units at 0.75 scaling, so a plain 1 vanishes on the 1024x600 panel.
    """
    return 1.4 / ctk.ScalingTracker.widget_scaling


def card(parent, **kwargs):
    """Panel surface with a hairline border, the building block of every page."""
    options = dict(fg_color=PANEL, border_width=hairline(), border_color=LINE, corner_radius=8)
    options.update(kwargs)
    return ctk.CTkFrame(parent, **options)


def outline_button(parent, text, **kwargs):
    options = dict(fg_color=PANEL, hover_color=SUBTLE, text_color=INK, border_width=hairline(),
                   border_color=BORDER, corner_radius=6, font=font(12, True))
    options.update(kwargs)
    return ctk.CTkButton(parent, text=text, **options)
