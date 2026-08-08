"""
Theoretical driver tests — error budget and the explicit corrections (Stage 1).

Covers task area 7 (LM358 offset and divider-tolerance errors) plus every
correction the task requires be made to the earlier analysis:

  * R_BE compared at 10 kohm, 100 kohm and DNP, including low-current
    distortion and turn-off behaviour, and NOT finalised without measurement.
  * C2 compensation marked DNP / MEASUREMENT-REQUIRED.
  * No claim that a 1 kHz update rate aliases exactly to DC under Linux.
  * Constant hFE gain approximately cancels in AC/DC; nonlinear and
    temperature-dependent hFE variation does not and must be measured.

Cross-checked against the shipped calibration.py so the theory module and the
production math agree.

Run: python3 -m unittest tests.test_led_driver_error_budget
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calibration
from led_driver import error_budget as eb
from led_driver.params import IR_CHANNEL_5V, RED_CHANNEL_5V

MA = 1e-3
UA = 1e-6
V_CMD_FULL_SCALE = 1.640
I_RED_FS = 16.40 * MA
I_IR_FS = 20.00 * MA
I_RED_OPERATING = 7.50 * MA


class TestInputReferredOffset(unittest.TestCase):
    """Task area 7 — V_OS plus I_B across the divider's Thevenin impedance."""

    def test_offset_at_25c_is_8_25_mv(self):
        v = eb.input_referred_offset_v(RED_CHANNEL_5V, over_temperature=False)
        self.assertAlmostEqual(v * 1e3, 8.25, places=9)

    def test_offset_over_temperature_is_11_5_mv(self):
        v = eb.input_referred_offset_v(RED_CHANNEL_5V, over_temperature=True)
        self.assertAlmostEqual(v * 1e3, 11.50, places=9)

    def test_bias_current_term_uses_the_5k_thevenin_impedance(self):
        vos_only = RED_CHANNEL_5V.opamp.vos_max_v
        total = eb.input_referred_offset_v(RED_CHANNEL_5V, over_temperature=False)
        self.assertAlmostEqual((total - vos_only) * 1e3, 1.25, places=9)

    def test_offset_is_the_same_for_both_channels_in_volts(self):
        self.assertAlmostEqual(
            eb.input_referred_offset_v(RED_CHANNEL_5V),
            eb.input_referred_offset_v(IR_CHANNEL_5V), places=15)


class TestOffsetCurrentError(unittest.TestCase):
    """Task area 7 — the offset becomes a per-channel current error."""

    def test_red_offset_current_is_82_5_ua(self):
        i = eb.offset_current_error_a(RED_CHANNEL_5V, over_temperature=False)
        self.assertAlmostEqual(i / UA, 82.50, places=6)

    def test_ir_offset_current_is_100_6_ua(self):
        i = eb.offset_current_error_a(IR_CHANNEL_5V, over_temperature=False)
        self.assertAlmostEqual(i / UA, 100.6098, places=4)

    def test_offset_is_0_50_percent_of_full_scale_on_both_channels(self):
        for ch, i_fs in ((RED_CHANNEL_5V, I_RED_FS), (IR_CHANNEL_5V, I_IR_FS)):
            with self.subTest(channel=ch.name):
                frac = eb.offset_error_fraction(ch, i_fs, over_temperature=False)
                self.assertAlmostEqual(frac * 100.0, 0.5030, places=4)

    def test_offset_is_1_10_percent_at_the_7_5ma_operating_point(self):
        frac = eb.offset_error_fraction(RED_CHANNEL_5V, I_RED_OPERATING,
                                        over_temperature=False)
        self.assertAlmostEqual(frac * 100.0, 1.1000, places=4)

    def test_offset_gets_worse_at_lower_operating_current(self):
        low = eb.offset_error_fraction(RED_CHANNEL_5V, 2.0 * MA)
        high = eb.offset_error_fraction(RED_CHANNEL_5V, I_RED_FS)
        self.assertGreater(low, high)


class TestToleranceGainErrors(unittest.TestCase):
    """Task area 7 — divider and sense-resistor tolerance."""

    def test_divider_ratio_extremes_are_plus_minus_1_percent(self):
        lo, hi = eb.divider_ratio_extremes(RED_CHANNEL_5V.divider)
        self.assertAlmostEqual(lo, 0.495, places=12)
        self.assertAlmostEqual(hi, 0.505, places=12)

    def test_divider_gain_error_is_plus_minus_1_percent(self):
        lo, hi = eb.divider_gain_error_fraction(RED_CHANNEL_5V.divider)
        self.assertAlmostEqual(lo * 100.0, -1.0, places=9)
        self.assertAlmostEqual(hi * 100.0, +1.0, places=9)

    def test_combined_gain_error_is_asymmetric(self):
        """(1+t)/(1-t) is not the mirror of (1-t)/(1+t)."""
        lo, hi = eb.total_gain_error_fraction(RED_CHANNEL_5V)
        self.assertAlmostEqual(hi * 100.0, 2.0202, places=4)
        self.assertAlmostEqual(lo * 100.0, -1.9802, places=4)

    def test_gain_error_is_independent_of_operating_point(self):
        self.assertEqual(eb.total_gain_error_fraction(RED_CHANNEL_5V),
                         eb.total_gain_error_fraction(IR_CHANNEL_5V))


class TestGainCancelsButOffsetDoesNot(unittest.TestCase):
    """The reason the error budget splits into gain and offset at all."""

    def test_a_pure_gain_error_leaves_perfusion_index_unchanged(self):
        ac, dc = 0.075 * MA, 7.50 * MA
        nominal = calibration.perfusion_index_from_ac_dc(ac, dc)
        scaled = calibration.perfusion_index_from_ac_dc(1.02 * ac, 1.02 * dc)
        self.assertAlmostEqual(nominal, scaled, places=12)

    def test_a_dc_offset_error_changes_perfusion_index(self):
        ac, dc = 0.075 * MA, 7.50 * MA
        nominal = calibration.perfusion_index_from_ac_dc(ac, dc)
        offset = calibration.perfusion_index_from_ac_dc(ac, dc - 82.5 * UA)
        self.assertNotAlmostEqual(nominal, offset, places=6)
        self.assertGreater(offset, nominal)

    def test_a_pure_gain_error_leaves_ratio_of_ratios_unchanged(self):
        r = calibration.ratio_of_ratios(0.075 * MA, 7.5 * MA, 0.060 * MA, 9.0 * MA)
        r_scaled = calibration.ratio_of_ratios(
            1.02 * 0.075 * MA, 1.02 * 7.5 * MA, 0.98 * 0.060 * MA, 0.98 * 9.0 * MA)
        self.assertAlmostEqual(r, r_scaled, places=12)

    def test_the_module_classifies_each_error_source(self):
        classes = eb.error_classification()
        self.assertEqual(classes["divider_tolerance"], "gain")
        self.assertEqual(classes["rsense_tolerance"], "gain")
        self.assertEqual(classes["alpha_hfe_constant"], "gain")
        self.assertEqual(classes["opamp_offset"], "offset")
        self.assertEqual(classes["rbe_bleed"], "offset")


class TestHfeCancellation(unittest.TestCase):
    """Correction: constant hFE cancels in AC/DC; varying hFE does not."""

    AC_FRACTION = 0.01

    def _ratio(self, hfe_model):
        dc_cmd = I_RED_OPERATING * RED_CHANNEL_5V.rsense_ohm
        ac_cmd = dc_cmd * self.AC_FRACTION
        return eb.ac_dc_ratio_from_command(
            dc_cmd, ac_cmd, RED_CHANNEL_5V, hfe_model=hfe_model, rbe_ohm=None)

    def test_constant_hfe_cancels_exactly(self):
        for hfe in (70.0, 200.0, 400.0, 700.0):
            with self.subTest(hfe=hfe):
                self.assertAlmostEqual(self._ratio(hfe), self.AC_FRACTION,
                                       places=12)

    def test_ideal_alpha_one_also_cancels(self):
        self.assertAlmostEqual(self._ratio(None), self.AC_FRACTION, places=12)

    def test_current_dependent_hfe_does_not_cancel(self):
        ratio = self._ratio(lambda ic: 200.0 + 20_000.0 * ic)
        deviation = abs(ratio / self.AC_FRACTION - 1.0)
        self.assertGreater(deviation, 1e-3)
        self.assertLess(deviation, 1e-2)

    def test_hfe_variation_is_flagged_as_measurement_required(self):
        self.assertIn("MEASUREMENT-REQUIRED", eb.HFE_CANCELLATION_CAVEAT)
        self.assertIn("temperature", eb.HFE_CANCELLATION_CAVEAT.lower())


class TestRbeComparison(unittest.TestCase):
    """Correction: compare 10k, 100k and DNP. Do not finalise without measurement."""

    def setUp(self):
        self.options = {
            o.rbe_ohm: o for o in eb.rbe_comparison(
                RED_CHANNEL_5V, I_RED_OPERATING, hfe=300.0, vbe_on_v=0.70)
        }

    def test_all_three_options_are_compared(self):
        self.assertEqual(set(self.options), {10_000.0, 100_000.0, None})

    def test_10k_bleeds_70ua(self):
        self.assertAlmostEqual(self.options[10_000.0].bleed_a / UA, 70.0, places=9)

    def test_100k_bleeds_7ua(self):
        self.assertAlmostEqual(self.options[100_000.0].bleed_a / UA, 7.0, places=9)

    def test_dnp_bleeds_nothing(self):
        self.assertEqual(self.options[None].bleed_a, 0.0)

    def test_10k_dead_zone_is_7mv_of_command_about_17_dac_codes(self):
        o = self.options[10_000.0]
        self.assertAlmostEqual(o.dead_zone_command_v * 1e3, 7.0, places=9)
        self.assertEqual(o.dead_zone_codes, 17)

    def test_100k_dead_zone_is_one_code(self):
        self.assertEqual(self.options[100_000.0].dead_zone_codes, 1)

    def test_dnp_has_no_dead_zone(self):
        self.assertEqual(self.options[None].dead_zone_codes, 0)

    def test_10k_shifts_perfusion_index_by_0_94_percent(self):
        self.assertAlmostEqual(
            self.options[10_000.0].pi_error_fraction * 100.0, 0.9421, places=4)

    def test_100k_shifts_perfusion_index_by_0_09_percent(self):
        self.assertAlmostEqual(
            self.options[100_000.0].pi_error_fraction * 100.0, 0.0934, places=4)

    def test_dnp_shifts_perfusion_index_not_at_all(self):
        self.assertEqual(self.options[None].pi_error_fraction, 0.0)

    def test_low_current_distortion_from_vbe_modulation_is_quantified(self):
        """R_BE is not a purely constant bleed: V_BE moves with the AC swing."""
        f = eb.rbe_ac_modulation_fraction(
            RED_CHANNEL_5V, I_RED_OPERATING, ac_fraction=0.01, rbe_ohm=10_000.0)
        self.assertAlmostEqual(f * 100.0, 0.0343, places=4)

    def test_ac_modulation_is_ten_times_smaller_at_100k(self):
        f10 = eb.rbe_ac_modulation_fraction(
            RED_CHANNEL_5V, I_RED_OPERATING, 0.01, 10_000.0)
        f100 = eb.rbe_ac_modulation_fraction(
            RED_CHANNEL_5V, I_RED_OPERATING, 0.01, 100_000.0)
        self.assertAlmostEqual(f10 / f100, 10.0, places=9)

    def test_turn_off_behaviour_without_rbe_depends_on_the_opamp_sink(self):
        o = self.options[None]
        self.assertIn("12", o.turn_off_note)
        self.assertIn("sink", o.turn_off_note.lower())

    def test_rbe_is_not_finalised(self):
        self.assertIsNone(eb.RBE_DECISION.value)
        self.assertEqual(eb.RBE_DECISION.evidence, "MEASUREMENT-REQUIRED")
        self.assertIn("NOT-FINALISED", eb.RBE_DECISION.status)

    def test_asking_for_the_rbe_value_raises(self):
        with self.assertRaises(eb.MeasurementRequiredError):
            eb.RBE_DECISION.require_value()


class TestC2Compensation(unittest.TestCase):
    """Correction: C2 stays DNP / MEASUREMENT-REQUIRED until scoped."""

    def test_c2_is_dnp(self):
        self.assertEqual(eb.C2_COMPENSATION.status, "DNP")

    def test_c2_has_no_value(self):
        self.assertIsNone(eb.C2_COMPENSATION.value)

    def test_c2_is_measurement_required(self):
        self.assertEqual(eb.C2_COMPENSATION.evidence, "MEASUREMENT-REQUIRED")

    def test_asking_for_the_c2_value_raises(self):
        with self.assertRaises(eb.MeasurementRequiredError):
            eb.C2_COMPENSATION.require_value()

    def test_c2_rationale_names_the_missing_evidence(self):
        text = eb.C2_COMPENSATION.rationale.lower()
        self.assertTrue("scope" in text or "loop model" in text)


class TestAliasing(unittest.TestCase):
    """Correction: do not claim 1 kHz aliases exactly to DC under Linux."""

    def test_nominal_alias_of_1khz_against_100hz_is_zero(self):
        self.assertAlmostEqual(eb.alias_frequency_hz(1000.0, 100.0), 0.0, places=12)

    def test_nominal_alias_is_only_true_for_perfect_clocks(self):
        self.assertAlmostEqual(eb.alias_frequency_hz(1000.5, 100.0), 0.5, places=12)

    def test_100ppm_clock_error_spreads_the_alias_to_0_2hz(self):
        lo, hi = eb.alias_band_hz(1000.0, 100.0, tolerance_ppm=100.0)
        self.assertAlmostEqual(lo, 0.0, places=12)
        self.assertAlmostEqual(hi, 0.2, places=9)

    def test_500ppm_clock_error_puts_the_alias_inside_the_heart_rate_band(self):
        lo, hi = eb.alias_band_hz(1000.0, 100.0, tolerance_ppm=500.0)
        self.assertAlmostEqual(hi, 1.0, places=9)
        self.assertTrue(eb.overlaps_band((lo, hi), eb.PPG_HR_BAND_HZ))

    def test_100ppm_alias_still_corrupts_the_dc_baseline_region(self):
        band = eb.alias_band_hz(1000.0, 100.0, tolerance_ppm=100.0)
        self.assertFalse(eb.overlaps_band(band, eb.PPG_HR_BAND_HZ))
        self.assertTrue(eb.overlaps_band(band, eb.PPG_BASELINE_BAND_HZ))

    def test_zero_tolerance_collapses_the_band_to_a_point(self):
        lo, hi = eb.alias_band_hz(1000.0, 100.0, tolerance_ppm=0.0)
        self.assertEqual((lo, hi), (0.0, 0.0))

    def test_the_caveat_refuses_the_exact_dc_claim(self):
        text = eb.ALIASING_CAVEAT.lower()
        self.assertNotIn("exactly dc", text)
        self.assertNotIn("exactly to dc", text)
        for word in ("phase", "drift", "jitter"):
            with self.subTest(word=word):
                self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
