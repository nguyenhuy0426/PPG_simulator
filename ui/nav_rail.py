"""Collapsible navigation rail.

Collapsed it is an icon column (56 px on the 1024x600 panel). Expanded it
widens to show labels and is drawn *over* the page instead of pushing it,
so the signal plots never reflow or redraw because of navigation. Picking a
page, or tapping anywhere outside the rail, collapses it again.
"""
import customtkinter as ctk

from ui import focus_is_inside
from ui import icons
from ui import theme as T


class RailItem(ctk.CTkFrame):
    def __init__(self, rail, icon_name, label, command, bold=False):
        ui = rail.ui
        super().__init__(rail, fg_color=T.PANEL, corner_radius=0, height=ui(48))
        self.rail, self.command, self.bold = rail, command, bold
        self.active = False
        self.grid_propagate(False)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(2, weight=1)
        self.indicator = ctk.CTkFrame(self, width=ui(3), corner_radius=0, fg_color=T.PANEL)
        self.indicator.grid(row=0, column=0, sticky="ns", pady=ui(8))
        self.icon = ctk.CTkLabel(self, text="", width=rail.collapsed_width - ui(3))
        self.icon.grid(row=0, column=1, sticky="ns")
        self.text = T.label(self, label, ui(14), bold, text_color=T.INK if bold else T.MUTED, anchor="w")
        self.set_icon(icon_name)
        for widget in (self, self.indicator, self.icon, self.text):
            widget.bind("<Button-1>", lambda _event: self.command())
            widget.bind("<Enter>", lambda _event: self._hover(True))
            widget.bind("<Leave>", lambda _event: self._hover(False))
        for widget in (self.icon, self.text):
            widget.configure(cursor="hand2")

    def set_icon(self, name):
        size = self.rail.ui(22)
        self._images = (icons.icon(name, T.MUTED, size), icons.icon(name, T.ACCENT, size))
        self.icon.configure(image=self._images[self.active])

    def set_label(self, label):
        self.text.configure(text=label)

    def show_label(self, visible):
        if visible:
            self.text.grid(row=0, column=2, sticky="w", padx=(0, self.rail.ui(12)))
        else:
            self.text.grid_remove()

    def _paint(self, hover=False):
        fill = T.SUBTLE if (self.active or hover) else T.PANEL
        for widget in (self, self.icon, self.text):
            widget.configure(fg_color=fill)
        self.indicator.configure(fg_color=T.ACCENT if self.active else fill)

    def _hover(self, inside):
        self._paint(hover=inside)

    def set_active(self, active):
        self.active = bool(active)
        self.icon.configure(image=self._images[self.active])
        if not self.bold:
            self.text.configure(text_color=T.INK if self.active else T.MUTED,
                                font=T.font(self.text.cget("font").cget("size"), self.active))
        self._paint()

    def invoke(self):
        self.command()


class NavRail(ctk.CTkFrame):
    def __init__(self, master, ui, on_select):
        self.ui = ui
        self.collapsed_width, self.expanded_width = ui(56), ui(216)
        super().__init__(master, fg_color=T.PANEL, corner_radius=0, width=self.collapsed_width)
        self.on_select = on_select
        self.expanded = False
        self.items = {}
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self._row = 0
        self.add("menu", "menu", "PPG", self.toggle, bold=True)
        divider = ctk.CTkFrame(self, height=T.hairline(), corner_radius=0, fg_color=T.LINE)
        divider.grid(row=self._next_row(), column=0, sticky="ew", padx=ui(10), pady=(0, ui(6)))
        self._spacer_row = None
        # Right-hand hairline separating the rail from the page.
        ctk.CTkFrame(self, width=T.hairline(), corner_radius=0, fg_color=T.LINE).place(
            relx=1.0, rely=0, relheight=1, anchor="ne")

    def _next_row(self):
        row, self._row = self._row, self._row + 1
        return row

    def add(self, key, icon_name, label, command, bold=False):
        item = RailItem(self, icon_name, label, command, bold)
        item.grid(row=self._next_row(), column=0, sticky="ew")
        self.items[key] = item
        return item

    def add_page(self, key, icon_name, label):
        item = self.add(key, icon_name, label, lambda: self._pick(key))
        item.is_page = True
        return item

    def add_spacer(self):
        row = self._next_row()
        self.grid_rowconfigure(row, weight=1)

    def _pick(self, key):
        self.collapse()
        self.on_select(key)

    def select(self, key):
        """Mark the page `key` as current (pages only; footer items are separate)."""
        for name, item in self.items.items():
            if getattr(item, "is_page", False):
                item.set_active(name == key)

    def expand(self):
        if self.expanded:
            return
        self.expanded = True
        self.configure(width=self.expanded_width)
        for item in self.items.values():
            item.show_label(True)
        self.items["menu"].set_icon("collapse")
        self.lift()

    def collapse(self):
        if not self.expanded:
            return
        self.expanded = False
        for item in self.items.values():
            item.show_label(False)
        self.configure(width=self.collapsed_width)
        self.items["menu"].set_icon("menu")

    def toggle(self):
        self.collapse() if self.expanded else self.expand()

    def click_outside(self, event):
        """Root-level click handler: collapse when the tap lands on the page."""
        widget = event.widget
        if self.expanded and not isinstance(widget, str) and not focus_is_inside(widget, self):
            self.collapse()
