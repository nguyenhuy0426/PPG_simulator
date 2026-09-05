"""The window manager's close button must reach CTkApp.on_closing.

on_closing() has always existed but was never bound to WM_DELETE_WINDOW, so the
title-bar X went to Tk's built-in default handler instead — the app was torn
down without passing through its own close path. Asserting merely that *some*
handler exists is not enough: Tk installs a default one, so the test invokes the
registered command and checks that our method is what ran.

These tests need a real display; they skip on a headless machine.
"""

import os
import unittest

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class TestCTkAppShutdownBinding(unittest.TestCase):

    def test_close_button_invokes_on_closing(self):
        from ui.ctk_app import CTkApp

        calls = []
        original = CTkApp.on_closing
        # Patched on the class, not the instance: __init__ binds the method
        # object, so the substitution has to be in place before construction.
        CTkApp.on_closing = lambda self: calls.append("closed")
        app = CTkApp()
        app.withdraw()
        try:
            command = app.protocol("WM_DELETE_WINDOW")
            self.assertTrue(command, "WM_DELETE_WINDOW has no handler bound")
            app.tk.call(command)      # what the window manager sends on close
            self.assertEqual(calls, ["closed"])
        finally:
            CTkApp.on_closing = original
            try:
                app.destroy()
            except Exception:
                # Unbound, Tk's default handler already destroyed the window.
                pass

    def test_on_closing_destroys_the_window(self):
        from ui.ctk_app import CTkApp

        app = CTkApp()
        app.withdraw()
        destroyed = []
        app.destroy = lambda: destroyed.append(True)
        app.on_closing()
        self.assertEqual(destroyed, [True])
        del app.destroy
        app.destroy()


if __name__ == "__main__":
    unittest.main()
