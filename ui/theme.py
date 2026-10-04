"""Clinical instrument palette: light controls, charcoal signal surfaces."""
import tkinter.font as tkfont

import customtkinter as ctk

# Surfaces
BG = "#EDF0F2"          # window / page background
PANEL = "#FFFFFF"       # cards, header, footer
SUBTLE = "#F5F7F8"      # quiet fills (hover, inactive chips)
LINE = "#D9DFE3"        # 1 px card borders and dividers
BORDER = "#C9D1D7"      # outlined buttons and inputs: a step darker than LINE
# Text
INK = "#1E252B"
MUTED = "#66727C"
FAINT = "#98A3AB"
# Signal surfaces (always dark: waveforms read best on charcoal)
DARK = "#1B2328"
GRID = "#2E3A41"
AXIS = "#8C9AA3"
PLOT_TEXT = "#D3DCE1"
IR = "#7FD8BE"
RED = "#F4958C"
# Actions and states
ACCENT = "#245D60"
HOVER = "#34777A"
ERROR = "#B13737"
ERROR_HOVER = "#952C2C"
OK = "#2F9466"
OK_BG = "#E3F3EB"
ERROR_BG = "#F8E1E1"
WARN = "#C98A12"
WARN_BG = "#FBEED3"
WARN_INK = "#8A5A00"

# First installed family wins. Ubuntu ships "Ubuntu"; DejaVu is the portable
# fallback that the project used before and always covers Vietnamese.
FONT_PREFERENCE = ("Inter", "Ubuntu", "Noto Sans", "DejaVu Sans")
_font_family = None


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


def install():
    ctk.set_appearance_mode("Light")
    ctk.set_default_color_theme("blue")
    theme = ctk.ThemeManager.theme
    theme["CTk"].update(fg_color=[BG, BG])
    theme["CTkFrame"].update(fg_color=[PANEL, PANEL], top_fg_color=[BG, BG],
                             border_color=[LINE, LINE], corner_radius=8)
    theme["CTkLabel"].update(text_color=[INK, INK])
    theme["CTkButton"].update(fg_color=[INK, INK], hover_color=[ACCENT, ACCENT],
                              text_color=[PANEL, PANEL], corner_radius=6)
    theme["CTkEntry"].update(fg_color=[PANEL, PANEL], text_color=[INK, INK],
                             border_color=[LINE, LINE], corner_radius=5)
    for kind in ("CTkOptionMenu", "CTkSegmentedButton"):
        theme[kind].update(fg_color=[INK, INK], text_color=[PANEL, PANEL])
    theme["CTkOptionMenu"].update(button_color=[ACCENT, ACCENT], button_hover_color=[HOVER, HOVER])
    theme["CTkSegmentedButton"].update(selected_color=[ACCENT, ACCENT], selected_hover_color=[HOVER, HOVER],
                                       unselected_color=[INK, INK], unselected_hover_color=[MUTED, MUTED])
    theme["CTkSlider"].update(progress_color=[ACCENT, ACCENT], button_color=[ACCENT, ACCENT],
                              button_hover_color=[HOVER, HOVER], fg_color=[LINE, LINE])
    theme["CTkCheckBox"].update(fg_color=[ACCENT, ACCENT], hover_color=[HOVER, HOVER],
                                text_color=[INK, INK], border_color=[MUTED, MUTED])


def label(parent, text, size=13, bold=False, **kwargs):
    return ctk.CTkLabel(parent, text=text, font=font(size, bold), **kwargs)


def hairline():
    """Border width that CTk draws as exactly 1 px at the current scaling.

    CTk rounds border_width * scaling and draws nothing below ~1.4 logical
    units at 0.75 scaling, so a plain 1 vanishes on the 1024x600 panel.
    """
    return 1.4 / ctk.ScalingTracker.widget_scaling


def card(parent, **kwargs):
    """White surface with a hairline border, the building block of every page."""
    options = dict(fg_color=PANEL, border_width=hairline(), border_color=LINE, corner_radius=8)
    options.update(kwargs)
    return ctk.CTkFrame(parent, **options)


def outline_button(parent, text, **kwargs):
    options = dict(fg_color=PANEL, hover_color=SUBTLE, text_color=INK, border_width=hairline(),
                   border_color=BORDER, corner_radius=6, font=font(12, True))
    options.update(kwargs)
    return ctk.CTkButton(parent, text=text, **options)
