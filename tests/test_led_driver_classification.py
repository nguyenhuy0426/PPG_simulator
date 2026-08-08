"""
Theoretical driver tests — Stage 1 value classification.

The task requires every candidate value to be classified as exactly one of:
FIXED BY DATASHEET/CALCULATION, RECOMMENDED STARTING VALUE,
MEASUREMENT-REQUIRED, or UNKNOWN. This test suite enforces that the table
is complete, uses only those four classes, and never upgrades evidence:
RBE, C1 and C2 must NOT be finalised from theory alone.

Run: python3 -m unittest tests.test_led_driver_classification
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from led_driver import classification
from led_driver.classification import (
    FIXED,
    MEASUREMENT_REQUIRED,
    RECOMMENDED,
    UNKNOWN,
)


class TestTableShape(unittest.TestCase):
    def test_every_entry_uses_one_of_the_four_classes(self):
        allowed = {FIXED, RECOMMENDED, MEASUREMENT_REQUIRED, UNKNOWN}
        for entry in classification.VALUE_TABLE:
            with self.subTest(value=entry.name):
                self.assertIn(entry.classification, allowed)

    def test_every_entry_names_its_evidence_source(self):
        for entry in classification.VALUE_TABLE:
            with self.subTest(value=entry.name):
                self.assertTrue(entry.basis.strip())

    def test_entry_names_are_unique(self):
        names = [e.name for e in classification.VALUE_TABLE]
        self.assertEqual(len(names), len(set(names)))


class TestRequiredEntries(unittest.TestCase):
    def _lookup(self, name):
        return classification.by_name(name)

    def test_core_circuit_values_are_all_present(self):
        for name in ("rsense_red", "rsense_ir", "rb", "divider_ratio",
                     "divider_r_abs", "rbe", "c1_input_filter", "c2",
                     "c3_lm358_bypass", "c4_5v_bulk", "c5_opt101_bypass",
                     "rail_5v", "dac_fullscale", "adc_reference",
                     "opamp_output_ceiling", "opamp_cm_limit",
                     "transistor_hfe_installed", "vbe_on",
                     "transistor_pinout_installed", "led_polarity_installed",
                     "red_led_reverse_abs_max", "mcp4725_eeprom_contents"):
            with self.subTest(name=name):
                self.assertIsNotNone(self._lookup(name))

    def test_rbe_c1_and_c2_are_not_finalised_from_theory(self):
        for name in ("rbe", "c1_input_filter", "c2"):
            with self.subTest(name=name):
                entry = self._lookup(name)
                self.assertEqual(entry.classification, MEASUREMENT_REQUIRED)

    def test_installed_part_properties_are_measurement_required(self):
        for name in ("transistor_hfe_installed", "vbe_on",
                     "transistor_pinout_installed", "led_polarity_installed",
                     "mcp4725_eeprom_contents"):
            with self.subTest(name=name):
                entry = self._lookup(name)
                self.assertEqual(entry.classification, MEASUREMENT_REQUIRED)

    def test_red_led_reverse_abs_max_is_unknown(self):
        self.assertEqual(self._lookup("red_led_reverse_abs_max").classification,
                         UNKNOWN)

    def test_datasheet_limits_are_fixed(self):
        for name in ("opamp_output_ceiling", "opamp_cm_limit",
                     "dac_fullscale", "adc_reference", "divider_ratio"):
            with self.subTest(name=name):
                self.assertEqual(self._lookup(name).classification, FIXED)

    def test_candidate_component_values_are_starting_values(self):
        for name in ("rsense_red", "rsense_ir", "rb", "divider_r_abs",
                     "c3_lm358_bypass", "c4_5v_bulk", "c5_opt101_bypass"):
            with self.subTest(name=name):
                self.assertEqual(self._lookup(name).classification,
                                 RECOMMENDED)

    def test_lookup_of_a_missing_name_returns_none(self):
        self.assertIsNone(self._lookup("does_not_exist"))


class TestConsistencyWithParams(unittest.TestCase):
    def test_stated_values_match_the_channel_designs(self):
        from led_driver.params import IR_CHANNEL_5V, RED_CHANNEL_5V
        self.assertEqual(classification.by_name("rsense_red").value,
                         RED_CHANNEL_5V.rsense_ohm)
        self.assertEqual(classification.by_name("rsense_ir").value,
                         IR_CHANNEL_5V.rsense_ohm)
        self.assertEqual(classification.by_name("rb").value,
                         RED_CHANNEL_5V.rb_ohm)
        self.assertEqual(classification.by_name("dac_fullscale").value,
                         RED_CHANNEL_5V.dac.fullscale_v)

    def test_measurement_required_and_unknown_entries_carry_no_value(self):
        for entry in classification.VALUE_TABLE:
            if entry.classification in (MEASUREMENT_REQUIRED, UNKNOWN):
                with self.subTest(value=entry.name):
                    self.assertIsNone(entry.value)


if __name__ == "__main__":
    unittest.main()
