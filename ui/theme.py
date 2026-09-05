"""Clinical instrument palette: light controls, charcoal signal surfaces."""
import customtkinter as ctk

BG = "#EDF0F2"
PANEL = "#FFFFFF"
INK = "#20272D"
MUTED = "#5E6B75"
LINE = "#D6DDE2"
DARK = "#192126"
GRID = "#344148"
IR = "#A3E3D0"
RED = "#FFABA5"
ACCENT = "#245D60"
HOVER = "#34777A"
ERROR = "#B13737"


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
    return ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(
        family="DejaVu Sans", size=size, weight="bold" if bold else "normal"), **kwargs)
