"""
tests/test_calibration.py — Phase 2 narrow unit tests.

Covers exactly the Phase 2 scope:
  - forward SpO2 mapping   : SpO2 = A - B*R
  - inverse R mapping      : R_target = (A - SpO2) / B
  - invalid B (<= 0)       -> ValueError
  - non-finite inputs      -> ValueError
  - DAC voltage->code boundaries (0 V, full-scale, over/under, midpoint)
  - unit conversion        : mV<->V and DAC_FULLSCALE_MV
  - config persistence backward compatibility for A/B

Runnable with either:
    python3 -m unittest tests.test_calibration -v
    pytest tests/test_calibration.py -v
Only stdlib + project config/calibration are required (no numpy / hardware).
"""

import math
import os
import sys
import unittest

# Make the repository root importable regardless of CWD.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import config
from calibration import (
    spo2_from_r,
    r_target_from_spo2,
    validate_coefficients,
    dac_voltage_to_code,
    SpO2Calibration,
    SPO2_COEFF_A_DEFAULT,
    SPO2_COEFF_B_DEFAULT,
)


class TestForwardSpO2Mapping(unittest.TestCase):
    def test_default_coefficients(self):
        # SpO2 = 110 - 25*R ; R=0.5 -> 97.5 (WhaleTeq worked example)
        self.assertAlmostEqual(spo2_from_r(0.5), 97.5)
        self.assertAlmostEqual(spo2_from_r(0.0), 110.0)
        self.assertAlmostEqual(spo2_from_r(1.0), 85.0)

    def test_custom_coefficients(self):
        # Fig 81 alternate calibration: SpO2 = 111.1 - 22.6*R
        self.assertAlmostEqual(spo2_from_r(0.5, 111.1, 22.6), 111.1 - 22.6 * 0.5)


class TestInverseRMapping(unittest.TestCase):
    def test_default_coefficients(self):
        # R_target = (110 - SpO2)/25
        self.assertAlmostEqual(r_target_from_spo2(97.5), 0.5)
        self.assertAlmostEqual(r_target_from_spo2(110.0), 0.0)
        self.assertAlmostEqual(r_target_from_spo2(98.0), (110.0 - 98.0) / 25.0)

    def test_round_trip(self):
        # Forward then inverse must recover the original R across A/B choices.
        for a, b in ((110.0, 25.0), (112.7, 20.1), (111.1, 22.6)):
            for r in (0.4, 0.5, 0.8, 1.2, 1.6):
                spo2 = spo2_from_r(r, a, b)
                self.assertAlmostEqual(r_target_from_spo2(spo2, a, b), r, places=9)


class TestInvalidB(unittest.TestCase):
    def test_zero_b_rejected(self):
        with self.assertRaises(ValueError):
            validate_coefficients(110.0, 0.0)
        with self.assertRaises(ValueError):
            r_target_from_spo2(98.0, 110.0, 0.0)

    def test_negative_b_rejected(self):
        with self.assertRaises(ValueError):
            validate_coefficients(110.0, -5.0)
        with self.assertRaises(ValueError):
            spo2_from_r(0.5, 110.0, -1.0)


class TestNonFiniteInputs(unittest.TestCase):
    def test_nonfinite_coefficients_rejected(self):
        for bad in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                validate_coefficients(bad, 25.0)
            with self.assertRaises(ValueError):
                validate_coefficients(110.0, bad)

    def test_nonnumeric_coefficients_rejected(self):
        for bad in ("110", None, [110.0], True):
            with self.assertRaises(ValueError):
                validate_coefficients(bad, 25.0)

    def test_nonfinite_r_and_spo2_rejected(self):
        with self.assertRaises(ValueError):
            spo2_from_r(math.nan)
        with self.assertRaises(ValueError):
            r_target_from_spo2(math.inf)


class TestDacVoltageToCode(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(dac_voltage_to_code(0.0), 0)
        # Full-scale (measured 3.28 V) maps to the top code 4095.
        self.assertEqual(dac_voltage_to_code(config.DAC_FULLSCALE_V), config.DAC_MAX_VALUE)

    def test_clamping(self):
        self.assertEqual(dac_voltage_to_code(-1.0), 0)              # under-range clamps low
        self.assertEqual(dac_voltage_to_code(5.0), config.DAC_MAX_VALUE)  # over-range clamps high

    def test_midpoint(self):
        # 1.64 V is half of 3.28 V full-scale: int(0.5 * 4095) = 2047 (truncation).
        self.assertEqual(dac_voltage_to_code(1.64), 2047)

    def test_uses_measured_fullscale_not_3v3(self):
        # A regression guard: 3.28 V must be full-scale, so 3.3 V — the old
        # nominal-VDD assumption — now exceeds range and clamps to the max code.
        self.assertEqual(dac_voltage_to_code(3.3), config.DAC_MAX_VALUE)
        # And 3.2 V no longer produces the old ~3969 code it did at /3.3 scaling.
        self.assertNotEqual(dac_voltage_to_code(3.2), int((3.2 / 3.3) * 4095))
        # 3.2 V is now below full-scale and must map strictly under 4095.
        self.assertEqual(dac_voltage_to_code(3.2), int((3.2 / 3.28) * 4095))
        self.assertLess(dac_voltage_to_code(3.2), config.DAC_MAX_VALUE)

    def test_nonfinite_voltage_rejected(self):
        with self.assertRaises(ValueError):
            dac_voltage_to_code(math.nan)
        with self.assertRaises(ValueError):
            dac_voltage_to_code(math.inf)

    def test_invalid_fullscale_rejected(self):
        with self.assertRaises(ValueError):
            dac_voltage_to_code(1.0, fullscale_v=0.0)


class TestUnitConversion(unittest.TestCase):
    def test_fullscale_mv_matches_v(self):
        self.assertEqual(config.DAC_FULLSCALE_MV, config.DAC_FULLSCALE_V * 1000.0)
        self.assertEqual(config.DAC_FULLSCALE_MV, 3280.0)

    def test_mv_to_v_path_matches_v_path(self):
        # UI works in mV; converting mV->V explicitly must match the volt path.
        for val_mv in (0.0, 625.0, 1640.0, 3280.0):
            self.assertEqual(
                dac_voltage_to_code(val_mv / 1000.0),
                dac_voltage_to_code(val_mv / 1000.0, config.DAC_FULLSCALE_V, config.DAC_MAX_VALUE),
            )

    def test_dc_625mv_code(self):
        # WhaleTeq DC example 625 mV at 3.28 V full-scale.
        self.assertEqual(dac_voltage_to_code(0.625), int((0.625 / 3.28) * 4095))


class TestSpO2CalibrationDataclass(unittest.TestCase):
    def test_defaults(self):
        cal = SpO2Calibration()
        self.assertEqual(cal.a, SPO2_COEFF_A_DEFAULT)
        self.assertEqual(cal.b, SPO2_COEFF_B_DEFAULT)
        self.assertAlmostEqual(cal.spo2_from_r(0.5), 97.5)
        self.assertAlmostEqual(cal.r_target_from_spo2(97.5), 0.5)

    def test_invalid_construction_rejected(self):
        with self.assertRaises(ValueError):
            SpO2Calibration(a=110.0, b=0.0)
        with self.assertRaises(ValueError):
            SpO2Calibration(a=math.nan, b=25.0)


class TestConfigPersistenceBackwardCompat(unittest.TestCase):
    """A/B persistence must survive round-trips and tolerate legacy/corrupt files."""

    def _make_params(self):
        from models.ppg_model import PPGParameters
        return PPGParameters()

    def test_defaults_present_in_store(self):
        import config_store
        self.assertIn("spo2_coeff_a", config_store._DEFAULTS)
        self.assertIn("spo2_coeff_b", config_store._DEFAULTS)

    def test_legacy_config_without_ab_uses_defaults(self):
        import config_store
        legacy = {"heart_rate": 80.0, "spo2": 95.0}  # no A/B keys (old file)
        params = self._make_params()
        config_store.apply_config_to_params(legacy, params)
        self.assertEqual(params.spo2_coeff_a, SPO2_COEFF_A_DEFAULT)
        self.assertEqual(params.spo2_coeff_b, SPO2_COEFF_B_DEFAULT)

    def test_valid_ab_round_trip(self):
        import config_store
        params = self._make_params()
        params.spo2_coeff_a = 111.1
        params.spo2_coeff_b = 22.6
        cfg = config_store.config_from_ppg_params(params)
        self.assertEqual(cfg["spo2_coeff_a"], 111.1)
        self.assertEqual(cfg["spo2_coeff_b"], 22.6)
        restored = self._make_params()
        config_store.apply_config_to_params(cfg, restored)
        self.assertEqual(restored.spo2_coeff_a, 111.1)
        self.assertEqual(restored.spo2_coeff_b, 22.6)

    def test_corrupt_ab_falls_back_to_defaults(self):
        import config_store
        bad = {"spo2_coeff_a": 110.0, "spo2_coeff_b": 0.0}  # B<=0 corrupt
        params = self._make_params()
        config_store.apply_config_to_params(bad, params)
        self.assertEqual(params.spo2_coeff_a, SPO2_COEFF_A_DEFAULT)
        self.assertEqual(params.spo2_coeff_b, SPO2_COEFF_B_DEFAULT)


class TestPPGModelIntegration(unittest.TestCase):
    def test_params_carry_ab_defaults(self):
        from models.ppg_model import PPGParameters
        p = PPGParameters()
        self.assertEqual(p.spo2_coeff_a, SPO2_COEFF_A_DEFAULT)
        self.assertEqual(p.spo2_coeff_b, SPO2_COEFF_B_DEFAULT)
        # copy() must preserve the new fields.
        self.assertEqual(p.copy().spo2_coeff_a, SPO2_COEFF_A_DEFAULT)

    def test_set_spo2_coefficients_validates(self):
        from models.ppg_model import PPGModel
        m = PPGModel()
        m.set_spo2_coefficients(111.1, 22.6)
        self.assertEqual(m.params.spo2_coeff_a, 111.1)
        self.assertEqual(m.params.spo2_coeff_b, 22.6)
        with self.assertRaises(ValueError):
            m.set_spo2_coefficients(110.0, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
