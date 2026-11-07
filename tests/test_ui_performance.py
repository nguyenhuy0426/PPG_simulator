"""UI responsiveness: no forced layout flushes, a reused Signal setup window and no redundant redraws.

The Tk tests need a display (Xvfb is fine); they skip on a headless machine.
"""
import os
import unittest
from unittest import mock

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class TestResponsiveUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.ctk_app import CTkApp
        CTkApp._maximize_to_work_area = lambda self: None
        cls.app = CTkApp(language="en")
        cls.app._save_language = lambda: None
        cls.app._save_ui_setting = lambda key, value: None
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.on_closing()

    def test_scrollbar_and_option_menu_redraws_do_not_flush_the_whole_window(self):
        import tkinter
        import customtkinter as ctk
        frame = ctk.CTkScrollableFrame(self.app)
        menu = ctk.CTkOptionMenu(self.app, values=["a", "b"])
        try:
            with mock.patch.object(tkinter.Misc, "update_idletasks") as flush:
                frame._scrollbar.set(0., .5)
                menu.set("b")
                menu._draw()
            flush.assert_not_called()
            self.assertTrue(ctk.CTkScrollbar._draw.ppg_without_flush)
        finally:
            frame.destroy()
            menu.destroy()

    def test_signal_setup_window_is_reused_and_reloads_from_the_engine(self):
        app = self.app
        app.open_signal_setup()
        app.update()
        window, panel = app.signal_setup_window, app.signal_setup_panel
        try:
            # Only the visible tab is built when the window opens.
            self.assertIn("dc_ir_mv", panel.entries)
            self.assertNotIn("resp_rate", panel.entries)
            self.assertNotIn("noise_amplitude_mv", panel.entries)
            truth = panel.entries["dc_ir_mv"].get()
            entry = panel.entries["dc_ir_mv"]
            entry.set(entry.minimum if float(truth) != entry.minimum else entry.maximum)  # never applied
            self.assertNotEqual(entry.get(), truth)
            app.close_signal_setup()
            self.assertFalse(app.signal_setup_visible)
            self.assertFalse(app.signal_setup_bubble.active)
            app.open_signal_setup()
            app.update()
            self.assertIs(app.signal_setup_window, window)
            self.assertIs(app.signal_setup_panel, panel)
            self.assertEqual(panel.entries["dc_ir_mv"].get(), truth)
            self.assertEqual(panel.status.cget("text"), panel.idle_status)
            # A later tab is built, and loaded from the engine, when it is first shown.
            panel.tabs.set("Respiration")
            panel._build_tab("Respiration")
            rate = app.engine.ppg_params.resp_rate
            self.assertEqual(float(panel.entries["resp_rate"].get()), rate)
            self.assertEqual(panel.entries["dc_ir_mv"].get(), truth)
        finally:
            app.close_signal_setup(destroy=True)
        self.assertIsNone(app.signal_setup_window)

    def test_unapplied_edit_survives_building_another_tab(self):
        app = self.app
        app.open_signal_setup()
        app.update()
        panel = app.signal_setup_panel
        try:
            truth = float(panel.entries["dc_ir_mv"].get())
            entry = panel.entries["dc_ir_mv"]
            edit = entry.minimum if truth != entry.minimum else entry.maximum
            entry.set(edit)
            panel.waveform_menu.set("sine" if panel.waveform_menu.get() != "sine" else "square")
            edited = panel.waveform_menu.get()
            panel._build_tab("Noise & calibration")
            self.assertEqual(float(panel.entries["dc_ir_mv"].get()), edit)
            self.assertEqual(panel.waveform_menu.get(), edited)
            self.assertEqual(panel.noise_menu.get(), app.engine.ppg_params.noise_kind)
        finally:
            app.close_signal_setup(destroy=True)

    def test_identical_lane_updates_are_not_redrawn(self):
        from ui.trace_view import Lane, LaneView
        view = LaneView(self.app, width=400, height=200)
        try:
            with mock.patch.object(view, "render") as render:
                lanes = [Lane("IR", "#fff", "mV", [(0., 1.), (1., 2.)])]
                view.update_lanes(lanes, end_s=0.)
                view.update_lanes([Lane("IR", "#fff", "mV", [(0., 1.), (1., 2.)])], end_s=0.)
                self.assertEqual(render.call_count, 1)
                view.update_lanes([Lane("IR", "#fff", "mV", [(0., 1.), (1., 3.)])], end_s=0.)
                view.update_lanes([Lane("IR", "#fff", "dB", [(0., 1.), (1., 3.)])], end_s=0.)
                self.assertEqual(render.call_count, 3)
        finally:
            view.destroy()

    def test_touch_slider_reconfigures_only_what_changed(self):
        from ui.touch_slider import TouchSlider
        slider = TouchSlider(self.app, 0, 100, value=10)
        try:
            with mock.patch.object(slider.minus, "configure") as minus, \
                    mock.patch.object(slider.readout, "configure") as readout:
                slider.set(10)
                minus.assert_not_called()
                readout.assert_not_called()
                slider.set(20)
                readout.assert_called_once()
                minus.assert_not_called()
            self.assertEqual(slider.get(), "20")
            slider.configure(state="disabled")
            self.assertEqual(slider.minus.cget("state"), "disabled")
        finally:
            slider.destroy()

    def test_setpoint_badge_is_not_regridded_every_tick(self):
        card = self.app.frames["Pathology"].cards["spo2"]
        card.set_badge("held")
        with mock.patch.object(card.badge, "grid") as grid:
            card.set_badge("held")
            grid.assert_not_called()
        card.set_badge(None)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class IncrementalRenderTest(unittest.TestCase):
    """A live frame patched in place must leave the same canvas items as a fresh full draw."""

    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()

    def tearDown(self):
        self.root.destroy()

    def view(self):
        from ui.trace_view import LaneView
        view = LaneView(self.root, width=600, height=300)
        view.pack(fill="both", expand=True)
        self.root.update()
        return view

    @staticmethod
    def lanes(shift, badge2="", gap=None, scale=1.0):
        import math
        from ui.trace_view import Lane
        pts = [(i * 0.01 - 8 + shift, 900 + scale * 60 * math.sin(2 * math.pi * 1.25 * (i * 0.01 + shift)))
               for i in range(800)]
        if gap is not None:
            pts = [p for p in pts if not (gap[0] <= p[0] <= gap[1])]
        # the reading in the header changes on every frame, as a live mV value does
        return [Lane("IR", "#7FD8BE", f"Live   {pts[-1][1]:.0f} mV", pts, badge=f"RX rate {70 + int(shift) % 9} bpm",
                     max_gap_s=.05, badge2=badge2),
                Lane("RED", "#F4958C", f"Live   {pts[-1][1] * .8:.0f} mV", [(t, v * 0.8) for t, v in pts],
                     max_gap_s=.05)]

    @staticmethod
    def snapshot(view):
        out = []
        for item in view.find_all():
            kind = view.type(item)
            row = [kind, tuple(round(c, 3) for c in view.coords(item)), view.itemcget(item, "fill")]
            if kind == "text":
                row.append(view.itemcget(item, "text"))
            out.append(tuple(row))
        return out

    def assert_same_as_fresh(self, view, lanes):
        fresh = self.view()
        try:
            fresh.update_lanes(lanes, end_s=0.0)
            # same items; only their stacking order may differ when a gap added or removed a line piece
            self.assertEqual(sorted(self.snapshot(view)), sorted(self.snapshot(fresh)))
        finally:
            fresh.destroy()

    def test_scrolling_samples_match_a_full_draw_and_keep_the_items(self):
        view = self.view()
        view.update_lanes(self.lanes(0.0), end_s=0.0)
        ids = set(view.find_all())
        for step in range(1, 40):
            shift = step * 0.1                        # crosses several whole-second boundaries
            lanes = self.lanes(shift, scale=1.0 + step * 0.01)
            view.update_lanes(lanes, end_s=0.0)
            self.assert_same_as_fresh(view, lanes)
        # polylines and y labels survive between whole-second changes; only the grid is re-created
        self.assertTrue(len(ids & set(view.find_all())) > 10)

    def test_a_layout_change_rebuilds(self):
        view = self.view()
        view.update_lanes(self.lanes(0.0), end_s=0.0)
        for lanes in (self.lanes(0.1, badge2="SpO2 est. 97.5 %"), self.lanes(0.2),
                      self.lanes(0.3, gap=(-5.0, -4.0))):    # a hole splits the line, so the item count changes
            view.update_lanes(lanes, end_s=0.0)
            self.assert_same_as_fresh(view, lanes)

    def test_an_incremental_frame_makes_far_fewer_tk_calls(self):
        view = self.view()
        view.update_lanes(self.lanes(0.0), end_s=0.0)
        calls = []
        real_create = view.create_text
        view.create_text = lambda *a, **k: (calls.append(1), real_create(*a, **k))[1]
        view.update_lanes(self.lanes(0.1), end_s=0.0)
        self.assertEqual(len(calls), 0)


class EstimateBudgetTest(unittest.TestCase):
    """Due rate/SpO2 refreshes are spread over ticks instead of stalling one tick with all of them."""

    def test_one_refresh_per_tick_and_first_estimates_are_never_deferred(self):
        from ui.rx_monitor import RXPanel
        panel = RXPanel.__new__(RXPanel)
        panel._heavy = 1
        self.assertTrue(panel._may_estimate(None))        # first value: always computed
        self.assertTrue(panel._may_estimate(None))
        self.assertTrue(panel._may_estimate((0.0, "old")))  # one due refresh uses the budget
        self.assertFalse(panel._may_estimate((0.0, "old")))  # the next waits for the following tick
        panel._heavy = 1
        self.assertTrue(panel._may_estimate((0.0, "old")))
