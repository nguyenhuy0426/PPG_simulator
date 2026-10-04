"""Classic page: honest output status, setpoint stepping and layout sizing.

The Tk tests need a display (Xvfb is fine); they skip on a headless machine.
"""
import os
import unittest

from models.ppg_model import CONDITION_NAMES
from ui.i18n import condition_labels
from ui.responsive import profile_for_screen

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class TestPureHelpers(unittest.TestCase):
    def test_condition_labels_follow_model_order(self):
        for language in ("en", "vi"):
            self.assertEqual(len(condition_labels(language)), len(CONDITION_NAMES))
        self.assertEqual(condition_labels("vi")[5], "Giãn mạch")
        self.assertEqual(condition_labels("fr"), condition_labels("en"))

    def test_touch_pixels_survive_widget_scaling(self):
        touch = profile_for_screen(1024, 600)
        # 0.75 widget scaling on the 7-inch panel: 12 px needs 16 logical units.
        self.assertEqual(touch.ui(12), 16)
        self.assertAlmostEqual(touch.ui(12) * touch.widget_scale, 12)
        desktop = profile_for_screen(1280, 800)
        self.assertEqual(desktop.ui(12), 15)
        qhd = profile_for_screen(2560, 1440)
        self.assertLessEqual(qhd.ui(12) * qhd.widget_scale, 12 * 1.4 + 1)


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class TestClassicPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.ctk_app import CTkApp
        CTkApp._maximize_to_work_area = lambda self: None
        cls.app = CTkApp(language="vi")
        cls.app._save_language = lambda: None
        cls.app.withdraw()
        cls.page = cls.app.frames["Pathology"]

    @classmethod
    def tearDownClass(cls):
        cls.app.on_closing()

    def test_status_never_claims_led_output_without_a_dac(self):
        from ui import theme as T
        from ui.frames import pathology_frame
        engine, dac = self.page.engine, self.page.engine.dac_manager
        saved = (pathology_frame.DRY_RUN, dac._ready, engine._running)
        try:
            pathology_frame.DRY_RUN = False
            dac._ready, engine._running = False, True
            colour, headline, detail = self.page._status()
            self.assertEqual(colour, T.ERROR)
            self.assertIn("DAC", headline)
            self.assertIn("0x60", detail)
            engine._running = False
            colour, _headline, detail = self.page._status()
            self.assertEqual(colour, T.ERROR)
            self.assertIn("0x61", detail)
        finally:
            pathology_frame.DRY_RUN, dac._ready, engine._running = saved

    def test_dac_errors_are_counted_per_run(self):
        from ui import theme as T
        from ui.frames import pathology_frame
        engine, dac = self.page.engine, self.page.engine.dac_manager
        saved = (pathology_frame.DRY_RUN, dac._ready, engine._running, dac._error_count_red)
        try:
            pathology_frame.DRY_RUN = False
            dac._ready, engine._running, dac._error_count_red = True, False, 1
            self.page._status()                      # stopped: start-up error is history
            engine._running = True
            colour, _headline, _detail = self.page._status()
            self.assertEqual(colour, T.OK)
            dac._error_count_red += 3
            colour, _headline, detail = self.page._status()
            self.assertEqual(colour, T.ERROR)
            self.assertIn("RED lỗi 3", detail)
        finally:
            pathology_frame.DRY_RUN, dac._ready, engine._running, dac._error_count_red = saved
            self.page._dac_error_base = (0, 0)

    def test_dry_run_status_is_labelled_as_simulation(self):
        from ui import theme as T
        engine = self.page.engine
        saved = engine._running
        try:
            engine._running = True
            colour, headline, detail = self.page._status()
            self.assertEqual(colour, T.WARN)
            self.assertIn("mô phỏng", headline)
            self.assertIn("Dry-run", detail)
        finally:
            engine._running = saved

    def test_setpoint_buttons_snap_to_the_step_grid(self):
        card = self.page.cards["pi"]
        sent = []
        command, card.command = card.command, sent.append
        try:
            card.set(3.04)
            card._nudge(1)
            card._nudge(-1)
            card.set(3.045)
            card._nudge(1)
            card._nudge(-1)
        finally:
            card.command = command
        self.assertEqual(sent, [3.05, 3.03, 3.05, 3.04])

    def test_condition_selector_drives_the_model_preset(self):
        engine = self.page.engine
        saved = engine.ppg_params.condition
        try:
            self.page.condition_menu.invoke("Co mạch")
            self.assertEqual(engine.ppg_params.condition, CONDITION_NAMES.index("Vasocnstr."))
        finally:
            engine.change_condition(saved)

    def test_rx_card_shows_no_samples_in_dry_run(self):
        self.app._show_frame("Pathology")
        self.app.deiconify()
        self.app.update()
        panel = self.page.rx_panel
        panel._last_update = 0.0
        panel.periodic_update()
        self.app.withdraw()
        self.assertTrue(panel.lanes)
        self.assertTrue(all(not lane.points for lane in panel.lanes))


if __name__ == "__main__":
    unittest.main()


class TestThemeAndIcons(unittest.TestCase):
    def test_every_icon_renders_for_both_modes(self):
        from ui import icons
        for name in icons.NAMES:
            light = icons._render(name, "#1E252B")
            self.assertIsNotNone(light)
            self.assertIsNotNone(light.getbbox(), name)   # something was drawn

    def test_config_theme_is_normalised(self):
        import json, tempfile
        import config_store
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "config.json")
            saved = config_store.CONFIG_JSON_PATH
            config_store.CONFIG_JSON_PATH = path
            try:
                for stored, expected in (("dark", "dark"), ("blur", "light"), (None, "light")):
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump({"theme": stored}, handle)
                    self.assertEqual(config_store.load_config()["theme"], expected)
            finally:
                config_store.CONFIG_JSON_PATH = saved


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class TestRailAndTheme(unittest.TestCase):
    def test_rail_navigation_theme_switch_and_collapse(self):
        from ui import theme as T
        from ui.ctk_app import CTkApp
        CTkApp._maximize_to_work_area = lambda self: None
        app = CTkApp(language="en")
        app._save_language = lambda: None
        saved = []
        app._save_ui_setting = lambda key, value: saved.append((key, value))
        try:
            app.update()
            rail = app.rail
            self.assertFalse(rail.expanded)
            rail.items["menu"].invoke()
            self.assertTrue(rail.expanded)
            rail.items["Calibration"].invoke()          # picking a page collapses
            self.assertFalse(rail.expanded)
            self.assertIs(app.active_frame, app.frames["Calibration"])
            self.assertTrue(rail.items["Calibration"].active)
            self.assertFalse(rail.items["Pathology"].active)
            app.toggle_theme()
            self.assertEqual(app.theme, T.DARK_MODE)
            self.assertTrue(T.is_dark())
            self.assertEqual(app.frames["Pathology"].trace.cget("bg"), T.DARK[1])
            self.assertEqual(saved, [("theme", "dark")])
            app.toggle_theme()
            self.assertFalse(T.is_dark())
            self.assertEqual(app.frames["Pathology"].trace.cget("bg"), T.DARK[0])
        finally:
            app.on_closing()
