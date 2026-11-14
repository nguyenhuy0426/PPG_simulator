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
    # Output started after the window began: the IR lane read 0 mV while the LED was off.
    raw = respiratory()
    raw[:500] = [s._replace(raw=0) for s in raw[:500]]
    assert estimate_rx_rr(raw, now=60).reason == 'dark'
    raw[-10] = raw[-10]._replace(raw=4095, saturated=True)
    assert estimate_rx_rr(raw, now=60).reason == 'saturated'
