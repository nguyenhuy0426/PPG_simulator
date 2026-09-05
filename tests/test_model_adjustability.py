"""
tests/test_model_adjustability.py — every AECG100 parameter is reachable.

The commercial reference (WhaleTeq AECG100, user_manual.pdf Tables 7/10/11/13)
lets the operator set heart rate, respiration rate, SpO2, PI, per-channel AC
and DC, an output DC offset, the pulse feature times, the waveform kind and the
artefact independently. This module asserts our model exposes the same span and
that each setting actually reaches the generated waveform — a setter that
stores a value nothing consumes is not an adjustable parameter.

Runnable with either:
    python3 -m unittest tests.test_model_adjustability -v
    pytest tests/test_model_adjustability.py -v
"""

import math
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from models import limits
from models.ppg_model import PPGModel, PPGParameters, COND_NORMAL
from models.respiration import RespirationConfig
from models.waveform import WAVE_PPG, WAVE_SINE, WAVE_SQUARE, WAVE_TRIANGLE

DT = 0.01


def _quiet_model(hr=60.0, pi=3.0):
    """A model with every stochastic and modulating source switched off.

    Beat-to-beat variability, respiration and noise all move the amplitude
    around; none of them are what these tests measure.
    """
    model = PPGModel()
    params = PPGParameters()
    params.condition = COND_NORMAL
    params.heart_rate = hr
    params.perfusion_index = pi
    params.spo2 = 98.0
    params.noise_level = 0.0
    model.set_parameters(params)
    model.hr_amplitude_enabled = False
    model.set_respiration(RespirationConfig(
        baseline_enabled=False, amplitude_enabled=False, frequency_enabled=False))
    model.cond_ranges.pi_cv = 0.0
    model.cond_ranges.hr_cv = 0.0
    model.set_heart_rate(hr)
    model.reset()
    return model


def _run(model, seconds, dt=DT):
    return [model.generate_both_samples(dt) for _ in range(int(seconds / dt))]


def _ac_swing_mv(model, seconds=4.0):
    """Peak-to-peak of the IR display signal (AC only, no DC), in mV."""
    disp = [s[2] for s in _run(model, seconds)]
    return (max(disp) - min(disp)) * 1000.0


class TestHeartRateRange(unittest.TestCase):
    def test_accepts_the_full_aecg100_span(self):
        model = PPGModel()
        for hr in (10.0, 60.0, 150.0, 300.0):
            model.set_heart_rate(hr)
            self.assertAlmostEqual(model.params.heart_rate, hr)

    def test_clamps_outside_the_span(self):
        model = PPGModel()
        model.set_heart_rate(1.0)
        self.assertEqual(model.params.heart_rate, limits.HEART_RATE.minimum)
        model.set_heart_rate(1000.0)
        self.assertEqual(model.params.heart_rate, limits.HEART_RATE.maximum)

    def test_high_rate_actually_beats_faster(self):
        slow = _quiet_model(hr=60.0)
        fast = _quiet_model(hr=240.0)
        _run(slow, 4.0)
        _run(fast, 4.0)
        self.assertGreater(fast.beat_count, slow.beat_count * 3)


class TestPerfusionIndexRange(unittest.TestCase):
    def test_accepts_the_full_aecg100_span(self):
        model = PPGModel()
        for pi in (0.01, 2.0, 30.0):
            model.set_perfusion_index(pi)
            self.assertAlmostEqual(model.params.perfusion_index, pi)

    def test_clamps_outside_the_span(self):
        model = PPGModel()
        model.set_perfusion_index(0.0)
        self.assertEqual(model.params.perfusion_index, limits.PERFUSION_INDEX.minimum)
        model.set_perfusion_index(99.0)
        self.assertEqual(model.params.perfusion_index, limits.PERFUSION_INDEX.maximum)

    def test_low_pi_reaches_the_waveform(self):
        model = _quiet_model(pi=0.05)
        # PI 0.05 % of a 1500 mV DC is 0.75 mV of AC.
        self.assertAlmostEqual(_ac_swing_mv(model), 0.75, delta=0.05)


class TestRespirationRate(unittest.TestCase):
    def test_accepts_the_full_span(self):
        model = PPGModel()
        for rr in (1.0, 20.0, 150.0):
            model.set_resp_rate(rr)
            self.assertAlmostEqual(model.params.resp_rate, rr)

    def test_out_of_range_raises(self):
        model = PPGModel()
        with self.assertRaises(ValueError):
            model.set_resp_rate(0.0)
        with self.assertRaises(ValueError):
            model.set_resp_rate(200.0)

    def test_rate_reaches_the_modulation(self):
        model = _quiet_model()
        model.set_respiration(RespirationConfig(
            rate_brpm=60.0, baseline_enabled=False, frequency_enabled=False))
        model.set_resp_rate(60.0)
        _run(model, 0.5)
        # Half a breath at 60 BrPM. Asserting a whole cycle would sit on the
        # 0.0/1.0 wrap, where float accumulation decides which side we land on.
        self.assertAlmostEqual(model.respiration.phase, 0.5, delta=0.05)


class TestSpO2Range(unittest.TestCase):
    def test_accepts_the_full_span(self):
        model = PPGModel()
        for spo2 in (0.0, 70.0, 100.0):
            model.set_spo2(spo2)
            self.assertAlmostEqual(model.params.spo2, spo2)

    def test_out_of_range_raises(self):
        model = PPGModel()
        with self.assertRaises(ValueError):
            model.set_spo2(-1.0)
        with self.assertRaises(ValueError):
            model.set_spo2(101.0)


class TestAcDcMastering(unittest.TestCase):
    def test_ac_level_reaches_the_output(self):
        model = _quiet_model()
        model.set_ac_levels(20.0)
        self.assertAlmostEqual(_ac_swing_mv(model), 20.0, delta=0.5)

    def test_ac_span_covers_the_aecg100_range(self):
        model = _quiet_model()
        for ac_mv in (0.1, 30.0, 300.0):
            model.set_ac_levels(ac_mv)
            self.assertAlmostEqual(model.params.ac_ir_mv, ac_mv)

    def test_ac_out_of_range_raises(self):
        model = _quiet_model()
        with self.assertRaises(ValueError):
            model.set_ac_levels(0.0)
        with self.assertRaises(ValueError):
            model.set_ac_levels(500.0)

    def test_independent_red_ac_is_kept(self):
        model = _quiet_model()
        model.set_ac_levels(20.0, 10.0)
        self.assertAlmostEqual(model.params.ac_ir_mv, 20.0)
        self.assertAlmostEqual(model.params.ac_red_mv, 10.0)
        disp_red = [s[3] for s in _run(model, 4.0)]
        self.assertAlmostEqual((max(disp_red) - min(disp_red)) * 1000.0, 10.0, delta=0.5)

    def test_red_ac_follows_spo2_when_not_pinned(self):
        """Default behaviour: Red AC is derived from the SpO2 target."""
        model = _quiet_model()
        model.set_ac_levels(20.0)
        self.assertIsNone(model.params.ac_red_mv)
        model.set_spo2(80.0)
        disp_red = [s[3] for s in _run(model, 4.0)]
        red_swing = (max(disp_red) - min(disp_red)) * 1000.0
        # R = (110-80)/25 = 1.2 at equal DC -> AC_red = 1.2 * AC_ir
        self.assertAlmostEqual(red_swing, 24.0, delta=0.6)

    def test_setting_pi_updates_the_ac_master(self):
        model = _quiet_model()
        model.set_perfusion_index(2.0)
        # 2 % of 1500 mV DC
        self.assertAlmostEqual(model.params.ac_ir_mv, 30.0, delta=0.01)

    def test_lock_ac_makes_a_dc_change_move_pi_not_ac(self):
        model = _quiet_model()
        model.set_ac_levels(45.0)
        model.set_lock(lock_ac=True)
        model.set_dc_levels(3000.0)
        self.assertAlmostEqual(model.params.ac_ir_mv, 45.0)
        self.assertAlmostEqual(model.params.perfusion_index, 1.5, delta=0.01)

    def test_unlocked_dc_change_holds_pi_and_moves_ac(self):
        model = _quiet_model()
        model.set_perfusion_index(3.0)
        model.set_dc_levels(1000.0)
        self.assertAlmostEqual(model.params.perfusion_index, 3.0)
        self.assertAlmostEqual(model.params.ac_ir_mv, 30.0, delta=0.01)

    def test_dc_span_covers_the_aecg100_range(self):
        model = _quiet_model()
        for dc_mv in (100.0, 625.0, 3000.0):
            model.set_dc_levels(dc_mv)
            self.assertAlmostEqual(model.params.dc_ir_mv, dc_mv)


class TestOutputDcOffset(unittest.TestCase):
    def test_offset_shifts_the_output(self):
        model = _quiet_model()
        model.set_dc_levels(1000.0)
        base = [s[0] for s in _run(model, 2.0)]
        model.set_output_dc_offset(500.0)
        shifted = [s[0] for s in _run(model, 2.0)]
        self.assertAlmostEqual(min(shifted) - min(base), 0.5, delta=0.01)

    def test_offset_does_not_change_the_ac_swing(self):
        model = _quiet_model()
        model.set_dc_levels(1000.0)
        before = _ac_swing_mv(model)
        model.set_output_dc_offset(500.0)
        self.assertAlmostEqual(_ac_swing_mv(model), before, delta=0.01)

    def test_dc_plus_offset_over_the_ceiling_raises(self):
        model = _quiet_model()
        model.set_dc_levels(2500.0)
        with self.assertRaises(ValueError):
            model.set_output_dc_offset(1000.0)   # 3500 > 3000 mV ceiling

    def test_offset_span(self):
        model = _quiet_model()
        model.set_dc_levels(500.0)
        model.set_output_dc_offset(2000.0)
        self.assertAlmostEqual(model.params.output_dc_offset_mv, 2000.0)
        with self.assertRaises(ValueError):
            model.set_output_dc_offset(2500.0)


class TestAmplificationAndNotch(unittest.TestCase):
    def test_amplification_scales_the_ac(self):
        model = _quiet_model()
        model.set_ac_levels(20.0)
        base = _ac_swing_mv(model)
        model.set_amplification(2.0)
        self.assertAlmostEqual(_ac_swing_mv(model), base * 2.0, delta=0.5)

    def test_amplification_out_of_range_raises(self):
        model = _quiet_model()
        with self.assertRaises(ValueError):
            model.set_amplification(0.0)
        with self.assertRaises(ValueError):
            model.set_amplification(10.0)

    def test_dicrotic_notch_setting_changes_the_notch(self):
        model = _quiet_model()
        model.set_dicrotic_notch(0.0)
        flat = [s[2] for s in _run(model, 2.0)]
        model.set_dicrotic_notch(0.5)
        deep = [s[2] for s in _run(model, 2.0)]
        # The shape is clamped to [0, 1], so both troughs bottom out at exactly
        # zero and min() cannot tell them apart. A deeper notch removes area
        # from the middle of every cycle, so compare the cycle mean instead.
        self.assertLess(sum(deep) / len(deep), sum(flat) / len(flat))

    def test_notch_out_of_range_raises(self):
        model = _quiet_model()
        with self.assertRaises(ValueError):
            model.set_dicrotic_notch(-0.1)
        with self.assertRaises(ValueError):
            model.set_dicrotic_notch(1.5)


class TestWaveformKind(unittest.TestCase):
    def test_default_is_ppg(self):
        self.assertEqual(PPGModel().params.waveform, WAVE_PPG)

    def test_every_aecg100_kind_is_selectable(self):
        model = _quiet_model()
        for kind in (WAVE_PPG, WAVE_SINE, WAVE_TRIANGLE, WAVE_SQUARE):
            model.set_waveform(kind)
            self.assertEqual(model.params.waveform, kind)

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            _quiet_model().set_waveform("sawtooth")

    def test_square_output_is_two_valued(self):
        model = _quiet_model(hr=60.0)
        model.set_waveform(WAVE_SQUARE)
        model.set_ac_levels(20.0)
        disp = [round(s[2] * 1000.0, 3) for s in _run(model, 3.0)]
        self.assertLessEqual(len(set(disp)), 3)   # low, high (and the odd edge)

    def test_sine_output_has_no_dicrotic_notch(self):
        model = _quiet_model(hr=60.0)
        model.set_waveform(WAVE_SINE)
        model.set_ac_levels(20.0)
        disp = [s[2] for s in _run(model, 1.0)]
        # A sine rises then falls exactly once per cycle: one sign change of
        # the first difference. A PPG pulse has three.
        diffs = [b - a for a, b in zip(disp, disp[1:])]
        changes = sum(1 for a, b in zip(diffs, diffs[1:]) if a > 0 > b or a < 0 < b)
        self.assertLessEqual(changes, 2)


class TestFeatureTimes(unittest.TestCase):
    def test_default_times_match_allen_2007(self):
        model = PPGModel()
        self.assertAlmostEqual(model.params.sp_ms_ir, 150.0)
        self.assertAlmostEqual(model.params.dn_ms_ir, 300.0)
        self.assertAlmostEqual(model.params.dp_ms_ir, 400.0)

    def test_systolic_time_moves_the_peak(self):
        model = _quiet_model(hr=60.0)
        model.set_feature_times("ir", 300.0, 450.0, 550.0)
        disp = [s[2] for s in _run(model, 2.0)][100:200]   # one settled cycle
        peak_idx = disp.index(max(disp))
        self.assertAlmostEqual(peak_idx / 100.0, 0.30, delta=0.04)

    def test_channels_are_independent(self):
        model = _quiet_model(hr=60.0)
        model.set_feature_times("red", 400.0, 600.0, 700.0)
        self.assertAlmostEqual(model.params.sp_ms_red, 400.0)
        self.assertAlmostEqual(model.params.sp_ms_ir, 150.0)

    def test_out_of_order_times_raise(self):
        model = _quiet_model()
        with self.assertRaises(ValueError):
            model.set_feature_times("ir", 400.0, 300.0, 500.0)

    def test_unknown_channel_raises(self):
        model = _quiet_model()
        with self.assertRaises(ValueError):
            model.set_feature_times("green", 150.0, 300.0, 400.0)


class TestRespirationIntegration(unittest.TestCase):
    def test_variation_percent_sets_the_amplitude_depth(self):
        # 60 BPM puts phase 0.15 exactly on a 10 ms sample, so the measured
        # peak is the true peak. At 240 BPM the grid misses it by ~1.6 %,
        # which is most of the modulation depth under test.
        model = _quiet_model(hr=60.0)
        model.set_ac_levels(20.0)
        model.set_respiration(RespirationConfig(
            rate_brpm=15.0, variation_ir_pct=16.0,
            baseline_enabled=False, frequency_enabled=False))
        peaks = []
        for _ in range(int(8.0 / DT)):
            model.generate_both_samples(DT)
            peaks.append(model.last_display_ir)
        # +/-16 % of a 20 mV AC -> the tallest beat is ~1.16 x the nominal.
        self.assertAlmostEqual(max(peaks) * 1000.0, 20.0 * 1.16, delta=0.4)

    def test_disabling_every_modulation_gives_a_steady_amplitude(self):
        model = _quiet_model(hr=60.0)
        model.set_ac_levels(20.0)
        peaks = []
        for _ in range(int(10.0 / DT)):
            model.generate_both_samples(DT)
            peaks.append(model.last_display_ir)
        self.assertAlmostEqual(max(peaks) * 1000.0, 20.0, delta=0.2)

    def test_apnea_is_reachable_from_the_model(self):
        model = _quiet_model()
        model.set_respiration(RespirationConfig(
            apnea_enabled=True, apnea_duration_s=30.0, apnea_cycle_min=1.0))
        self.assertTrue(model.respiration.config.apnea_enabled)
        self.assertEqual(model.respiration.config.apnea_duration_s, 30.0)
        # ... and it is mirrored onto params so config_store persists it.
        self.assertTrue(model.params.apnea_enabled)
        self.assertEqual(model.params.apnea_duration_s, 30.0)


class TestParameterPersistence(unittest.TestCase):
    def test_every_new_field_round_trips(self):
        import config_store
        params = PPGParameters()
        params.waveform = WAVE_TRIANGLE
        params.ac_ir_mv = 22.5
        params.ac_red_mv = 11.0
        params.output_dc_offset_mv = 250.0
        params.sp_ms_ir = 160.0
        params.dn_ms_ir = 330.0
        params.dp_ms_ir = 430.0
        params.sp_ms_red = 170.0
        params.dn_ms_red = 340.0
        params.dp_ms_red = 440.0
        params.resp_ie_ratio = 3
        params.resp_variation_ir_pct = 9.0
        params.resp_variation_red_pct = 7.0
        params.resp_mod_frequency = False
        params.apnea_enabled = True
        params.apnea_duration_s = 20.0
        params.apnea_cycle_min = 2.0
        params.lock_ac = True
        params.lock_dc = True

        cfg = config_store.config_from_ppg_params(params)
        restored = PPGParameters()
        config_store.apply_config_to_params(cfg, restored)

        for field in ("waveform", "ac_ir_mv", "ac_red_mv", "output_dc_offset_mv",
                      "sp_ms_ir", "dn_ms_ir", "dp_ms_ir",
                      "sp_ms_red", "dn_ms_red", "dp_ms_red",
                      "resp_ie_ratio", "resp_variation_ir_pct",
                      "resp_variation_red_pct", "resp_mod_frequency",
                      "apnea_enabled", "apnea_duration_s", "apnea_cycle_min",
                      "lock_ac", "lock_dc"):
            with self.subTest(field=field):
                self.assertEqual(getattr(restored, field), getattr(params, field))

    def test_a_legacy_config_still_loads(self):
        import config_store
        params = PPGParameters()
        config_store.apply_config_to_params({"heart_rate": 80.0}, params)
        self.assertEqual(params.heart_rate, 80.0)
        self.assertEqual(params.waveform, WAVE_PPG)
        self.assertEqual(params.output_dc_offset_mv, 0.0)

    def test_a_corrupt_waveform_falls_back_to_ppg(self):
        import config_store
        params = PPGParameters()
        config_store.apply_config_to_params({"waveform": "spiral"}, params)
        self.assertEqual(params.waveform, WAVE_PPG)

    def test_noise_settings_round_trip(self):
        import config_store
        params = PPGParameters()
        params.noise_kind = "white"
        params.noise_amplitude_mv = 1.25
        params.noise_freq_hz = 5.0
        params.noise_seed = 7
        cfg = config_store.config_from_ppg_params(params)
        restored = PPGParameters()
        config_store.apply_config_to_params(cfg, restored)
        self.assertEqual(restored.noise_kind, "white")
        self.assertEqual(restored.noise_amplitude_mv, 1.25)
        self.assertEqual(restored.noise_freq_hz, 5.0)
        self.assertEqual(restored.noise_seed, 7)


class TestBackwardCompatibility(unittest.TestCase):
    def test_default_model_still_produces_the_legacy_ac_scale(self):
        model = PPGModel()
        model.set_perfusion_index(3.0)
        self.assertAlmostEqual(model.get_ac_amplitude(), 3.0 * 0.015)

    def test_default_waveform_still_peaks_at_unity(self):
        model = PPGModel()
        peak = max(model._compute_pulse_shape(i / 2000.0) for i in range(2000))
        self.assertAlmostEqual(peak, 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main(verbosity=2)
