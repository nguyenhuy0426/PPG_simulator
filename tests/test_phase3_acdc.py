"""
tests/test_phase3_acdc.py — Phase 3 narrow unit tests.

Covers exactly the Phase 3 scope (docs/claude_phases/03_PHASE_AC_DC_PI_AND_
RED_IR_MODEL.md §Tests):
  - AC/DC → PI                         (PI derived, AC/DC are master)
  - equal and unequal DC ratio-of-ratios : R = (AC_red/DC_red)/(AC_ir/DC_ir)
  - A/B changes                        (SpO2 = A - B*R drives derived Red AC)
  - clipping                           (bounded by the real 3.28 V DAC range)
  - AC above / below DC                (selectable polarity)
  - invalid combinations               (non-physical / unsafe → ValueError)

Runnable with either:
    python3 -m unittest tests.test_phase3_acdc -v
    pytest tests/test_phase3_acdc.py -v
Only stdlib + project config/calibration/model are required (no numpy/hardware).
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
    perfusion_index_from_ac_dc,
    ratio_of_ratios,
    ac_red_from_target,
    validate_ac_dc,
    r_target_from_spo2,
)
from models.ppg_model import (
    PPGModel,
    PPGParameters,
    POLARITY_ABOVE_DC,
    POLARITY_BELOW_DC,
    COND_NORMAL,
    COND_STRONG_PERFUSION,
    DEFAULT_DC_BASELINE_V,
)


def _run_cycles(model, n_samples, dt=0.01):
    """Generate n_samples and return lists of (ir, red, disp_ir, disp_red)."""
    ir, red, dir_, dred = [], [], [], []
    for _ in range(n_samples):
        s_ir, s_red, d_ir, d_red = model.generate_both_samples(dt)
        ir.append(s_ir); red.append(s_red); dir_.append(d_ir); dred.append(d_red)
    return ir, red, dir_, dred


# ─────────────────────────── AC/DC → PI ───────────────────────────
class TestAcDcToPI(unittest.TestCase):
    def test_pure_pi_from_ac_dc(self):
        # PI = AC/DC × 100. Units cancel (works in mV or V).
        self.assertAlmostEqual(perfusion_index_from_ac_dc(45.0, 1500.0), 3.0)
        self.assertAlmostEqual(perfusion_index_from_ac_dc(150.0, 1500.0), 10.0)
        self.assertAlmostEqual(perfusion_index_from_ac_dc(0.045, 1.5), 3.0)

    def test_model_set_ac_dc_derives_pi(self):
        # set_ac_dc is the master entry point; PI must be DERIVED from AC/DC.
        m = PPGModel()
        m.set_ac_dc(45.0, 1500.0)          # 45 mV / 1500 mV → PI = 3.0
        self.assertAlmostEqual(m.current_pi, 3.0)
        self.assertAlmostEqual(m.params.perfusion_index, 3.0)
        m.set_ac_dc(150.0, 1500.0)         # → PI = 10.0
        self.assertAlmostEqual(m.current_pi, 10.0)

    def test_model_set_ac_dc_sets_per_channel_dc(self):
        m = PPGModel()
        m.set_ac_dc(45.0, 1500.0, 900.0)
        self.assertAlmostEqual(m.dc_ir, 1.5)
        self.assertAlmostEqual(m.dc_red, 0.9)
        # legacy alias tracks the IR (primary) channel
        self.assertAlmostEqual(m.dc_baseline, m.dc_ir)


# ────────────────── equal & unequal DC ratio-of-ratios ──────────────────
class TestRatioOfRatios(unittest.TestCase):
    def test_pure_equal_dc(self):
        # Equal DC → AC_red = R·AC_ir and reconstructed R == target.
        for r in (0.4, 0.5, 0.8, 1.2, 1.6):
            ac_ir = 0.045
            ac_red = ac_red_from_target(r, ac_ir, 1.5, 1.5)
            self.assertAlmostEqual(ac_red, r * ac_ir)
            self.assertAlmostEqual(ratio_of_ratios(ac_red, 1.5, ac_ir, 1.5), r)

    def test_pure_unequal_dc(self):
        # Unequal DC → AC_red carries (DC_red/DC_ir); reconstructed R still exact.
        cases = [(1.5, 0.9), (1.0, 2.0), (2.0, 0.5), (1.5, 1.2)]
        for dc_ir, dc_red in cases:
            for r in (0.4, 0.6, 0.8, 1.0, 1.3, 1.6):
                ac_ir = 0.05
                ac_red = ac_red_from_target(r, ac_ir, dc_red, dc_ir)
                self.assertAlmostEqual(ac_red, r * ac_ir * (dc_red / dc_ir))
                self.assertAlmostEqual(
                    ratio_of_ratios(ac_red, dc_red, ac_ir, dc_ir), r, places=9)

    def test_model_equal_dc_reconstructs_r(self):
        # End-to-end: last_ac_ir/last_ac_red share pulse & HR coupling, so their
        # ratio-of-ratios equals the SpO2 target regardless of PI/pulse phase.
        m = PPGModel()
        p = PPGParameters(); p.spo2 = 90.0   # R_target = (110-90)/25 = 0.8
        m.set_parameters(p)
        self._assert_reconstructs(m, 0.8)

    def test_model_unequal_dc_reconstructs_r(self):
        m = PPGModel()
        p = PPGParameters(); p.spo2 = 90.0
        p.dc_ir_mv = 1500.0; p.dc_red_mv = 900.0   # unequal DC
        m.set_parameters(p)
        self.assertAlmostEqual(m.dc_ir, 1.5)
        self.assertAlmostEqual(m.dc_red, 0.9)
        self._assert_reconstructs(m, 0.8)

    def _assert_reconstructs(self, m, r_expected):
        # Advance until the pulse is non-zero so the AC amplitudes are meaningful.
        got = None
        for _ in range(2000):
            m.generate_both_samples(0.01)
            if m.last_ac_ir > 1e-6:
                got = ratio_of_ratios(m.last_ac_red, m.dc_red,
                                      m.last_ac_ir, m.dc_ir)
                break
        self.assertIsNotNone(got, "pulse never became non-zero")
        self.assertAlmostEqual(got, r_expected, places=6)


# ─────────────────────────── A/B changes ───────────────────────────
class TestABChanges(unittest.TestCase):
    def test_ab_changes_derived_red_ac(self):
        # For a fixed SpO2, changing A/B changes R_target, hence AC_red.
        spo2 = 96.0
        r_default = r_target_from_spo2(spo2)                 # (110-96)/25 = 0.56
        r_alt = r_target_from_spo2(spo2, 111.1, 22.6)        # different mapping
        self.assertNotAlmostEqual(r_default, r_alt)
        ac_ir = 0.045
        ac_red_default = ac_red_from_target(r_default, ac_ir, 1.5, 1.5)
        ac_red_alt = ac_red_from_target(r_alt, ac_ir, 1.5, 1.5)
        # AC_red tracks R, so different A/B → different Red amplitude.
        self.assertNotAlmostEqual(ac_red_default, ac_red_alt)

    def test_model_ab_flows_into_ratio(self):
        # With custom A/B on the model, the reconstructed ratio equals the R
        # implied by those A/B and the SpO2.
        m = PPGModel()
        p = PPGParameters(); p.spo2 = 96.0
        p.spo2_coeff_a = 111.1; p.spo2_coeff_b = 22.6
        m.set_parameters(p)
        r_expected = r_target_from_spo2(96.0, 111.1, 22.6)
        got = None
        for _ in range(2000):
            m.generate_both_samples(0.01)
            if m.last_ac_ir > 1e-6:
                got = ratio_of_ratios(m.last_ac_red, m.dc_red,
                                      m.last_ac_ir, m.dc_ir)
                break
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got, r_expected, places=6)


# ─────────────────────────── clipping ───────────────────────────
class TestClipping(unittest.TestCase):
    def test_output_bounded_to_dac_range(self):
        # Every generated sample must stay within [0, 3.28 V] (measured full-scale).
        m = PPGModel()
        m.set_ac_dc(150.0, 1500.0)   # PI=10, normal DC
        ir, red, _, _ = _run_cycles(m, 1500)
        for v in ir + red:
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, config.DAC_FULLSCALE_V)

    def test_upper_clip_engages_at_full_scale(self):
        # High DC + high PI drives the systolic peak above 3.28 V → must clamp
        # exactly at the DAC ceiling, never above it.
        m = PPGModel()
        p = PPGParameters()
        p.condition = COND_STRONG_PERFUSION   # PI range keeps a high perfusion
        p.perfusion_index = 18.0
        p.dc_ir_mv = 3000.0; p.dc_red_mv = 3000.0
        m.set_parameters(p)
        ir, red, _, _ = _run_cycles(m, 2000)
        self.assertLessEqual(max(ir), config.DAC_FULLSCALE_V)
        self.assertGreaterEqual(min(ir), 0.0)
        # The ceiling must actually be reached (clipping engaged), else the test
        # would silently pass without exercising the clamp.
        self.assertEqual(max(ir), config.DAC_FULLSCALE_V)


# ─────────────────────── AC above / below DC ───────────────────────
class TestPolarity(unittest.TestCase):
    def test_default_is_above_dc(self):
        m = PPGModel()
        self.assertEqual(m.ac_polarity, POLARITY_ABOVE_DC)

    def test_above_dc_pulse_rides_up(self):
        m = PPGModel(); m.set_polarity(POLARITY_ABOVE_DC)
        m.set_perfusion_index(6.0)     # sizeable AC so the pulse is clear
        _, _, disp_ir, _ = _run_cycles(m, 1500)
        # Pulse-up: the display AC swings clearly positive.
        self.assertGreater(max(disp_ir), 0.02)

    def test_below_dc_pulse_dips_down(self):
        m = PPGModel(); m.set_polarity(POLARITY_BELOW_DC)
        m.set_perfusion_index(6.0)
        _, _, disp_ir, _ = _run_cycles(m, 1500)
        # Pulse-down: the display AC swings clearly negative.
        self.assertLess(min(disp_ir), -0.02)

    def test_polarity_flips_sign_of_ac(self):
        # Same seed-independent structure: above vs below mirror on the AC term.
        m_up = PPGModel(); m_up.set_polarity(POLARITY_ABOVE_DC); m_up.set_perfusion_index(6.0)
        m_dn = PPGModel(); m_dn.set_polarity(POLARITY_BELOW_DC); m_dn.set_perfusion_index(6.0)
        _, _, up, _ = _run_cycles(m_up, 1000)
        _, _, dn, _ = _run_cycles(m_dn, 1000)
        # Above-DC reaches a positive peak; below-DC reaches a negative trough.
        self.assertGreater(max(up), 0.0)
        self.assertLess(min(dn), 0.0)


# ─────────────── invalid / non-physical combinations ───────────────
class TestInvalidCombinations(unittest.TestCase):
    def test_validate_ac_dc_rejects_bad(self):
        bad_cases = [
            (0.0, -100.0),     # DC <= 0
            (0.0, 4000.0),     # DC > full-scale (3280 mV)
            (200.0, 3200.0),   # DC + AC > full-scale
            (200.0, 100.0),    # DC - AC < 0 (envelope underflow)
            (-5.0, 1500.0),    # AC < 0
        ]
        for ac, dc in bad_cases:
            with self.assertRaises(ValueError):
                validate_ac_dc(ac, dc)

    def test_validate_ac_dc_rejects_nonfinite(self):
        for ac, dc in ((math.nan, 1500.0), (100.0, math.inf), (math.inf, 1500.0)):
            with self.assertRaises(ValueError):
                validate_ac_dc(ac, dc)

    def test_validate_ac_dc_accepts_valid(self):
        ac, dc = validate_ac_dc(45.0, 1500.0)
        self.assertEqual((ac, dc), (45.0, 1500.0))
        # Boundary: DC + AC exactly at full-scale is allowed.
        validate_ac_dc(200.0, 3000.0)

    def test_perfusion_index_from_ac_dc_rejects_bad(self):
        for ac, dc in ((45.0, 0.0), (45.0, -1.0), (-1.0, 1500.0),
                       (math.nan, 1500.0), (45.0, math.inf)):
            with self.assertRaises(ValueError):
                perfusion_index_from_ac_dc(ac, dc)

    def test_ratio_of_ratios_rejects_bad(self):
        # Zero/negative DC on either channel, or non-positive IR AC (division).
        for args in ((45.0, 0.0, 30.0, 1500.0),
                     (45.0, 1500.0, 30.0, 0.0),
                     (45.0, 1500.0, 0.0, 1500.0),
                     (45.0, 1500.0, -1.0, 1500.0)):
            with self.assertRaises(ValueError):
                ratio_of_ratios(*args)

    def test_ac_red_from_target_rejects_bad(self):
        for args in ((0.8, 30.0, 900.0, 0.0),     # DC_ir = 0
                     (0.8, 30.0, 0.0, 1500.0),     # DC_red = 0
                     (-0.1, 30.0, 900.0, 1500.0),  # negative R
                     (0.8, -1.0, 900.0, 1500.0)):  # negative AC_ir
            with self.assertRaises(ValueError):
                ac_red_from_target(*args)

    def test_model_setters_reject_bad(self):
        m = PPGModel()
        with self.assertRaises(ValueError):
            m.set_ac_dc(200.0, 3100.0)          # envelope over full-scale
        with self.assertRaises(ValueError):
            m.set_dc_levels(4000.0)             # DC over full-scale
        with self.assertRaises(ValueError):
            m.set_dc_levels(1500.0, -5.0)       # Red DC <= 0
        with self.assertRaises(ValueError):
            m.set_polarity(7)                   # unknown polarity enum


# ─────────────── backward compatibility (equal-DC legacy) ───────────────
class TestBackwardCompat(unittest.TestCase):
    def test_default_dc_reproduces_legacy_ac_scale(self):
        # Legacy: AC_ir = PI × 0.015 V at the shared 1.5 V DC baseline.
        m = PPGModel()
        self.assertAlmostEqual(m.dc_ir, DEFAULT_DC_BASELINE_V)
        m.set_perfusion_index(3.0)
        self.assertAlmostEqual(m.get_ac_amplitude(), 3.0 * 0.015)
        m.set_perfusion_index(10.0)
        self.assertAlmostEqual(m.get_ac_amplitude(), 10.0 * 0.015)

    def test_default_equal_dc_matches_simple_product(self):
        # At equal DC, AC_red = R·AC_ir (the pre-Phase-3 simplification).
        r = 0.8
        ac_ir = 0.045
        self.assertAlmostEqual(
            ac_red_from_target(r, ac_ir, 1.5, 1.5), r * ac_ir)

    def test_params_defaults(self):
        p = PPGParameters()
        self.assertEqual(p.dc_ir_mv, 1500.0)
        self.assertEqual(p.dc_red_mv, 1500.0)
        self.assertEqual(p.ac_polarity, POLARITY_ABOVE_DC)
        # copy() preserves the new fields.
        c = p.copy()
        self.assertEqual(c.dc_ir_mv, 1500.0)
        self.assertEqual(c.dc_red_mv, 1500.0)
        self.assertEqual(c.ac_polarity, POLARITY_ABOVE_DC)


if __name__ == "__main__":
    unittest.main(verbosity=2)
