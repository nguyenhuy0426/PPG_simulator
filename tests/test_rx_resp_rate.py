"""Respiratory modulation fixtures and raw-signal refusal paths."""
import math
import pytest
from core.rx_resp_rate import estimate_rx_rr
from hw.opt101_rx import RXSample


def respiratory(rate=16, modulated=True):
    out = []
    for i in range(6000):
        t = i / 100
        breath = math.sin(2 * math.pi * rate / 60 * t) if modulated else 0
        pulse = math.sin(2 * math.pi * 1.5 * t) + .2 * math.sin(4 * math.pi * 1.5 * t - 1)
        out.append(RXSample(t, round(1500 + 8 * breath + 100 * (1 + .12 * breath) * pulse), False))
    return out


@pytest.mark.parametrize('rate', [6, 12, 16, 24, 36])
def test_recovers_respiratory_modulation(rate):
    result = estimate_rx_rr(respiratory(rate), now=60)
    assert result.reason == 'ok'
    assert result.brpm == pytest.approx(rate, abs=1)


def test_missing_short_and_unmodulated_signal_does_not_invent_rr():
    assert estimate_rx_rr([], now=60).brpm is None
    assert estimate_rx_rr(respiratory()[-1000:], now=60).brpm is None
    assert estimate_rx_rr(respiratory(modulated=False), now=60).brpm is None


@pytest.mark.parametrize('fault', ['clip', 'zero', 'stale', 'invalid', 'gap'])
def test_raw_faults_prevent_estimation(fault):
    raw = respiratory()
    if fault == 'clip': raw[-10] = raw[-10]._replace(raw=4095, saturated=True)
    if fault == 'zero': raw[-10] = raw[-10]._replace(raw=0)
    if fault == 'stale': raw = raw[:-100]
    if fault == 'invalid': raw[-10] = raw[-10]._replace(raw=float('nan'))
    if fault == 'gap': raw = raw[:3000] + raw[4000:]
    assert estimate_rx_rr(raw, now=60).brpm is None


def test_dark_samples_are_not_reported_as_adc_clipping():
    # The IR lane read 0 mV within the last 30 s (LED off / dropout): no RR, and not called ADC clipping.
    raw = respiratory()
    raw[-2500:-2000] = [s._replace(raw=0) for s in raw[-2500:-2000]]
    assert estimate_rx_rr(raw, now=60).reason == 'dark'
    raw[-10] = raw[-10]._replace(raw=4095, saturated=True)
    assert estimate_rx_rr(raw, now=60).reason == 'saturated'


def test_dark_lead_in_before_start_is_skipped():
    # Output started 5 s into the window: the lit 55 s still give the rate (was 'dark' for a whole minute).
    raw = respiratory(16)
    raw[:500] = [s._replace(raw=0) for s in raw[:500]]
    result = estimate_rx_rr(raw, now=60)
    assert result.reason == 'ok' and result.brpm == pytest.approx(16, abs=1)


def test_samples_newer_than_now_are_ignored():
    # The receiver appends while the panel works: a sample after `now` was reported as 'invalid'.
    raw = respiratory(16)
    raw.append(RXSample(60.02, raw[-1].raw, False))
    assert estimate_rx_rr(raw, now=60.01).reason == 'ok'


# ---- model PPG (generator waveform + 1 mV RX noise) ----
import random
from models.ppg_model import CONDITION_NAMES, PPGModel, PPGParameters
from models.respiration import RespirationConfig


def model_rx(rr, hr=91.0, variation=4.0, condition=0, seconds=60, seed=1, breathing=True):
    random.seed(seed)
    rng = random.Random(seed)
    model, p = PPGModel(), PPGParameters()
    p.condition, p.heart_rate, p.dc_ir_mv, p.ac_ir_mv, p.noise_level = condition, hr, 1000.0, 56.0, 0.0
    model.set_parameters(p)
    if condition == 0:
        model.set_heart_rate(hr)
    model.set_respiration(RespirationConfig(rate_brpm=rr, variation_ir_pct=variation, variation_red_pct=variation,
                                            baseline_enabled=breathing, amplitude_enabled=breathing,
                                            frequency_enabled=breathing))
    out = []
    for i in range(int(seconds * 200)):
        ir, *_ = model.generate_both_samples(1 / 200)
        if i % 2 == 0:
            out.append(RXSample(i / 200, round((ir * 1000 + rng.gauss(0, 1)) / 3280 * 4095), False))
    return out


@pytest.mark.parametrize('rr', [6, 10, 15, 18, 24, 27])
def test_generator_default_4_percent_modulation_is_read_back(rr):
    raw = model_rx(rr)
    result = estimate_rx_rr(raw, now=raw[-1].timestamp)
    assert result.reason == 'ok'
    assert result.brpm == pytest.approx(rr, abs=1)


@pytest.mark.parametrize('hr,seed,condition', [(60, 1, 0), (91, 1, 0), (130, 0, 0), (91, 3, 0), (60, 2, 0),
                                               (75, 9, 1), (75, 9, 4)])
def test_no_breathing_modulation_gives_no_rate(hr, seed, condition):
    raw = model_rx(15, hr=hr, seed=seed, condition=condition, breathing=False)
    result = estimate_rx_rr(raw, now=raw[-1].timestamp)
    assert result.brpm is None and result.reason == 'unclear'
