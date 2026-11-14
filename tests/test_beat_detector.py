"""Pulse tone detector: one beat per received pulse, within ~0.2 s of the peak, silent on noise."""
import random

import pytest

from core.beat_detector import BeatDetector
from models.ppg_model import CONDITION_NAMES, PPGModel, PPGParameters


def pulse_wave(hr, seconds, ac=50.0, condition=0):
    random.seed(1000 * condition + int(hr))       # the model's beat-to-beat variation uses the global random
    m, p = PPGModel(), PPGParameters()
    p.condition, p.heart_rate, p.dc_ir_mv, p.ac_ir_mv, p.noise_level = condition, hr, 1000.0, ac, 0.0
    m.set_parameters(p)
    if condition == 0:
        m.set_heart_rate(hr)
    out = []
    for i in range(int(seconds * 200)):
        ir, *_ = m.generate_both_samples(1 / 200)
        if i % 2 == 0:
            out.append(ir * 1000)
    return out, m.beat_count


def rx_like(values, seed=2):
    """1 mV white noise plus 1-3 sample spikes of 15-100 mV ~1.4/s, as measured on the Pi RX lanes."""
    rng = random.Random(seed)
    out = [v + rng.gauss(0, 1) for v in values]
    for k in range(50, len(out) - 4, 70):
        for j in range(rng.randint(1, 3)):
            out[k + j] += rng.choice((-1, 1)) * rng.uniform(15, 100)
    return out


def detect(values, hz=100.0):
    d, beats, latency = BeatDetector(), [], []
    for i, v in enumerate(values):
        beat = d.feed(i / hz, v)
        if beat is not None:
            beats.append(beat)
            latency.append(i / hz - beat)
    return beats, latency


def gaps(beats):
    return [b - a for a, b in zip(beats, beats[1:])]


@pytest.mark.parametrize("hr", (30, 75, 150, 300))
def test_one_tone_per_beat_after_lock(hr):
    values, model_beats = pulse_wave(hr, 30)
    beats, latency = detect(rx_like(values))
    period = 60.0 / hr
    assert beats and beats[0] < 4 * period + 1.0                 # locks within ~4 beats
    assert all(g > .6 * period for g in gaps(beats))                 # never two tones for one beat
    assert sum(g > 1.5 * period for g in gaps(beats)) <= .02 * len(beats)   # misses < 2 %
    assert len(beats) >= .95 * model_beats - 5
    assert sorted(latency)[len(latency) // 2] < max(.25, .4 * period)


@pytest.mark.parametrize("condition", range(1, len(CONDITION_NAMES)))
def test_condition_presets_keep_one_tone_per_beat(condition):
    values, model_beats = pulse_wave(75, 30, condition=condition)
    beats, _ = detect(rx_like(values))
    med = sorted(gaps(beats))[len(beats) // 2]
    assert len(beats) >= model_beats - 5
    assert all(.6 * med < g < 1.5 * med for g in gaps(beats))


def test_noise_spikes_and_artefact_bursts_stay_silent():
    rng = random.Random(5)
    values = [700 + rng.gauss(0, 1) + (80 if i % 70 == 0 else 0) + (rng.gauss(0, 15) if i % 500 < 100 else 0)
              for i in range(12000)]
    assert detect(values)[0] == []


def test_a_dark_lane_unlocks_and_a_return_relocks():
    values, _ = pulse_wave(90, 12)
    values = rx_like(values) + [4.0] * 500 + rx_like(pulse_wave(90, 12)[0], seed=3)
    d, beats = BeatDetector(), []
    for i, v in enumerate(values):
        beat = d.feed(i / 100, v)
        if beat is not None:
            beats.append(beat)
        if i == 1200 + 400:
            assert not d.locked                              # 4 s dark: no tone
    assert any(b > 17 for b in beats)                        # tones again after the light comes back
    assert not any(12.5 < b < 17 for b in beats)


def test_a_gap_in_the_samples_restarts_the_peak_search():
    d = BeatDetector()
    for i in range(100):
        d.feed(i / 100, 700.0 + i)                           # rising, no peak yet
    assert d.feed(5.0, 600.0) is None                        # 4 s hole then lower: not a "peak" across the hole
