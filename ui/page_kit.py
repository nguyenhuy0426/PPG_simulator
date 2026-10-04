"""Building blocks shared by every page, so they all read as one instrument.

Sizes are pixels on the 1024x600 panel (theme.ui converts them).
"""
import customtkinter as ctk

from ui import icons
from ui import theme as T


def page_header(parent, row=0):
    """Title + muted subtitle on the left, an actions frame on the right."""
    u = T.ui
    bar = ctk.CTkFrame(parent, fg_color="transparent")
    bar.grid(row=row, column=0, columnspan=99, sticky="ew", pady=(0, u(8)))
    bar.grid_columnconfigure(0, weight=1)
    title = T.label(bar, "", u(17), True, anchor="w")
    title.grid(row=0, column=0, sticky="w")
    subtitle = T.label(bar, "", u(12), text_color=T.MUTED, anchor="w", justify="left")
    subtitle.grid(row=1, column=0, sticky="w")
    actions = ctk.CTkFrame(bar, fg_color="transparent", width=1, height=1)
    actions.grid(row=0, column=1, rowspan=2, sticky="e")
    return title, subtitle, actions


def section(parent, title="", span=1):
    """Bordered card with a title row; returns (card, title_label, tools_frame).

    Put widgets in rows >= 1 of the card; `tools_frame` sits right of the title.
    """
    u = T.ui
    card = T.card(parent)
    card.grid_columnconfigure(0, weight=1)
    head = ctk.CTkFrame(card, fg_color="transparent")
    head.grid(row=0, column=0, columnspan=span, sticky="ew", padx=u(10), pady=(u(8), u(6)))
    head.grid_columnconfigure(0, weight=1)
    label = T.label(head, title, u(14), True, anchor="w", height=u(30))
    label.grid(row=0, column=0, sticky="w")
    tools = ctk.CTkFrame(head, fg_color="transparent", width=1, height=1)  # CTk default is 200x200
    tools.grid(row=0, column=1, sticky="e")
    return card, label, tools


def plot_holder(card, row=1):
    """Rounded charcoal well inside a card; pack a TraceView/LaneView into it."""
    u = T.ui
    holder = ctk.CTkFrame(card, fg_color=T.DARK, corner_radius=u(6))
    holder.grid(row=row, column=0, sticky="nsew", padx=u(6), pady=(0, u(6)))
    card.grid_rowconfigure(row, weight=1)
    return holder


def primary_button(parent, text="", command=None, width=128, **kwargs):
    u = T.ui
    return ctk.CTkButton(parent, text=text, command=command, height=u(36), width=u(width), compound="left",
                         font=T.font(u(13), True), fg_color=T.ACCENT, hover_color=T.HOVER,
                         text_color=T.WHITE, **kwargs)


def secondary_button(parent, text="", command=None, width=120, icon=None, **kwargs):
    u = T.ui
    image = icons.icon(icon, T.INK, u(16)) if icon else None
    return T.outline_button(parent, text, command=command, height=u(36), width=u(width), image=image,
                            compound="left", font=T.font(u(13), True), **kwargs)


def set_running(button, running, start_text, stop_text):
    """Accent 'start' with a play icon, or red 'stop' with a stop icon."""
    u = T.ui
    button.configure(text=stop_text if running else start_text,
                     image=icons.icon("stop" if running else "play", T.WHITE, u(14)),
                     fg_color=T.ERROR if running else T.ACCENT,
                     hover_color=T.ERROR_HOVER if running else T.HOVER)
