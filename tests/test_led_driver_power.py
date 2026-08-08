"""
Theoretical driver tests — dissipation, rail budget and LED limits (Stage 1).

Covers task areas 5 and 10, plus the corrected rail-current budget:
  5.  R_sense, LED and transistor dissipation.
  10. Current limits for the actual Red and IR LEDs.

Correction under test: the total rail budget is 37.60 mA, not 37.3 mA, and it
must be derived from a KCL that accounts for base current and the R_BE bleed
rather than from LED current alone.

Run: python3 -m unittest tests.test_led_driver_power
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from led_driver import power
from led_driver.params import CHANNELS_5V, IR_CHANNEL_5V, RED_CHANNEL_5V

MA = 1e-3
MW = 1e-3
V_CMD_FULL_SCALE = 1.640
I_RED_FS = 16.40 * MA
I_IR_FS = 20.00 * MA


class TestSenseResistorDissipation(unittest.TestCase):
    """Task area 5."""

    def test_red_rsense_dissipates_26_9_mw_at_full_scale(self):
        p = power.rsense_dissipation_w(I_RED_FS, RED_CHANNEL_5V)
        self.assertAlmostEqual(p / MW, 26.896, places=3)

    def test_ir_rsense_dissipates_32_8_mw_at_full_scale(self):
        p = power.rsense_dissipation_w(I_IR_FS, IR_CHANNEL_5V)
        self.assertAlmostEqual(p / MW, 32.800, places=3)

    def test_both_sense_resistors_fit_a_common_0805_or_0603_part(self):
        """Sanity: both are far under a 100 mW small-chip rating."""
        for ch, i in ((RED_CHANNEL_5V, I_RED_FS), (IR_CHANNEL_5V, I_IR_FS)):
            with self.subTest(channel=ch.name):
                self.assertLess(power.rsense_dissipation_w(i, ch), 0.100)


class TestLedDissipation(unittest.TestCase):
    """Task areas 5 and 10."""

    def test_red_led_dissipates_36_1_mw_at_worst_case_vf(self):
        p = power.led_dissipation_w(I_RED_FS, RED_CHANNEL_5V, vf_selector="max")
        self.assertAlmostEqual(p / MW, 36.080, places=3)

    def test_ir_led_dissipates_33_0_mw_at_worst_case_vf(self):
        p = power.led_dissipation_w(I_IR_FS, IR_CHANNEL_5V, vf_selector="max")
        self.assertAlmostEqual(p / MW, 33.000, places=3)

    def test_red_led_uses_about_34_percent_of_its_power_rating(self):
        frac = power.led_dissipation_fraction(I_RED_FS, RED_CHANNEL_5V,
                                              vf_selector="max")
        self.assertAlmostEqual(frac * 100.0, 34.362, places=3)

    def test_ir_led_uses_22_percent_of_its_power_rating(self):
        frac = power.led_dissipation_fraction(I_IR_FS, IR_CHANNEL_5V,
                                              vf_selector="max")
        self.assertAlmostEqual(frac * 100.0, 22.000, places=3)


class TestTransistorDissipation(unittest.TestCase):
    """Task area 5 — worst case is at MINIMUM V_F, not maximum."""

    def test_red_transistor_worst_case_is_25_6_mw(self):
        p = power.transistor_dissipation_w(I_RED_FS, RED_CHANNEL_5V,
                                           V_CMD_FULL_SCALE, vf_selector="min")
        self.assertAlmostEqual(p / MW, 25.584, places=3)

    def test_ir_transistor_worst_case_is_41_2_mw(self):
        p = power.transistor_dissipation_w(I_IR_FS, IR_CHANNEL_5V,
                                           V_CMD_FULL_SCALE, vf_selector="min")
        self.assertAlmostEqual(p / MW, 41.200, places=3)

    def test_minimum_vf_dissipates_more_than_maximum_vf(self):
        at_min = power.transistor_dissipation_w(
            I_RED_FS, RED_CHANNEL_5V, V_CMD_FULL_SCALE, vf_selector="min")
        at_max = power.transistor_dissipation_w(
            I_RED_FS, RED_CHANNEL_5V, V_CMD_FULL_SCALE, vf_selector="max")
        self.assertGreater(at_min, at_max)

    def test_both_transistors_are_far_inside_the_400mw_rating(self):
        for ch, i in ((RED_CHANNEL_5V, I_RED_FS), (IR_CHANNEL_5V, I_IR_FS)):
            with self.subTest(channel=ch.name):
                p = power.transistor_dissipation_w(i, ch, V_CMD_FULL_SCALE,
                                                   vf_selector="min")
                self.assertLess(p, 0.15 * ch.transistor.pc_max_w)

    def test_ir_transistor_figure_rests_on_a_non_datasheet_vf_minimum(self):
        """The IR datasheet has no V_F minimum; a lower real V_F raises P_C."""
        self.assertFalse(IR_CHANNEL_5V.led.vf_min_is_datasheet_minimum)
        self.assertTrue(RED_CHANNEL_5V.led.vf_min_is_datasheet_minimum)


class TestLedCurrentLimits(unittest.TestCase):
    """Task area 10 — the actual Red and IR parts, not a generic LED."""

    def test_red_absolute_maximum_is_20_ma(self):
        self.assertAlmostEqual(RED_CHANNEL_5V.led.if_max_continuous_a / MA, 20.0)

    def test_ir_absolute_maximum_is_100_ma(self):
        self.assertAlmostEqual(IR_CHANNEL_5V.led.if_max_continuous_a / MA, 100.0)

    def test_red_full_scale_uses_82_percent_of_its_absolute_maximum(self):
        frac = power.current_limit_fraction(I_RED_FS, RED_CHANNEL_5V)
        self.assertAlmostEqual(frac * 100.0, 82.0, places=6)

    def test_ir_full_scale_uses_20_percent_of_its_absolute_maximum(self):
        frac = power.current_limit_fraction(I_IR_FS, IR_CHANNEL_5V)
        self.assertAlmostEqual(frac * 100.0, 20.0, places=6)

    def test_red_full_scale_sits_just_below_the_suggested_window(self):
        """Datasheet 'suggestion using current' for the Red part is 16-18 mA."""
        low, high = RED_CHANNEL_5V.led.if_suggested_a
        self.assertLessEqual(low, I_RED_FS)
        self.assertLessEqual(I_RED_FS, high)

    def test_ir_part_publishes_no_suggested_window(self):
        self.assertIsNone(IR_CHANNEL_5V.led.if_suggested_a)

    def test_exceeding_the_red_absolute_maximum_raises(self):
        with self.assertRaises(power.CurrentLimitError):
            power.check_led_current_or_raise(21.0 * MA, RED_CHANNEL_5V)

    def test_ir_power_rating_binds_before_its_current_rating(self):
        """150 mW / 1.65 V = 90.9 mA, below the 100 mA absolute maximum I_F."""
        i_at_pd_limit = (IR_CHANNEL_5V.led.pd_max_w
                         / IR_CHANNEL_5V.led.vf_max_v)
        self.assertLess(i_at_pd_limit, IR_CHANNEL_5V.led.if_max_continuous_a)
        self.assertAlmostEqual(i_at_pd_limit / MA, 90.909, places=3)

    def test_exceeding_the_led_power_rating_raises_below_the_current_limit(self):
        """95 mA is inside I_F max but 157 mW is outside P_D max."""
        self.assertLess(95.0 * MA, IR_CHANNEL_5V.led.if_max_continuous_a)
        with self.assertRaises(power.CurrentLimitError) as ctx:
            power.check_led_current_or_raise(95.0 * MA, IR_CHANNEL_5V)
        self.assertIn("mW", str(ctx.exception))

    def test_full_scale_currents_do_not_raise(self):
        power.check_led_current_or_raise(I_RED_FS, RED_CHANNEL_5V)
        power.check_led_current_or_raise(I_IR_FS, IR_CHANNEL_5V)

    def test_the_error_names_the_led_and_the_limit(self):
        with self.assertRaises(power.CurrentLimitError) as ctx:
            power.check_led_current_or_raise(21.0 * MA, RED_CHANNEL_5V)
        self.assertIn("Red", str(ctx.exception))


class TestRailCurrentBudget(unittest.TestCase):
    """Corrected budget: 37.60 mA, derived from KCL, not from LED current alone."""

    def budget(self, **kw):
        return power.rail_current_budget(CHANNELS_5V, V_CMD_FULL_SCALE, **kw)

    def test_led_currents_alone_total_36_40_ma(self):
        b = self.budget(hfe=None, rbe_ohm=None)
        self.assertAlmostEqual(b["led_a"] / MA, 36.40, places=6)

    def test_opamp_quiescent_is_two_amplifiers_at_600ua(self):
        b = self.budget()
        self.assertAlmostEqual(b["opamp_quiescent_a"] / MA, 1.20, places=9)

    def test_total_rail_current_is_37_60_ma(self):
        b = self.budget()
        self.assertAlmostEqual(b["total_a"] / MA, 37.60, places=6)

    def test_total_is_not_the_previously_documented_37_3_ma(self):
        b = self.budget()
        self.assertNotAlmostEqual(b["total_a"] / MA, 37.3, places=2)

    def test_per_channel_rail_current_equals_the_sense_current_exactly(self):
        """KCL: I_C + I_B + I_RBE = I_E + I_RBE = I_sense, for any hFE, any R_BE."""
        for hfe in (70.0, 200.0, 400.0, 700.0):
            for rbe in (None, 10_000.0, 100_000.0):
                with self.subTest(hfe=hfe, rbe=rbe):
                    b = power.rail_current_budget(
                        CHANNELS_5V, V_CMD_FULL_SCALE, hfe=hfe, rbe_ohm=rbe)
                    for entry in b["per_channel"]:
                        self.assertAlmostEqual(
                            entry["rail_a"], entry["sense_a"], places=12)

    def test_total_is_invariant_to_hfe_and_rbe(self):
        totals = [
            power.rail_current_budget(
                CHANNELS_5V, V_CMD_FULL_SCALE, hfe=hfe, rbe_ohm=rbe)["total_a"]
            for hfe in (70.0, 200.0, 400.0, 700.0)
            for rbe in (None, 10_000.0, 100_000.0)
        ]
        # Exact in algebra; only floating-point summation order differs.
        self.assertLess(max(totals) - min(totals), 1e-15)

    def test_led_current_itself_is_not_invariant_to_hfe_and_rbe(self):
        ideal = power.rail_current_budget(
            CHANNELS_5V, V_CMD_FULL_SCALE, hfe=None, rbe_ohm=None)["led_a"]
        real = power.rail_current_budget(
            CHANNELS_5V, V_CMD_FULL_SCALE, hfe=70.0, rbe_ohm=10_000.0)["led_a"]
        self.assertLess(real, ideal)

    def test_budget_accounts_for_base_and_rbe_currents_separately(self):
        b = self.budget(hfe=70.0, rbe_ohm=10_000.0)
        self.assertGreater(b["base_a"], 0.0)
        self.assertAlmostEqual(b["rbe_a"] / MA, 0.140, places=6)
        self.assertAlmostEqual(
            (b["led_a"] + b["base_a"] + b["rbe_a"] + b["opamp_quiescent_a"]) / MA,
            37.60, places=6)


if __name__ == "__main__":
    unittest.main()
