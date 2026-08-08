"""
Theoretical driver tests — DAC code / voltage / current equations (Stage 1).

Covers task areas 1, 2 and 6:
  1. DAC code, voltage and current equations.
  2. 4096 DAC levels versus maximum code 4095.
  6. LED current at code 0 and 4095.

Everything here is a PURE CALCULATION against the 5 V design *hypothesis*
(see led_driver.params.DESIGN_STATUS). Nothing in this file measures, proves
or implies anything about physical hardware.

Run: python3 -m unittest tests.test_led_driver_dac
"""

import ast
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import led_driver
from led_driver import dac as dac_calc
from led_driver.params import (
    CONVENTION_MAX_CODE,
    CONVENTION_RATIOMETRIC,
    DESIGN_STATUS,
    IR_CHANNEL_5V,
    RED_CHANNEL_5V,
    DacSpec,
)

MA = 1e-3
UA = 1e-6


class TestDesignStatusIsHypothesis(unittest.TestCase):
    """The whole 5 V candidate must announce itself as unverified."""

    def test_design_status_is_not_hardware_verified(self):
        self.assertIn("HYPOTHESIS", DESIGN_STATUS.upper())
        self.assertNotIn("VERIFIED-HARDWARE", DESIGN_STATUS.upper())

    def test_every_channel_carries_the_hypothesis_status(self):
        for ch in (RED_CHANNEL_5V, IR_CHANNEL_5V):
            with self.subTest(channel=ch.name):
                self.assertEqual(ch.status, DESIGN_STATUS)


class TestPureCalculationModuleHasNoHardwareImports(unittest.TestCase):
    """Static guard: the calculation package must not import GPIO/I2C libs."""

    FORBIDDEN_ROOTS = {
        "RPi", "gpiod", "gpiozero", "lgpio", "smbus", "smbus2",
        "board", "busio", "digitalio", "adafruit_mcp4725", "adafruit_blinka",
        "grove", "serial", "spidev", "periphery",
    }

    def _module_files(self):
        pkg_dir = pathlib.Path(led_driver.__file__).parent
        return sorted(pkg_dir.glob("*.py"))

    def test_package_has_source_files(self):
        self.assertTrue(self._module_files(), "led_driver package has no modules")

    def test_no_gpio_or_i2c_imports_anywhere_in_package(self):
        for path in self._module_files():
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    roots = [(node.module or "").split(".")[0]]
                else:
                    continue
                for root in roots:
                    with self.subTest(module=path.name, imported=root):
                        self.assertNotIn(root, self.FORBIDDEN_ROOTS)


class TestDacLevelsVersusMaxCode(unittest.TestCase):
    """Task area 2 — 4096 levels but 4095 is the largest writable code."""

    def setUp(self):
        self.dac = DacSpec()

    def test_twelve_bits_gives_4096_distinct_levels(self):
        self.assertEqual(self.dac.level_count, 4096)

    def test_largest_writable_code_is_4095(self):
        self.assertEqual(self.dac.max_code, 4095)

    def test_level_count_is_one_more_than_max_code(self):
        self.assertEqual(self.dac.level_count, self.dac.max_code + 1)

    def test_lsb_divides_fullscale_by_level_count_not_max_code(self):
        self.assertAlmostEqual(self.dac.lsb_v, 3.28 / 4096, places=12)
        self.assertNotAlmostEqual(self.dac.lsb_v, 3.28 / 4095, places=9)

    def test_ratiometric_convention_never_reaches_fullscale(self):
        v_max = dac_calc.code_to_voltage(4095, self.dac, CONVENTION_RATIOMETRIC)
        self.assertLess(v_max, self.dac.fullscale_v)
        self.assertAlmostEqual(v_max, 3.28 * 4095 / 4096, places=9)

    def test_max_code_convention_reaches_fullscale_exactly(self):
        v_max = dac_calc.code_to_voltage(4095, self.dac, CONVENTION_MAX_CODE)
        self.assertAlmostEqual(v_max, 3.28, places=12)

    def test_convention_discrepancy_at_full_scale_is_exactly_one_lsb(self):
        d = dac_calc.convention_discrepancy(self.dac)
        self.assertAlmostEqual(d["delta_v"], self.dac.lsb_v, places=12)
        self.assertAlmostEqual(d["delta_lsb"], 1.0, places=9)

    def test_convention_discrepancy_fraction_is_about_0_024_percent(self):
        d = dac_calc.convention_discrepancy(self.dac)
        self.assertAlmostEqual(d["delta_fraction"] * 100.0, 0.0244, places=4)

    def test_both_conventions_agree_at_code_zero(self):
        self.assertEqual(
            dac_calc.code_to_voltage(0, self.dac, CONVENTION_RATIOMETRIC), 0.0)
        self.assertEqual(
            dac_calc.code_to_voltage(0, self.dac, CONVENTION_MAX_CODE), 0.0)

    def test_out_of_range_codes_are_rejected(self):
        for bad in (-1, 4096, 1.5, True, None):
            with self.subTest(code=bad):
                with self.assertRaises(ValueError):
                    dac_calc.code_to_voltage(bad, self.dac, CONVENTION_RATIOMETRIC)

    def test_unknown_convention_is_rejected(self):
        with self.assertRaises(ValueError):
            dac_calc.code_to_voltage(1000, self.dac, "guess")


class TestCommandVoltageThroughDivider(unittest.TestCase):
    """Task area 1 — DAC volts -> op-amp command volts through the 10k/10k divider."""

    def test_divider_ratio_is_one_half(self):
        self.assertAlmostEqual(RED_CHANNEL_5V.divider.ratio, 0.5, places=12)
        self.assertAlmostEqual(IR_CHANNEL_5V.divider.ratio, 0.5, places=12)

    def test_thevenin_source_impedance_is_5k(self):
        self.assertAlmostEqual(RED_CHANNEL_5V.divider.thevenin_ohm, 5000.0, places=9)

    def test_dac_load_is_20k(self):
        self.assertAlmostEqual(RED_CHANNEL_5V.divider.dac_load_ohm, 20000.0, places=9)

    def test_fullscale_command_voltage_is_1v64(self):
        self.assertAlmostEqual(
            dac_calc.command_voltage_from_dac_v(3.28, RED_CHANNEL_5V), 1.640, places=9)

    def test_command_voltage_scales_linearly(self):
        self.assertAlmostEqual(
            dac_calc.command_voltage_from_dac_v(1.5, RED_CHANNEL_5V), 0.750, places=9)


class TestFullScaleCurrents(unittest.TestCase):
    """Task area 1 — the 5 V hypothesis full-scale currents."""

    def test_red_full_scale_current_is_16_40_ma(self):
        i = dac_calc.full_scale_current(RED_CHANNEL_5V)
        self.assertAlmostEqual(i / MA, 16.40, places=6)

    def test_ir_full_scale_current_is_20_00_ma(self):
        i = dac_calc.full_scale_current(IR_CHANNEL_5V)
        self.assertAlmostEqual(i / MA, 20.00, places=6)

    def test_red_rsense_is_100_ohm_and_ir_is_82_ohm(self):
        self.assertEqual(RED_CHANNEL_5V.rsense_ohm, 100.0)
        self.assertEqual(IR_CHANNEL_5V.rsense_ohm, 82.0)

    def test_sense_current_is_command_over_rsense(self):
        self.assertAlmostEqual(
            dac_calc.sense_current(0.750, RED_CHANNEL_5V) / MA, 7.50, places=9)
        self.assertAlmostEqual(
            dac_calc.sense_current(0.750, IR_CHANNEL_5V) / MA, 9.1463, places=4)

    def test_negative_command_voltage_is_rejected(self):
        with self.assertRaises(ValueError):
            dac_calc.sense_current(-0.1, RED_CHANNEL_5V)


class TestCurrentLsb(unittest.TestCase):
    """Task area 1/2 — one DAC code step in LED-current terms."""

    def test_red_current_lsb_is_about_4_00_ua(self):
        self.assertAlmostEqual(
            dac_calc.current_lsb(RED_CHANNEL_5V) / UA, 4.0039, places=4)

    def test_ir_current_lsb_is_about_4_88_ua(self):
        self.assertAlmostEqual(
            dac_calc.current_lsb(IR_CHANNEL_5V) / UA, 4.8828, places=4)


class TestLedCurrentAtCodeZeroAndFullScale(unittest.TestCase):
    """Task area 6 — LED current at code 0 and code 4095."""

    def test_code_zero_gives_exactly_zero_ideal_current(self):
        i = dac_calc.led_current_from_code(0, RED_CHANNEL_5V, hfe=300.0)
        self.assertEqual(i, 0.0)

    def test_code_4095_ratiometric_is_one_lsb_below_the_ideal_ceiling(self):
        i = dac_calc.led_current_from_code(
            4095, RED_CHANNEL_5V, hfe=None,
            convention=CONVENTION_RATIOMETRIC)
        self.assertAlmostEqual(i / MA, 16.396, places=3)
        self.assertLess(i, dac_calc.full_scale_current(RED_CHANNEL_5V))

    def test_code_4095_max_code_convention_hits_the_ideal_ceiling(self):
        i = dac_calc.led_current_from_code(
            4095, RED_CHANNEL_5V, hfe=None, convention=CONVENTION_MAX_CODE)
        self.assertAlmostEqual(i / MA, 16.40, places=6)

    def test_hfe_none_means_ideal_alpha_of_one(self):
        ideal = dac_calc.led_current_from_code(2048, RED_CHANNEL_5V, hfe=None)
        real = dac_calc.led_current_from_code(2048, RED_CHANNEL_5V, hfe=70.0)
        self.assertLess(real, ideal)

    def test_base_current_loss_at_hfe_70_is_1_41_percent(self):
        ideal = dac_calc.led_current_from_code(2048, RED_CHANNEL_5V, hfe=None)
        real = dac_calc.led_current_from_code(2048, RED_CHANNEL_5V, hfe=70.0)
        self.assertAlmostEqual((1.0 - real / ideal) * 100.0, 1.4085, places=4)

    def test_code_zero_with_offset_and_no_rbe_leaks_led_current(self):
        """Worst-case op-amp offset means 'code 0' is not exactly 'LED off'."""
        i = dac_calc.led_current_from_command(
            0.00825, RED_CHANNEL_5V, hfe=300.0, rbe_ohm=None)
        self.assertGreater(i / UA, 80.0)

    def test_rbe_10k_creates_a_dead_zone_below_7mv_command(self):
        """R_BE bleeds the sense current away from the base at low commands."""
        i = dac_calc.led_current_from_command(
            0.005, RED_CHANNEL_5V, hfe=300.0, rbe_ohm=10_000.0, vbe_on_v=0.70)
        self.assertEqual(i, 0.0)

    def test_rbe_10k_strongly_suppresses_the_offset_current(self):
        without = dac_calc.led_current_from_command(
            0.00825, RED_CHANNEL_5V, hfe=300.0, rbe_ohm=None)
        with_rbe = dac_calc.led_current_from_command(
            0.00825, RED_CHANNEL_5V, hfe=300.0, rbe_ohm=10_000.0, vbe_on_v=0.70)
        self.assertGreater(with_rbe, 0.0)
        self.assertLess(with_rbe, 0.2 * without)

    def test_led_current_is_monotonic_in_code(self):
        prev = -1.0
        for code in range(0, 4096, 137):
            i = dac_calc.led_current_from_code(code, IR_CHANNEL_5V, hfe=300.0)
            self.assertGreaterEqual(i, prev)
            prev = i


class TestDocumentedCodeTable(unittest.TestCase):
    """Cross-check the code table used in 03_LED_DRIVER_ARCHITECTURE.md §8.4."""

    EXPECTED = [
        # (target mA, red code, ir code)
        (2.0, 499, 409),
        (5.0, 1248, 1023),
        (7.5, 1872, 1535),
        (10.0, 2496, 2047),
    ]

    def test_target_current_to_code_matches_documented_table(self):
        for ma, red_code, ir_code in self.EXPECTED:
            with self.subTest(mA=ma):
                self.assertEqual(
                    dac_calc.code_for_target_current(ma * MA, RED_CHANNEL_5V), red_code)
                self.assertEqual(
                    dac_calc.code_for_target_current(ma * MA, IR_CHANNEL_5V), ir_code)

    def test_target_above_full_scale_is_rejected(self):
        with self.assertRaises(ValueError):
            dac_calc.code_for_target_current(25.0 * MA, RED_CHANNEL_5V)


if __name__ == "__main__":
    unittest.main()
