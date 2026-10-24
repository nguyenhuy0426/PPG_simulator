"""The Signal setup window follows the chosen language: no English form text left in Vietnamese."""
import os
import unittest

from ui.frames.advanced_frame import COPY

HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def test_both_languages_have_the_same_keys():
    assert set(COPY["en"]) == set(COPY["vi"])


def texts(widget):
    """Every text shown under a widget (labels, buttons, checkboxes, option-menu values)."""
    found = []
    for child in widget.winfo_children():
        for option in ("text",):
            try:
                value = child.cget(option)
            except Exception:
                value = None
            if isinstance(value, str) and value:
                found.append(value)
        values = getattr(child, "_values", None)
        if isinstance(values, (list, tuple)):
            found.extend(str(v) for v in values)
        found.extend(texts(child))
    return found


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class TestSettingsLanguage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.ctk_app import CTkApp
        CTkApp._maximize_to_work_area = lambda self: None
        cls.app = CTkApp(language="vi")
        cls.app._save_language = lambda: None
        cls.app._save_ui_setting = lambda key, value: None
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.on_closing()

    def shown(self):
        panel = self.app.signal_setup_panel
        for name in list(panel._unbuilt):
            panel.tabs.set(name)
            panel._build_tab(name)
        self.app.update()
        return texts(self.app.signal_setup_window)

    def english_only(self):
        """English strings that differ from their Vietnamese counterpart (shared tokens like 'PPG' excluded)."""
        out = set()
        for key, value in COPY["en"].items():
            if isinstance(value, str) and value != COPY["vi"][key]:
                out.update(line for line in value.split("\n"))
        out.update({"Signal setup", "AC above DC", "AC below DC", "proportional", "white", "motion", "triangle"})
        return out

    def test_vietnamese_window_has_no_english_form_text(self):
        self.app.open_signal_setup()
        try:
            shown = self.shown()
            leftovers = sorted(s for s in shown if s in self.english_only()
                               or any(line in self.english_only() for line in s.split("\n")))
            self.assertEqual(leftovers, [])
            tabs = list(self.app.signal_setup_panel.tabs._tab_dict)    # tab names are not widget text
            self.assertEqual(tabs, [COPY["vi"][k] for k in ("tab_amplitude", "tab_respiration", "tab_noise")])
            self.assertIn(COPY["vi"]["apply_signal"], shown)
        finally:
            self.app.close_signal_setup()

    def test_menus_map_back_to_model_identifiers(self):
        self.app.open_signal_setup()
        try:
            self.shown()
            panel = self.app.signal_setup_panel
            p = panel.engine.ppg_params
            self.assertEqual(panel._key("waveforms", panel.waveform_menu.get(), ("ppg", "sine", "triangle", "square")),
                             p.waveform)
            self.assertEqual(panel.polarity_menu.get(), COPY["vi"]["above"] if p.ac_polarity == 0 else COPY["vi"]["below"])
            self.assertEqual(panel._label("noises", p.noise_kind), panel.noise_menu.get())
        finally:
            self.app.close_signal_setup()

    def test_switching_language_with_the_window_open_rebuilds_it(self):
        self.app.open_signal_setup()
        try:
            self.app.set_language("en")
            self.app.update()
            self.assertIn(COPY["en"]["apply_signal"], self.shown())
            self.app.set_language("vi")
            self.app.update()
            self.assertIn(COPY["vi"]["apply_signal"], self.shown())
        finally:
            self.app.close_signal_setup()
