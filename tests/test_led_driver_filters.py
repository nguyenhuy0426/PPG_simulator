"""
Theoretical driver tests — input RC filter options (Stage 1, C1 selection).

The filter is the capacitor C1 from the divider midpoint to ground. The source
resistance it sees is the divider Thevenin resistance, 10k || 10k = 5 kohm.
Options under evaluation: DNP, 10 nF, 100 nF, 220 nF.

These are CALCULATIONS of the option space, not a selection. Per the task
instruction, the input filter must NOT be finalised from theory alone; the
final choice is MEASUREMENT-REQUIRED (scope on TP_CMD_*).

Run: python3 -m unittest tests.test_led_driver_filters
"""

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from led_driver import filters
from led_driver.params import RED_CHANNEL_5V

NF = 1e-9
MS = 1e-3
R_THEV = 5000.0


class TestCutoffFrequencies(unittest.TestCase):
    def test_10nf_cuts_off_at_3183_hz(self):
        self.assertAlmostEqual(filters.cutoff_hz(10 * NF), 3183.099, places=2)

    def test_100nf_cuts_off_at_318_hz(self):
        self.assertAlmostEqual(filters.cutoff_hz(100 * NF), 318.310, places=2)

    def test_220nf_cuts_off_at_145_hz(self):
        self.assertAlmostEqual(filters.cutoff_hz(220 * NF), 144.686, places=2)

    def test_dnp_has_no_cutoff(self):
        self.assertEqual(filters.cutoff_hz(None), math.inf)

    def test_source_resistance_is_the_divider_thevenin_resistance(self):
        self.assertAlmostEqual(RED_CHANNEL_5V.divider.thevenin_ohm, R_THEV)


class TestAttenuationAtKeyFrequencies(unittest.TestCase):
    """1 kHz = DAC update stepping; 100 Hz = model rate; 10 Hz = PPG band."""

    def test_magnitude_at_1_khz(self):
        self.assertAlmostEqual(filters.magnitude_at(1000.0, 10 * NF),
                               0.95403, places=4)
        self.assertAlmostEqual(filters.magnitude_at(1000.0, 100 * NF),
                               0.30331, places=4)
        self.assertAlmostEqual(filters.magnitude_at(1000.0, 220 * NF),
                               0.14320, places=4)

    def test_magnitude_at_100_hz(self):
        self.assertAlmostEqual(filters.magnitude_at(100.0, 100 * NF),
                               0.95403, places=4)
        self.assertAlmostEqual(filters.magnitude_at(100.0, 220 * NF),
                               0.82263, places=4)

    def test_ppg_band_is_essentially_untouched_by_every_option(self):
        for c in (None, 10 * NF, 100 * NF, 220 * NF):
            with self.subTest(c=c):
                self.assertGreater(filters.magnitude_at(10.0, c), 0.9976)

    def test_dnp_passes_everything(self):
        self.assertEqual(filters.magnitude_at(1000.0, None), 1.0)


class TestSettling(unittest.TestCase):
    def test_5_tau_settling_times(self):
        self.assertAlmostEqual(filters.settle_5tau_s(10 * NF) / MS, 0.250)
        self.assertAlmostEqual(filters.settle_5tau_s(100 * NF) / MS, 2.500)
        self.assertAlmostEqual(filters.settle_5tau_s(220 * NF) / MS, 5.500)

    def test_only_the_10nf_option_settles_within_one_dac_update(self):
        # 100 nF and 220 nF deliberately smooth ACROSS 1 ms updates; that is
        # the intent, but it must be a documented property, not a surprise.
        self.assertLess(filters.settle_5tau_s(10 * NF), 1e-3)
        self.assertGreater(filters.settle_5tau_s(100 * NF), 1e-3)
        self.assertGreater(filters.settle_5tau_s(220 * NF), 1e-3)

    def test_every_option_settles_within_one_model_period(self):
        for c in (10 * NF, 100 * NF, 220 * NF):
            with self.subTest(c=c):
                self.assertLess(filters.settle_5tau_s(c), 10e-3)


class TestChannelMatching(unittest.TestCase):
    """C1 tolerance creates a per-channel gain difference at 100 Hz; the two
    channels must be fitted with the same option and tolerance."""

    def test_10_percent_tolerance_on_100nf_gives_about_1_7_percent_mismatch(self):
        d = filters.channel_gain_mismatch(100 * NF, tol_frac=0.10, f_hz=100.0)
        self.assertGreater(d, 0.010)
        self.assertLess(d, 0.030)

    def test_dnp_has_no_mismatch(self):
        self.assertEqual(
            filters.channel_gain_mismatch(None, tol_frac=0.10, f_hz=100.0),
            0.0)


class TestOptionTable(unittest.TestCase):
    def test_table_covers_all_four_options(self):
        table = filters.option_table()
        self.assertEqual(len(table), 4)
        self.assertIsNone(table[0].c_farad)
        for row, expected in zip(table[1:], (10 * NF, 100 * NF, 220 * NF)):
            self.assertAlmostEqual(row.c_farad, expected, places=15)

    def test_selection_is_not_finalised_from_theory(self):
        self.assertIn("MEASUREMENT-REQUIRED", filters.SELECTION_STATUS)


if __name__ == "__main__":
    unittest.main()
