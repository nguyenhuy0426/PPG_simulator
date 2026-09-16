import unittest

from ui.responsive import profile_for_screen


class TestResponsiveLayout(unittest.TestCase):
    def test_seven_inch_1024x600_is_compact_and_never_overflows(self):
        profile = profile_for_screen(1024, 600)
        self.assertTrue(profile.compact)
        self.assertEqual(profile.geometry, "1024x600+0+0")
        self.assertEqual(profile.minimum_size, (800, 480))
        self.assertLess(profile.widget_scale, 1.0)

    def test_common_laptop_resolution_uses_regular_layout(self):
        profile = profile_for_screen(1366, 768)
        self.assertFalse(profile.compact)
        self.assertFalse(profile.large)
        self.assertLessEqual(profile.widget_scale, 1.0)

    def test_full_hd_and_qhd_use_capped_large_layout(self):
        full_hd = profile_for_screen(1920, 1080)
        qhd = profile_for_screen(2560, 1440)
        self.assertTrue(full_hd.large)
        self.assertTrue(qhd.large)
        self.assertGreater(full_hd.widget_scale, 1.0)
        self.assertEqual(qhd.widget_scale, 1.5)

    def test_small_resolution_minimum_does_not_exceed_screen(self):
        profile = profile_for_screen(640, 400)
        self.assertEqual(profile.minimum_size, (640, 400))


if __name__ == "__main__":
    unittest.main()
