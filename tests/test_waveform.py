"""
tests/test_waveform.py — waveform shape library (AECG100 parity).

Covers:
  - the four AECG100 output waveforms (PPG / Sine / Triangle / Square)
  - configurable systolic / dicrotic-notch / diastolic amplitude AND time
  - normalisation: every shape peaks at exactly 1.0 and never leaves [0, 1]
  - the millisecond<->cycle-fraction mapping the AECG100 specifies at 60 BPM

Runnable with either:
    python3 -m unittest tests.test_waveform -v
    pytest tests/test_waveform.py -v
"""

import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from models import waveform
from models.waveform import PulseMorphology, PulseShaper


def _sweep(fn, steps=2000):
    return [fn(i / float(steps)) for i in range(steps)]


class TestWaveformKinds(unittest.TestCase):
    def test_four_aecg100_waveforms_are_available(self):
        self.assertEqual(
            set(waveform.WAVEFORM_KINDS),
            {waveform.WAVE_PPG, waveform.WAVE_SINE,
             waveform.WAVE_TRIANGLE, waveform.WAVE_SQUARE},
        )

    def test_default_waveform_is_ppg(self):
        self.assertEqual(waveform.DEFAULT_WAVEFORM, waveform.WAVE_PPG)

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            waveform.validate_kind("sawtooth")

    def test_validate_kind_is_case_insensitive(self):
        self.assertEqual(waveform.validate_kind("SINE"), waveform.WAVE_SINE)


class TestSimpleShapes(unittest.TestCase):
    """Sine / triangle / square all live in [0, 1] and peak at 1.0."""

    def _assert_unit_range(self, kind):
        shaper = PulseShaper()
        values = _sweep(lambda p: shaper.sample(kind, p))
        self.assertGreaterEqual(min(values), 0.0, kind)
        self.assertLessEqual(max(values), 1.0, kind)
        self.assertAlmostEqual(max(values), 1.0, places=3, msg=kind)

    def test_sine_is_unit_range(self):
        self._assert_unit_range(waveform.WAVE_SINE)

    def test_triangle_is_unit_range(self):
        self._assert_unit_range(waveform.WAVE_TRIANGLE)

    def test_square_is_unit_range(self):
        self._assert_unit_range(waveform.WAVE_SQUARE)

    def test_square_is_binary(self):
        shaper = PulseShaper()
        values = set(round(v, 6) for v in _sweep(lambda p: shaper.sample(waveform.WAVE_SQUARE, p), 200))
        self.assertEqual(values, {0.0, 1.0})

    def test_square_duty_is_half(self):
        shaper = PulseShaper()
        values = _sweep(lambda p: shaper.sample(waveform.WAVE_SQUARE, p), 1000)
        self.assertAlmostEqual(sum(values) / len(values), 0.5, places=2)

    def test_triangle_peaks_at_midcycle(self):
        shaper = PulseShaper()
        self.assertAlmostEqual(shaper.sample(waveform.WAVE_TRIANGLE, 0.5), 1.0, places=6)
        self.assertAlmostEqual(shaper.sample(waveform.WAVE_TRIANGLE, 0.0), 0.0, places=6)

    def test_phase_wraps(self):
        shaper = PulseShaper()
        for kind in waveform.WAVEFORM_KINDS:
            with self.subTest(kind=kind):
                self.assertAlmostEqual(shaper.sample(kind, 0.25),
                                       shaper.sample(kind, 1.25), places=9)
                self.assertAlmostEqual(shaper.sample(kind, 0.25),
                                       shaper.sample(kind, -0.75), places=9)


class TestPulseMorphology(unittest.TestCase):
    def test_defaults_match_allen_2007_positions(self):
        morph = PulseMorphology()
        self.assertAlmostEqual(morph.systolic_pos, 0.15)
        self.assertAlmostEqual(morph.notch_pos, 0.30)
        self.assertAlmostEqual(morph.diastolic_pos, 0.40)

    def test_times_are_expressed_at_60_bpm(self):
        """AECG100 quotes feature times in ms at 60 BPM = a 1000 ms cycle."""
        morph = PulseMorphology()
        self.assertAlmostEqual(morph.systolic_time_ms, 150.0)
        self.assertAlmostEqual(morph.notch_time_ms, 300.0)
        self.assertAlmostEqual(morph.diastolic_time_ms, 400.0)

    def test_from_times_ms_round_trips(self):
        morph = PulseMorphology.from_times_ms(150.0, 360.0, 460.0)
        self.assertAlmostEqual(morph.systolic_pos, 0.150)
        self.assertAlmostEqual(morph.notch_pos, 0.360)
        self.assertAlmostEqual(morph.diastolic_pos, 0.460)
        self.assertAlmostEqual(morph.notch_time_ms, 360.0)

    def test_from_times_ms_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            PulseMorphology.from_times_ms(150.0, 360.0, 1500.0)

    def test_replace_returns_new_object(self):
        morph = PulseMorphology()
        other = morph.replace(diastolic_amplitude=0.6)
        self.assertAlmostEqual(morph.diastolic_amplitude, 0.4)
        self.assertAlmostEqual(other.diastolic_amplitude, 0.6)

    def test_is_frozen(self):
        with self.assertRaises(Exception):
            PulseMorphology().systolic_pos = 0.9


class TestPpgShape(unittest.TestCase):
    def test_normalised_peak_is_exactly_one(self):
        shaper = PulseShaper()
        values = _sweep(lambda p: shaper.sample(waveform.WAVE_PPG, p))
        self.assertAlmostEqual(max(values), 1.0, places=3)
        self.assertGreaterEqual(min(values), 0.0)

    def test_peak_stays_one_after_morphology_change(self):
        shaper = PulseShaper()
        shaper.morphology = PulseMorphology.from_times_ms(120.0, 300.0, 520.0).replace(
            diastolic_amplitude=0.9, dicrotic_depth=0.5)
        values = _sweep(lambda p: shaper.sample(waveform.WAVE_PPG, p))
        self.assertAlmostEqual(max(values), 1.0, places=3)

    def test_systolic_peak_lands_near_configured_time(self):
        shaper = PulseShaper()
        shaper.morphology = PulseMorphology.from_times_ms(250.0, 400.0, 500.0)
        values = _sweep(lambda p: shaper.sample(waveform.WAVE_PPG, p), 1000)
        peak_phase = values.index(max(values)) / 1000.0
        self.assertAlmostEqual(peak_phase, 0.25, delta=0.02)

    def test_notch_creates_a_local_minimum(self):
        shaper = PulseShaper()
        notch_phase = shaper.morphology.notch_pos
        at_notch = shaper.sample(waveform.WAVE_PPG, notch_phase)
        before = shaper.sample(waveform.WAVE_PPG, notch_phase - 0.05)
        after = shaper.sample(waveform.WAVE_PPG, notch_phase + 0.05)
        self.assertLess(at_notch, before)
        self.assertLess(at_notch, after)

    def test_dicrotic_factor_reduces_notch_depth(self):
        shaper = PulseShaper()
        notch_phase = shaper.morphology.notch_pos
        full = shaper.sample(waveform.WAVE_PPG, notch_phase, dicrotic_factor=1.0)
        faded = shaper.sample(waveform.WAVE_PPG, notch_phase, dicrotic_factor=0.4)
        self.assertGreater(faded, full)

    def test_dicrotic_factor_does_not_rescale_the_peak(self):
        """Notch fading must reshape the notch, not the overall amplitude."""
        shaper = PulseShaper()
        full = max(_sweep(lambda p: shaper.sample(waveform.WAVE_PPG, p, 1.0)))
        faded = max(_sweep(lambda p: shaper.sample(waveform.WAVE_PPG, p, 0.2)))
        self.assertAlmostEqual(full, faded, places=3)

    def test_degenerate_shape_does_not_divide_by_zero(self):
        shaper = PulseShaper()
        shaper.morphology = PulseMorphology().replace(
            systolic_amplitude=0.0, diastolic_amplitude=0.0, dicrotic_depth=0.0)
        self.assertEqual(shaper.sample(waveform.WAVE_PPG, 0.15), 0.0)

    def test_scale_is_cached_until_morphology_changes(self):
        shaper = PulseShaper()
        shaper.sample(waveform.WAVE_PPG, 0.15)
        first = shaper.peak_search_count
        shaper.sample(waveform.WAVE_PPG, 0.20)
        self.assertEqual(shaper.peak_search_count, first)
        shaper.morphology = shaper.morphology.replace(diastolic_amplitude=0.7)
        shaper.sample(waveform.WAVE_PPG, 0.20)
        self.assertEqual(shaper.peak_search_count, first + 1)


if __name__ == "__main__":
    unittest.main()
