"""
tests/test_respiration.py — respiratory modulation and apnea (AECG100 parity).

Covers the AECG100 "Respiration" and "Apnea" sections (user_manual.pdf Table 7):
  - rate 1-150 BrPM
  - inhale-exhale ratio 1:1 .. 1:5
  - Wave Modulation Baseline / Amplitude / Frequency, independently selectable
  - per-channel Variation R / IR, 1-16 %
  - apnea duration 1-60 s on a 1-10 min cycle

Runnable with either:
    python3 -m unittest tests.test_respiration -v
    pytest tests/test_respiration.py -v
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from models import respiration
from models.respiration import RespirationConfig, RespirationModulator

DT = 0.01  # 10 ms, the model tick


def _run(modulator, seconds, dt=DT):
    """Advance the modulator and return every state it produced."""
    return [modulator.advance(dt) for _ in range(int(seconds / dt))]


class TestConfigValidation(unittest.TestCase):
    def test_defaults_are_valid(self):
        RespirationConfig().validate()

    def test_all_three_modulations_default_on(self):
        cfg = RespirationConfig()
        self.assertTrue(cfg.baseline_enabled)
        self.assertTrue(cfg.amplitude_enabled)
        self.assertTrue(cfg.frequency_enabled)

    def test_rate_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            RespirationConfig(rate_brpm=200.0).validate()
        with self.assertRaises(ValueError):
            RespirationConfig(rate_brpm=0.0).validate()

    def test_rate_at_aecg100_bounds_is_accepted(self):
        RespirationConfig(rate_brpm=1.0).validate()
        RespirationConfig(rate_brpm=150.0).validate()

    def test_unsupported_inhale_exhale_ratio_raises(self):
        with self.assertRaises(ValueError):
            RespirationConfig(inhale_exhale_ratio=7).validate()

    def test_variation_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            RespirationConfig(variation_ir_pct=20.0).validate()

    def test_apnea_bounds(self):
        RespirationConfig(apnea_enabled=True, apnea_duration_s=60.0,
                          apnea_cycle_min=10.0).validate()
        with self.assertRaises(ValueError):
            RespirationConfig(apnea_enabled=True, apnea_duration_s=90.0).validate()

    def test_apnea_longer_than_its_cycle_raises(self):
        with self.assertRaises(ValueError):
            RespirationConfig(apnea_enabled=True, apnea_duration_s=60.0,
                              apnea_cycle_min=1.0 / 60.0).validate()

    def test_replace_returns_new_config(self):
        cfg = RespirationConfig()
        other = cfg.replace(rate_brpm=30.0)
        self.assertEqual(cfg.rate_brpm, 16.0)
        self.assertEqual(other.rate_brpm, 30.0)


class TestPhaseAdvance(unittest.TestCase):
    def test_completes_one_cycle_per_breath(self):
        mod = RespirationModulator(RespirationConfig(rate_brpm=60.0))  # 1 breath/s
        states = _run(mod, 1.0)
        self.assertAlmostEqual(states[-1].cycles, 1.0, delta=0.02)

    def test_rate_change_does_not_jump_the_phase(self):
        mod = RespirationModulator(RespirationConfig(rate_brpm=12.0))
        _run(mod, 2.0)
        before = mod.phase
        mod.config = RespirationConfig(rate_brpm=60.0)
        after = mod.advance(DT).phase
        self.assertLess(abs(after - before), 0.05)

    def test_reset_returns_to_zero(self):
        mod = RespirationModulator()
        _run(mod, 3.0)
        mod.reset()
        self.assertEqual(mod.phase, 0.0)


class TestInhaleExhaleRatio(unittest.TestCase):
    def test_one_to_one_is_symmetric(self):
        mod = RespirationModulator(RespirationConfig(rate_brpm=60.0,
                                                     inhale_exhale_ratio=1))
        states = _run(mod, 1.0)
        rising = sum(1 for a, b in zip(states, states[1:]) if b.drive > a.drive)
        self.assertAlmostEqual(rising / float(len(states)), 0.5, delta=0.05)

    def test_one_to_four_has_a_short_inhale(self):
        mod = RespirationModulator(RespirationConfig(rate_brpm=60.0,
                                                     inhale_exhale_ratio=4))
        states = _run(mod, 1.0)
        rising = sum(1 for a, b in zip(states, states[1:]) if b.drive > a.drive)
        self.assertAlmostEqual(rising / float(len(states)), 0.2, delta=0.05)

    def test_drive_stays_bounded_for_every_ratio(self):
        for ratio in (1, 2, 3, 4, 5):
            with self.subTest(ratio=ratio):
                mod = RespirationModulator(
                    RespirationConfig(rate_brpm=60.0, inhale_exhale_ratio=ratio))
                drives = [s.drive for s in _run(mod, 2.0)]
                self.assertGreaterEqual(min(drives), -1.0001)
                self.assertLessEqual(max(drives), 1.0001)
                self.assertGreater(max(drives), 0.9)
                self.assertLess(min(drives), -0.9)


class TestModulationSelection(unittest.TestCase):
    def test_baseline_disabled_gives_zero_baseline(self):
        mod = RespirationModulator(RespirationConfig(baseline_enabled=False))
        for state in _run(mod, 5.0):
            self.assertEqual(state.baseline_ir, 0.0)
            self.assertEqual(state.baseline_red, 0.0)

    def test_amplitude_disabled_gives_unity_factor(self):
        mod = RespirationModulator(RespirationConfig(amplitude_enabled=False))
        for state in _run(mod, 5.0):
            self.assertEqual(state.amplitude_ir, 1.0)
            self.assertEqual(state.amplitude_red, 1.0)

    def test_frequency_disabled_gives_unity_factor(self):
        mod = RespirationModulator(RespirationConfig(frequency_enabled=False))
        for state in _run(mod, 5.0):
            self.assertEqual(state.interval_factor, 1.0)

    def test_all_disabled_is_a_flat_signal(self):
        mod = RespirationModulator(RespirationConfig(
            baseline_enabled=False, amplitude_enabled=False,
            frequency_enabled=False))
        for state in _run(mod, 3.0):
            self.assertEqual(state.baseline_ir, 0.0)
            self.assertEqual(state.amplitude_ir, 1.0)
            self.assertEqual(state.interval_factor, 1.0)


class TestVariationDepth(unittest.TestCase):
    def test_amplitude_depth_follows_variation_percent(self):
        mod = RespirationModulator(RespirationConfig(
            rate_brpm=60.0, variation_ir_pct=10.0, variation_red_pct=10.0,
            baseline_enabled=False, frequency_enabled=False))
        factors = [s.amplitude_ir for s in _run(mod, 4.0)]
        self.assertAlmostEqual(max(factors), 1.10, delta=0.01)
        self.assertAlmostEqual(min(factors), 0.90, delta=0.01)

    def test_channels_can_have_different_depths(self):
        mod = RespirationModulator(RespirationConfig(
            rate_brpm=60.0, variation_ir_pct=16.0, variation_red_pct=2.0,
            baseline_enabled=False, frequency_enabled=False))
        states = _run(mod, 4.0)
        ir_swing = max(s.amplitude_ir for s in states) - min(s.amplitude_ir for s in states)
        red_swing = max(s.amplitude_red for s in states) - min(s.amplitude_red for s in states)
        self.assertGreater(ir_swing, red_swing * 4)

    def test_zero_variation_is_neutral(self):
        mod = RespirationModulator(RespirationConfig(
            variation_ir_pct=0.0, variation_red_pct=0.0))
        for state in _run(mod, 3.0):
            self.assertAlmostEqual(state.amplitude_ir, 1.0)
            self.assertAlmostEqual(state.baseline_ir, 0.0)


class TestApnea(unittest.TestCase):
    def test_disabled_by_default(self):
        mod = RespirationModulator()
        self.assertFalse(any(s.in_apnea for s in _run(mod, 10.0)))

    def test_apnea_occurs_once_per_cycle(self):
        # 30 s of apnea on the 1 min cycle: half the run, plus the 1 s fade-out
        # that already counts as apnea because the depth is no longer full.
        cfg = RespirationConfig(apnea_enabled=True, apnea_duration_s=30.0,
                                apnea_cycle_min=1.0)
        mod = RespirationModulator(cfg)
        states = _run(mod, 120.0, dt=0.05)
        apnea_fraction = sum(1 for s in states if s.in_apnea) / float(len(states))
        self.assertAlmostEqual(apnea_fraction, 0.5, delta=0.06)

    def test_modulation_is_suppressed_during_apnea(self):
        cfg = RespirationConfig(apnea_enabled=True, apnea_duration_s=30.0,
                                apnea_cycle_min=1.0, rate_brpm=60.0)
        mod = RespirationModulator(cfg)
        dt = 0.02
        states = _run(mod, 60.0, dt=dt)
        # Apnea runs 30-60 s; sample 35-55 s, clear of both blend ramps.
        deep = states[int(35.0 / dt):int(55.0 / dt)]
        self.assertTrue(deep)
        for state in deep:
            self.assertTrue(state.in_apnea)
            self.assertAlmostEqual(state.amplitude_ir, 1.0, places=3)
            self.assertAlmostEqual(state.baseline_ir, 0.0, places=4)
            self.assertAlmostEqual(state.interval_factor, 1.0, places=4)

    def test_apnea_onset_is_blended_not_stepped(self):
        """A hard cut to zero would be a step artefact at the DAC output."""
        cfg = RespirationConfig(apnea_enabled=True, apnea_duration_s=30.0,
                                apnea_cycle_min=1.0, rate_brpm=30.0,
                                variation_ir_pct=16.0)
        mod = RespirationModulator(cfg)
        states = _run(mod, 70.0, dt=0.01)
        jumps = [abs(b.amplitude_ir - a.amplitude_ir)
                 for a, b in zip(states, states[1:])]
        self.assertLess(max(jumps), 0.02)


class TestModulationConstants(unittest.TestCase):
    def test_modulation_kind_names(self):
        self.assertEqual(
            set(respiration.MODULATION_KINDS),
            {respiration.MOD_BASELINE, respiration.MOD_AMPLITUDE,
             respiration.MOD_FREQUENCY},
        )

    def test_enabled_modulations_reports_the_selection(self):
        cfg = RespirationConfig(amplitude_enabled=False)
        self.assertEqual(cfg.enabled_modulations(),
                         (respiration.MOD_BASELINE, respiration.MOD_FREQUENCY))


if __name__ == "__main__":
    unittest.main()
