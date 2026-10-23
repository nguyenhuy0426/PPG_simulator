"""Drop CustomTkinter's forced layout flush from scrollbar and option-menu redraws.

CustomTkinter 6.0 ends ``CTkScrollbar._draw`` and ``CTkOptionMenu._draw`` with
``self._canvas.update_idletasks()``. Every redraw of one of these small widgets
therefore runs a full geometry/redraw pass of the whole window before
returning. While the Signal setup window is built (three scrollable tabs, four
option menus) those redraws repeat dozens of times: about 1.3 s of the 1.4 s
open time on the x86 laptop. Tk repaints at idle anyway, so the flush is
redundant; the canvas keeps its own update_idletasks for any other caller.
"""
import customtkinter as ctk


def _no_flush():
    return None


def _without_flush(draw):
    def wrapped(self, *args, **kwargs):
        canvas = getattr(self, "_canvas", None)
        if canvas is not None and "update_idletasks" not in vars(canvas):
            canvas.update_idletasks = _no_flush
        return draw(self, *args, **kwargs)
    wrapped.ppg_without_flush = True
    return wrapped


def install():
    """Idempotent; applies to every scrollbar and option menu created afterwards or redrawn."""
    for cls in (ctk.CTkScrollbar, ctk.CTkOptionMenu):
        if not getattr(cls._draw, "ppg_without_flush", False):
            cls._draw = _without_flush(cls._draw)
