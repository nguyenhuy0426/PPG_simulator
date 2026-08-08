"""
Theoretical driver tests — single-fault behaviour of the current sink (Stage 1
item 16).

Covers the seven required fault conditions: open LED, shorted LED, open
R_sense, shorted R_sense, broken feedback, reversed transistor, reversed LED.

Every number here is a CALCULATION from datasheet limits and the candidate
component values. Nothing has been provoked or measured on hardware; the fault
signatures are predictions for the bring-up procedure, not observations.

Run: python3 -m unittest tests.test_led_driver_faults
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from led_driver import faults
from led_driver.params import IR_CHANNEL_5V, RED_CHANNEL_5V

MA = 1e-3
MW = 1e-3

# Shared by several faults: the op-amp output ceiling (5.00 - 1.5 = 3.50 V)
# minus V_BE(on) 0.70 V leaves 2.80 V to push current through R_B + R_sense.
V_DRIVE_MAX = 2.80


class TestOpenLed(unittest.TestCase):
    """Collector path broken: only the base path B->E->R_sense can conduct."""

    def test_red_regulates_only_up_to_2_55_ma_through_the_base_path(self):
        f = faults.open_led(RED_CHANNEL_5V)
        self.assertAlmostEqual(f.max_base_path_current_a / MA,
                               V_DRIVE_MAX / 1100.0 / MA, places=4)
        self.assertAlmostEqual(f.max_base_path_current_a / MA, 2.5455, places=3)

    def test_ir_regulates_only_up_to_2_59_ma_through_the_base_path(self):
        f = faults.open_led(IR_CHANNEL_5V)
        self.assertAlmostEqual(f.max_base_path_current_a / MA, 2.5878, places=3)

    def test_sense_voltage_clamps_far_below_full_scale_command(self):
        for ch, clamp in ((RED_CHANNEL_5V, 0.25455), (IR_CHANNEL_5V, 0.21220)):
            with self.subTest(channel=ch.name):
                f = faults.open_led(ch)
                self.assertAlmostEqual(f.sense_clamp_v, clamp, places=4)
                self.assertLess(f.sense_clamp_v, 1.640 / 4)

    def test_no_led_current_and_opamp_saturates_high(self):
        f = faults.open_led(RED_CHANNEL_5V)
        self.assertEqual(f.led_current_a, 0.0)
        self.assertTrue(f.opamp_saturates_high)
        self.assertFalse(f.destructive)

    def test_base_path_current_is_within_transistor_base_rating(self):
        # 2SC1815 I_B(abs max) = 50 mA; the fault pushes < 3 mA through B-E.
        f = faults.open_led(IR_CHANNEL_5V)
        self.assertLess(f.max_base_path_current_a, 0.050)


class TestShortedLed(unittest.TestCase):
    """LED failed short: regulation survives, transistor absorbs V_F."""

    def test_regulation_is_unaffected(self):
        f = faults.shorted_led(RED_CHANNEL_5V, i_led_a=16.40 * MA)
        self.assertTrue(f.regulation_intact)
        self.assertFalse(f.destructive)

    def test_red_transistor_vce_rises_to_3_36_v(self):
        f = faults.shorted_led(RED_CHANNEL_5V, i_led_a=16.40 * MA)
        self.assertAlmostEqual(f.vce_v, 5.00 - 1.640, places=3)

    def test_red_transistor_dissipation_rises_to_55_mw(self):
        f = faults.shorted_led(RED_CHANNEL_5V, i_led_a=16.40 * MA)
        self.assertAlmostEqual(f.transistor_dissipation_w / MW, 55.104, places=2)

    def test_ir_transistor_dissipation_rises_to_67_mw_still_under_rating(self):
        f = faults.shorted_led(IR_CHANNEL_5V, i_led_a=20.00 * MA)
        self.assertAlmostEqual(f.transistor_dissipation_w / MW, 67.200, places=2)
        self.assertLess(f.transistor_dissipation_w,
                        IR_CHANNEL_5V.transistor.pc_max_w)


class TestOpenRsense(unittest.TestCase):
    """Sense resistor open: no current path at all, loop latches off."""

    def test_led_current_is_zero_and_fault_is_safe(self):
        for ch in (RED_CHANNEL_5V, IR_CHANNEL_5V):
            with self.subTest(channel=ch.name):
                f = faults.open_rsense(ch)
                self.assertEqual(f.led_current_a, 0.0)
                self.assertFalse(f.destructive)

    def test_sense_node_is_flagged_indeterminate_not_given_a_number(self):
        f = faults.open_rsense(RED_CHANNEL_5V)
        self.assertIsNone(f.sense_node_v)
        self.assertIn("INDETERMINATE", f.sense_node_state)


class TestShortedRsense(unittest.TestCase):
    """Sense resistor short: feedback reads zero, drive slams to maximum.

    This is the destructive single fault of this topology.
    """

    def test_base_drive_slams_to_2_8_ma(self):
        f = faults.shorted_rsense(RED_CHANNEL_5V)
        self.assertAlmostEqual(f.base_drive_a / MA, 2.800, places=3)

    def test_minimum_gain_current_bound_is_196_ma(self):
        # hFE(abs min) = 70: even the worst transistor tries >= 196 mA.
        f = faults.shorted_rsense(RED_CHANNEL_5V)
        self.assertAlmostEqual(f.min_gain_current_bound_a / MA, 196.0, places=1)

    def test_fault_exceeds_led_and_transistor_ratings_and_is_destructive(self):
        for ch in (RED_CHANNEL_5V, IR_CHANNEL_5V):
            with self.subTest(channel=ch.name):
                f = faults.shorted_rsense(ch)
                self.assertGreater(f.min_gain_current_bound_a,
                                   ch.led.if_max_continuous_a)
                self.assertGreater(f.min_gain_current_bound_a,
                                   ch.transistor.ic_max_a)
                self.assertTrue(f.destructive)


class TestBrokenFeedback(unittest.TestCase):
    """Feedback wire open: output state indeterminate; bound the worst case."""

    def test_output_state_is_indeterminate(self):
        f = faults.broken_feedback(RED_CHANNEL_5V)
        self.assertIn("INDETERMINATE", f.output_state)

    def test_red_worst_case_current_bound_is_28_ma_and_over_led_abs_max(self):
        # Output saturated high, hFE -> infinity: I <= 2.80 V / R_sense.
        f = faults.broken_feedback(RED_CHANNEL_5V)
        self.assertAlmostEqual(f.worst_case_current_bound_a / MA, 28.00,
                               places=2)
        self.assertTrue(f.exceeds_led_abs_max)

    def test_ir_worst_case_current_bound_is_34_ma_but_within_led_abs_max(self):
        f = faults.broken_feedback(IR_CHANNEL_5V)
        self.assertAlmostEqual(f.worst_case_current_bound_a / MA, 34.146,
                               places=2)
        self.assertFalse(f.exceeds_led_abs_max)


class TestReversedTransistor(unittest.TestCase):
    """C and E swapped: reverse-active operation, E-B junction stressed."""

    def test_eb_reverse_stress_stays_under_the_5_v_vebo_rating(self):
        for ch, veb in ((RED_CHANNEL_5V, 3.20), (IR_CHANNEL_5V, 3.70)):
            with self.subTest(channel=ch.name):
                f = faults.reversed_transistor(ch)
                self.assertAlmostEqual(f.veb_reverse_bound_v, veb, places=2)
                self.assertLess(f.veb_reverse_bound_v, f.vebo_abs_max_v)

    def test_reverse_gain_is_unknown_not_a_number(self):
        f = faults.reversed_transistor(RED_CHANNEL_5V)
        self.assertIsNone(f.reverse_hfe)
        self.assertIn("UNKNOWN", f.regulation_state)


class TestReversedLed(unittest.TestCase):
    """LED installed backwards: blocks like the open-LED case, plus reverse
    voltage stress on the LED itself."""

    def test_behaves_like_open_led_for_the_base_path(self):
        f = faults.reversed_led(RED_CHANNEL_5V)
        o = faults.open_led(RED_CHANNEL_5V)
        self.assertAlmostEqual(f.max_base_path_current_a,
                               o.max_base_path_current_a, places=6)

    def test_ir_reverse_voltage_stays_just_under_the_5_v_abs_max_at_5_00_v(self):
        # SIR234 V_R(abs max) = 5 V; predicted reverse ~= 4.79 V at 5.00 V rail.
        f = faults.reversed_led(IR_CHANNEL_5V)
        self.assertAlmostEqual(f.led_reverse_v, 4.7878, places=3)
        self.assertEqual(f.reverse_abs_max_v, 5.0)
        self.assertTrue(f.within_reverse_rating)

    def test_ir_reverse_voltage_exceeds_abs_max_at_a_5_25_v_rail(self):
        f = faults.reversed_led(IR_CHANNEL_5V, rail_v=5.25)
        self.assertGreater(f.led_reverse_v, f.reverse_abs_max_v)
        self.assertFalse(f.within_reverse_rating)

    def test_red_reverse_destruction_threshold_is_unknown(self):
        # The Red datasheet gives only a leakage characterisation (10 uA at
        # V_R = 5 V), not an absolute-maximum reverse voltage.
        f = faults.reversed_led(RED_CHANNEL_5V)
        self.assertIsNone(f.reverse_abs_max_v)
        self.assertIsNone(f.within_reverse_rating)


class TestFaultSummary(unittest.TestCase):
    def test_all_seven_faults_are_enumerated_per_channel(self):
        for ch in (RED_CHANNEL_5V, IR_CHANNEL_5V):
            with self.subTest(channel=ch.name):
                table = faults.all_faults(ch)
                self.assertEqual(
                    set(table),
                    {"open_led", "shorted_led", "open_rsense",
                     "shorted_rsense", "broken_feedback",
                     "reversed_transistor", "reversed_led"})

    def test_the_only_destructive_single_fault_is_the_shorted_rsense(self):
        table = faults.all_faults(RED_CHANNEL_5V)
        destructive = {name for name, f in table.items() if f.destructive}
        self.assertEqual(destructive, {"shorted_rsense"})


if __name__ == "__main__":
    unittest.main()
