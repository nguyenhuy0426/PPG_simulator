"""Outlined selector: shows the current choice and opens CTk's own dropdown.

Unlike CTkOptionMenu it draws a real 1 px border with the chevron pinned to
the right edge, and it has no text entry, so the touch panel never needs an
on-screen keyboard.
"""
import customtkinter as ctk
from customtkinter.windows.widgets.core_widget_classes import DropdownMenu

from ui import icons
from ui import theme as T


class SelectButton(ctk.CTkFrame):
    def __init__(self, master, values, command=None, font=None, dropdown_font=None,
                 width=140, height=32, icon_size=14, pad=10, **kwargs):
        super().__init__(master, width=width, height=height, fg_color=T.PANEL, border_width=T.hairline(),
                         border_color=T.BORDER, corner_radius=6, **kwargs)
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._values, self._command, self._value = list(values), command, ""
        self._label = ctk.CTkLabel(self, text="", font=font or T.font(12), text_color=T.INK, anchor="w")
        self._label.grid(row=0, column=0, sticky="ew", padx=(pad, 4), pady=2)
        self._chevron = ctk.CTkLabel(self, text="", image=icons.icon("chevron", T.MUTED, icon_size))
        self._chevron.grid(row=0, column=1, padx=(0, pad - 2), pady=2)
        self._menu = DropdownMenu(master=self, values=self._values, command=self._chosen,
                                  fg_color=T.PANEL, hover_color=T.SUBTLE, text_color=T.INK,
                                  font=dropdown_font or font or T.font(12))
        for widget in (self, self._label, self._chevron):
            widget.bind("<Button-1>", lambda _event: self._open())
            widget.bind("<Enter>", lambda _event: self._hover(True))
            widget.bind("<Leave>", lambda _event: self._hover(False))
            widget.configure(cursor="hand2")

    def _hover(self, inside):
        colour = T.SUBTLE if inside else T.PANEL
        self.configure(fg_color=colour)
        for widget in (self._label, self._chevron):
            widget.configure(fg_color=colour)

    def _open(self):
        self._menu.open(self.winfo_rootx(), self.winfo_rooty() + self.winfo_height() + 2)

    def _chosen(self, value):
        self.set(value)
        if self._command is not None:
            self._command(value)

    def invoke(self, value):
        """Choose `value` as if picked from the menu (tests and automation)."""
        self._chosen(value)

    def get(self):
        return self._value

    def set(self, value):
        self._value = value
        self._label.configure(text=value)

    def set_values(self, values):
        self._values = list(values)
        self._menu.configure(values=self._values)
