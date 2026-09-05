"""
tests/test_limits.py — parameter-range single source of truth.

The ranges under test are the union of the WhaleTeq AECG100 reflectance and
transmittance module specifications (docs/whale_device/user_manual.pdf,
Tables 7, 10, 11, 13), which is the commercial benchmark this simulator is
being brought to parity with.

Runnable with either:
    python3 -m unittest tests.test_limits -v
    pytest tests/test_limits.py -v
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from models import limits


class TestLimitObject(unittest.TestCase):
    def test_clamp_below_minimum_returns_minimum(self):
        self.assertEqual(limits.HEART_RATE.clamp(-5.0), limits.HEART_RATE.minimum)

    def test_clamp_above_maximum_returns_maximum(self):
        self.assertEqual(limits.HEART_RATE.clamp(9_999.0), limits.HEART_RATE.maximum)

    def test_clamp_inside_range_is_identity(self):
        self.assertEqual(limits.HEART_RATE.clamp(75.0), 75.0)

    def test_contains(self):
        self.assertTrue(limits.HEART_RATE.contains(10.0))
        self.assertTrue(limits.HEART_RATE.contains(300.0))
        self.assertFalse(limits.HEART_RATE.contains(9.999))

    def test_validate_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            limits.HEART_RATE.validate(400.0)

    def test_validate_rejects_non_finite(self):
        for bad in (float("nan"), float("inf"), "75", None, True):
            with self.assertRaises(ValueError):
                limits.HEART_RATE.validate(bad)

    def test_validate_returns_float(self):
        self.assertIsInstance(limits.HEART_RATE.validate(75), float)

    def test_quantise_snaps_to_step(self):
        # HR step is 1 BPM.
        self.assertEqual(limits.HEART_RATE.quantise(75.4), 75.0)
        self.assertEqual(limits.HEART_RATE.quantise(75.6), 76.0)

    def test_quantise_with_zero_step_is_identity(self):
        free = limits.Limit(0.0, 1.0, 0.0, 0.0, "")
        self.assertEqual(free.quantise(0.123456), 0.123456)

    def test_limit_is_immutable(self):
        with self.assertRaises(Exception):
            limits.HEART_RATE.minimum = 0.0


class TestAECG100Ranges(unittest.TestCase):
    """Each range must cover the corresponding AECG100 specification."""

    def test_heart_rate_covers_10_to_300_bpm(self):
        self.assertLessEqual(limits.HEART_RATE.minimum, 10.0)
        self.assertGreaterEqual(limits.HEART_RATE.maximum, 300.0)

    def test_perfusion_index_covers_reflectance_and_transmittance(self):
        self.assertLessEqual(limits.PERFUSION_INDEX.minimum, 0.01)
        self.assertGreaterEqual(limits.PERFUSION_INDEX.maximum, 30.0)

    def test_resp_rate_covers_1_to_150_brpm(self):
        self.assertLessEqual(limits.RESP_RATE.minimum, 1.0)
        self.assertGreaterEqual(limits.RESP_RATE.maximum, 150.0)

    def test_spo2_covers_0_to_100(self):
        self.assertLessEqual(limits.SPO2.minimum, 0.0)
        self.assertGreaterEqual(limits.SPO2.maximum, 100.0)

    def test_dc_level_covers_100_to_3000_mv(self):
        self.assertLessEqual(limits.DC_LEVEL_MV.minimum, 100.0)
        self.assertGreaterEqual(limits.DC_LEVEL_MV.maximum, 3000.0)

    def test_ac_level_covers_transmittance_range(self):
        self.assertLessEqual(limits.AC_LEVEL_MV.minimum, 0.1)
        self.assertGreaterEqual(limits.AC_LEVEL_MV.maximum, 300.0)

    def test_output_dc_offset_covers_0_to_2000_mv(self):
        self.assertEqual(limits.OUTPUT_DC_OFFSET_MV.minimum, 0.0)
        self.assertGreaterEqual(limits.OUTPUT_DC_OFFSET_MV.maximum, 2000.0)

    def test_feature_time_covers_0_to_1000_ms(self):
        self.assertEqual(limits.FEATURE_TIME_MS.minimum, 0.0)
        self.assertGreaterEqual(limits.FEATURE_TIME_MS.maximum, 1000.0)

    def test_noise_amplitude_covers_0_05_to_2_mv(self):
        self.assertLessEqual(limits.NOISE_AMPLITUDE_MV.minimum, 0.05)
        self.assertGreaterEqual(limits.NOISE_AMPLITUDE_MV.maximum, 2.0)

    def test_resp_variation_covers_1_to_16_percent(self):
        self.assertLessEqual(limits.RESP_VARIATION_PCT.minimum, 1.0)
        self.assertGreaterEqual(limits.RESP_VARIATION_PCT.maximum, 16.0)

    def test_apnea_duration_covers_1_to_60_s(self):
        self.assertLessEqual(limits.APNEA_DURATION_S.minimum, 1.0)
        self.assertGreaterEqual(limits.APNEA_DURATION_S.maximum, 60.0)

    def test_apnea_cycle_covers_1_to_10_min(self):
        self.assertLessEqual(limits.APNEA_CYCLE_MIN.minimum, 1.0)
        self.assertGreaterEqual(limits.APNEA_CYCLE_MIN.maximum, 10.0)

    def test_every_default_is_inside_its_own_range(self):
        for name, limit in limits.all_limits().items():
            with self.subTest(limit=name):
                self.assertTrue(
                    limit.contains(limit.default),
                    f"{name}: default {limit.default} outside "
                    f"[{limit.minimum}, {limit.maximum}]",
                )


class TestDcOffsetRule(unittest.TestCase):
    """AECG100: DC + Output-DC offset must not exceed 3000 mV."""

    def test_sum_within_budget_is_accepted(self):
        self.assertEqual(limits.validate_dc_with_offset(625.0, 1000.0), (625.0, 1000.0))

    def test_sum_over_budget_raises(self):
        with self.assertRaises(ValueError):
            limits.validate_dc_with_offset(2500.0, 1000.0)

    def test_boundary_sum_is_accepted(self):
        limits.validate_dc_with_offset(1000.0, 2000.0)


class TestInhaleExhaleRatios(unittest.TestCase):
    def test_supported_ratios_match_aecg100(self):
        self.assertEqual(limits.INHALE_EXHALE_RATIOS, (1, 2, 3, 4, 5))

    def test_inhale_fraction_one_to_one(self):
        self.assertAlmostEqual(limits.inhale_fraction(1), 0.5)

    def test_inhale_fraction_one_to_four(self):
        self.assertAlmostEqual(limits.inhale_fraction(4), 0.2)

    def test_unsupported_ratio_raises(self):
        with self.assertRaises(ValueError):
            limits.inhale_fraction(6)


if __name__ == "__main__":
    unittest.main()
