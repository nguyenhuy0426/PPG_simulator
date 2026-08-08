"""
Theoretical driver tests — compliance and headroom (Stage 1).

Covers task areas 3, 4, 8 and 9:
  3. LM358P input common-mode and output headroom.
  4. LED / transistor compliance voltage.
  8. Supply variation while the loop remains in compliance.
  9. Explicit failure when compliance is insufficient.

Pure calculation against the 5 V design hypothesis. No hardware is touched and
no result here is evidence about a physical board.

Run: python3 -m unittest tests.test_led_driver_compliance
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from led_driver import compliance
from led_driver.params import IR_CHANNEL_5V, LM358P, RED_CHANNEL_5V

MA = 1e-3
V_CMD_FULL_SCALE = 1.640  # 3.28 V DAC through the 10k/10k divider


class TestOpAmpInputCommonMode(unittest.TestCase):
    """Task area 3 — the LM358 + input must stay inside its common-mode range."""

    def test_common_mode_ceiling_at_25c_is_3v50(self):
        self.assertAlmostEqual(LM358P.cm_max_25c_v, 3.50, places=9)

    def test_common_mode_ceiling_over_temperature_is_3v00(self):
        self.assertAlmostEqual(LM358P.cm_max_over_temp_v, 3.00, places=9)

    def test_full_scale_command_is_inside_common_mode_range_over_temperature(self):
        r = compliance.input_common_mode(
            V_CMD_FULL_SCALE, RED_CHANNEL_5V, over_temperature=True)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.margin_v, 1.36, places=9)

    def test_full_scale_command_margin_at_25c_is_1v86(self):
        r = compliance.input_common_mode(
            V_CMD_FULL_SCALE, RED_CHANNEL_5V, over_temperature=False)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.margin_v, 1.86, places=9)

    def test_undivided_dac_output_fails_common_mode_over_temperature(self):
        """This is why the 10k/10k attenuator exists at all."""
        r = compliance.input_common_mode(3.28, RED_CHANNEL_5V, over_temperature=True)
        self.assertFalse(r.ok)
        self.assertLess(r.margin_v, 0.0)

    def test_undivided_dac_output_passes_only_at_25c(self):
        r = compliance.input_common_mode(3.28, RED_CHANNEL_5V, over_temperature=False)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.margin_v, 0.22, places=9)


class TestOpAmpOutputHeadroom(unittest.TestCase):
    """Task area 3 — the op-amp must drive V_sense + V_BE + I_RB * R_B."""

    def test_output_ceiling_is_3v50_on_a_5v_rail(self):
        self.assertAlmostEqual(LM358P.output_max_v, 3.50, places=9)

    def test_required_output_includes_base_current_drop_across_rb(self):
        """Correction: R_B carries I_B, not zero."""
        v = compliance.opamp_output_required_v(
            V_CMD_FULL_SCALE, IR_CHANNEL_5V, hfe=70.0, rbe_ohm=None, vbe_on_v=0.70)
        self.assertAlmostEqual(v, 2.6217, places=4)

    def test_required_output_includes_rbe_current_in_the_rb_drop(self):
        """Correction: R_B carries I_B + I_RBE when R_BE is fitted."""
        without = compliance.opamp_output_required_v(
            V_CMD_FULL_SCALE, IR_CHANNEL_5V, hfe=70.0, rbe_ohm=None, vbe_on_v=0.70)
        with_rbe = compliance.opamp_output_required_v(
            V_CMD_FULL_SCALE, IR_CHANNEL_5V, hfe=70.0, rbe_ohm=10_000.0,
            vbe_on_v=0.70)
        self.assertGreater(with_rbe, without)
        self.assertAlmostEqual(with_rbe, 2.6907, places=4)

    def test_worst_case_required_output_still_fits_under_the_ceiling(self):
        v = compliance.opamp_output_required_v(
            V_CMD_FULL_SCALE, IR_CHANNEL_5V, hfe=70.0, rbe_ohm=10_000.0,
            vbe_on_v=0.75)
        self.assertAlmostEqual(v, 2.7456, places=4)
        self.assertLess(v, LM358P.output_max_v)

    def test_output_headroom_result_is_ok_with_margin(self):
        r = compliance.opamp_output_headroom(
            V_CMD_FULL_SCALE, IR_CHANNEL_5V, hfe=70.0, rbe_ohm=10_000.0,
            vbe_on_v=0.75)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.margin_v, 0.7544, places=4)

    def test_lower_hfe_demands_more_from_the_op_amp_output(self):
        low = compliance.opamp_output_required_v(
            V_CMD_FULL_SCALE, IR_CHANNEL_5V, hfe=70.0, rbe_ohm=None)
        high = compliance.opamp_output_required_v(
            V_CMD_FULL_SCALE, IR_CHANNEL_5V, hfe=400.0, rbe_ohm=None)
        self.assertGreater(low, high)


class TestLedAndTransistorCompliance(unittest.TestCase):
    """Task area 4 — V_CE = V_rail - V_F - V_sense must stay usable."""

    def test_red_vce_at_full_scale_worst_case_vf(self):
        v = compliance.collector_emitter_voltage(
            RED_CHANNEL_5V, V_CMD_FULL_SCALE, vf_selector="max")
        self.assertAlmostEqual(v, 1.16, places=9)

    def test_ir_vce_at_full_scale_worst_case_vf(self):
        v = compliance.collector_emitter_voltage(
            IR_CHANNEL_5V, V_CMD_FULL_SCALE, vf_selector="max")
        self.assertAlmostEqual(v, 1.71, places=9)

    def test_vce_requirement_exceeds_datasheet_vce_sat(self):
        self.assertGreater(compliance.MIN_VCE_V,
                           RED_CHANNEL_5V.transistor.vce_sat_max_v)

    def test_both_channels_comply_at_nominal_5v(self):
        for ch in (RED_CHANNEL_5V, IR_CHANNEL_5V):
            with self.subTest(channel=ch.name):
                r = compliance.led_compliance(ch, V_CMD_FULL_SCALE,
                                              vf_selector="max")
                self.assertTrue(r.ok)

    def test_unknown_vf_selector_is_rejected(self):
        with self.assertRaises(ValueError):
            compliance.collector_emitter_voltage(
                RED_CHANNEL_5V, V_CMD_FULL_SCALE, vf_selector="nominal")


class TestMinimumRail(unittest.TestCase):
    """Task area 8 — how far the supply may sag before the loop breaks."""

    def test_red_channel_needs_at_least_4v34(self):
        v = compliance.minimum_rail_v(RED_CHANNEL_5V, V_CMD_FULL_SCALE,
                                      vf_selector="max")
        self.assertAlmostEqual(v, 4.34, places=9)

    def test_ir_channel_needs_at_least_3v79(self):
        v = compliance.minimum_rail_v(IR_CHANNEL_5V, V_CMD_FULL_SCALE,
                                      vf_selector="max")
        self.assertAlmostEqual(v, 3.79, places=9)

    def test_red_channel_is_the_binding_constraint(self):
        red = compliance.minimum_rail_v(RED_CHANNEL_5V, V_CMD_FULL_SCALE,
                                        vf_selector="max")
        ir = compliance.minimum_rail_v(IR_CHANNEL_5V, V_CMD_FULL_SCALE,
                                       vf_selector="max")
        self.assertGreater(red, ir)

    def test_minus_10_percent_supply_still_complies(self):
        results = compliance.supply_sweep(
            [RED_CHANNEL_5V, IR_CHANNEL_5V], [4.50], V_CMD_FULL_SCALE,
            vf_selector="max")
        self.assertTrue(all(r.ok for r in results))

    def test_supply_sweep_reports_shrinking_margin(self):
        results = compliance.supply_sweep(
            [RED_CHANNEL_5V], [5.25, 5.00, 4.75, 4.50], V_CMD_FULL_SCALE,
            vf_selector="max")
        margins = [r.margin_v for r in results]
        self.assertEqual(margins, sorted(margins, reverse=True))
        self.assertAlmostEqual(margins[1], 0.66, places=9)   # 1.16 - 0.50

    def test_supply_sweep_flags_the_rail_where_red_fails(self):
        results = compliance.supply_sweep(
            [RED_CHANNEL_5V], [4.50, 4.25, 4.00], V_CMD_FULL_SCALE,
            vf_selector="max")
        self.assertEqual([r.ok for r in results], [True, False, False])


class TestExplicitFailureOnInsufficientCompliance(unittest.TestCase):
    """Task area 9 — insufficient compliance must raise, not silently clamp."""

    def test_a_3v28_rail_cannot_drive_the_red_led_and_raises(self):
        with self.assertRaises(compliance.ComplianceError):
            compliance.check_compliance_or_raise(
                RED_CHANNEL_5V, V_CMD_FULL_SCALE, rail_v=3.28,
                vf_selector="max")

    def test_the_error_message_names_the_channel_and_the_shortfall(self):
        with self.assertRaises(compliance.ComplianceError) as ctx:
            compliance.check_compliance_or_raise(
                RED_CHANNEL_5V, V_CMD_FULL_SCALE, rail_v=3.28,
                vf_selector="max")
        message = str(ctx.exception)
        self.assertIn("Red", message)
        self.assertIn("V_CE", message)

    def test_negative_vce_is_reported_not_clamped_to_zero(self):
        v = compliance.collector_emitter_voltage(
            RED_CHANNEL_5V, V_CMD_FULL_SCALE, vf_selector="max", rail_v=3.28)
        self.assertAlmostEqual(v, -0.56, places=9)

    def test_nominal_5v_rail_does_not_raise(self):
        compliance.check_compliance_or_raise(
            RED_CHANNEL_5V, V_CMD_FULL_SCALE, rail_v=5.00, vf_selector="max")

    def test_command_beyond_common_mode_also_raises(self):
        with self.assertRaises(compliance.ComplianceError):
            compliance.check_compliance_or_raise(
                RED_CHANNEL_5V, 3.28, rail_v=5.00, vf_selector="max",
                over_temperature=True)


if __name__ == "__main__":
    unittest.main()
