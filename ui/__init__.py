# ui package


def focus_is_inside(focused, widget):
    """True when `focused` is `widget` itself or one of its internal children.

    CustomTkinter routes keyboard focus to a plain tkinter child widget
    (e.g. the ``tkinter.Entry`` inside a ``CTkEntry``), so comparing a live
    ``toplevel.focus_get()`` result to the CTk wrapper by identity never
    matches. Any "don't clobber the widget the user is editing" guard must
    walk the master chain instead.
    """
    while focused is not None:
        if focused is widget:
            return True
        focused = getattr(focused, "master", None)
    return False
