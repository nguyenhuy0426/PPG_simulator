"""Settings on the 1024x600 touch panel: Apply stays reachable, a swipe scrolls the form, Apply shows a toast."""
import os
import unittest

os.environ.setdefault("PPG_DRY_RUN", "1")
HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class SettingsTouchTest(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        from ui.frames.advanced_frame import AdvancedFrame
        self.ctk = ctk
        self.root = ctk.CTk()
        self.root.geometry("860x531")          # the Signal setup window size on the Pi panel
        self.addCleanup(self.root.destroy)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        self.panel = AdvancedFrame(self.root, language="vi", fg_color="transparent")
        self.panel.grid(row=0, column=0, sticky="nsew")
        self.root.update()
        self.tab = self.panel.tabs.tab(self.panel.tabs.get())

    def buttons(self):
        body = next(w for w in walk(self.tab) if isinstance(w, self.ctk.CTkScrollableFrame))
        inside = set(walk(body))
        return [w for w in walk(self.tab) if isinstance(w, self.ctk.CTkButton) and w not in inside]

    def test_apply_button_is_visible_without_scrolling(self):
        (button,) = self.buttons()
        self.assertEqual(button.cget("text"), "Áp dụng biên độ & hình dạng")
        bottom = button.winfo_rooty() + button.winfo_height()
        self.assertTrue(button.winfo_ismapped())
        self.assertLessEqual(bottom, self.root.winfo_rooty() + self.root.winfo_height())

    def test_swipe_on_the_form_scrolls_it(self):
        body = next(w for w in walk(self.tab) if isinstance(w, self.ctk.CTkScrollableFrame))
        canvas = body._parent_canvas
        label = next(w for w in walk(body) if w.winfo_class() == "Label" and w.winfo_ismapped())
        self.assertEqual(canvas.yview()[0], 0.0)
        label.event_generate("<ButtonPress-1>", x=5, y=5, rootx=100, rooty=400)
        label.event_generate("<B1-Motion>", x=5, y=-195, rootx=100, rooty=200)
        self.root.update()
        self.assertGreater(canvas.yview()[0], 0.1)

    def test_apply_shows_a_toast_then_hides_it(self):
        from ui.frames import advanced_frame
        (button,) = self.buttons()
        button.invoke()
        self.root.update()
        self.assertTrue(self.panel.toast.winfo_ismapped())
        self.assertEqual(self.panel.toast.cget("text"), "✓ Đã thiết lập thông số: biên độ & hình dạng")
        self.panel._hide_toast()
        self.root.update()
        self.assertFalse(self.panel.toast.winfo_ismapped())
        self.assertGreater(advanced_frame.TOAST_MS, 1000)

    def test_failed_apply_shows_the_error_and_no_toast(self):
        def fail():
            raise ValueError("DC + offset > 3000 mV")
        self.panel._apply(fail)
        self.root.update()
        self.assertFalse(self.panel.toast.winfo_ismapped())
        self.assertEqual(self.panel.status.cget("text"), "DC + offset > 3000 mV")

if __name__ == "__main__":
    unittest.main()
