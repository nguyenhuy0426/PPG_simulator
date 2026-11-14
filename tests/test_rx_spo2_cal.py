"""Receive-path SpO2 calibration: lanes with the zero offsets measured on the Pi (§13) read R ~0.82x the sent R;
the fitted A', B' read the sent SpO2 back."""
import os
from collections import namedtuple

import pytest

os.environ.setdefault("PPG_DRY_RUN", "1")

from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED
from core import rx_spo2_cal as cal
from core.rx_spo2 import estimate_rx_spo2
from models.ppg_model import PPGModel, PPGParameters

Sample = namedtuple("Sample", "timestamp raw saturated")
LANE = {ADC_CHANNEL_IR: (1.05, 256.0), ADC_CHANNEL_RED: (1.21, 87.0)}    # rx = g * (tx - x0), mV, measured


def params(**kw):
    p = PPGParameters()
    p.heart_rate, p.perfusion_index, p.dc_ir_mv, p.dc_red_mv, p.ac_ir_mv = 80.0, 4.0, 1000.0, 1000.0, 40.0
    p.ac_red_mv, p.noise_level = 50.0, 0.0                 # a manual RED AC, as on the Pi
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def waveform(p, seconds, spo2):
    m = PPGModel()
    q = p.copy()
    q.spo2, q.ac_red_mv = spo2, None
    m.set_parameters(q)
    out = []
    for i in range(int(seconds * 200)):
        ir, red, *_ = m.generate_both_samples(1 / 200)
        if i % 2 == 0:
            out.append((ir * 1000, red * 1000))
    return out


def lane(values, channel, start):
    g, x0 = LANE[channel]
    return [Sample(start + i / 100, max(0, round(g * (v - x0) / 3300 * 4095)), False) for i, v in enumerate(values)]


class FakeEngine:
    def __init__(self, p):
        self.ppg_params, self.running, self.loaded = p, False, None

    def get_ppg_params(self):
        return self.ppg_params

    def update_spo2_target(self, spo2):
        self.ppg_params = self.ppg_params.copy()
        self.ppg_params.spo2, self.ppg_params.ac_red_mv = spo2, None

    def start_simulation(self, condition):
        self.running = True

    def stop_simulation(self):
        self.running = False

    def load_parameters(self, p):
        self.ppg_params = self.loaded = p


class FakeReceiver:
    """Serves MEASURE_S of the waveform the engine is playing, through the two distorted lanes."""

    def __init__(self, engine, weak=False):
        self.engine, self.weak, self._cache = engine, weak, {}

    def get_samples_since(self, channel, since):
        p = self.engine.ppg_params
        key = (p.spo2, since)
        if key not in self._cache:
            self._cache[key] = waveform(p, cal.MEASURE_S, p.spo2)
        ir, red = zip(*self._cache[key])
        values = ir if channel == ADC_CHANNEL_IR else red
        if self.weak:
            values = [1000.0] * len(values)
        return lane(values, channel, since)


def run_calibration(engine, receiver):
    run = cal.CalibrationRun(engine, receiver)
    now = 100.0
    run.start(now)
    while not run.done:
        now += 1.0
        run.tick(now)
    return run


def test_fit_recovers_a_straight_line():
    a, b, residual = cal.fit([(98.0, 0.4), (90.0, 0.72), (80.0, 1.12), (70.0, 1.52)])
    assert (a, b) == pytest.approx((108.0, 25.0))
    assert residual == pytest.approx(0.0, abs=1e-9)
    with pytest.raises(ValueError):
        cal.fit([(98.0, 0.5), (70.0, 0.5)])


def test_distorted_lanes_read_high_without_calibration_and_right_with_it():
    engine = FakeEngine(params())
    run = run_calibration(engine, FakeReceiver(engine))
    assert run.error is None, run.error
    c = run.calibration
    assert c.max_residual <= cal.MAX_RESIDUAL
    assert (c.dc_ir_mv, c.dc_red_mv) == (1000.0, 1000.0)
    for spo2 in (95.0, 85.0, 75.0):
        p = params()
        ir, red = zip(*waveform(p, 12, spo2))
        rx_ir, rx_red = lane(ir, ADC_CHANNEL_IR, 0.0), lane(red, ADC_CHANNEL_RED, 0.0)
        raw = estimate_rx_spo2(rx_ir, rx_red, 110.0, 25.0)
        fixed = estimate_rx_spo2(rx_ir, rx_red, c.a, c.b)
        assert raw.ratio < 0.9 * (110 - spo2) / 25           # the bug: received R ~0.82x the sent R
        assert fixed.spo2 == pytest.approx(spo2, abs=1.5)


def test_run_restores_the_classic_parameters_and_stops_the_output():
    engine = FakeEngine(params())
    run_calibration(engine, FakeReceiver(engine))
    assert not engine.running
    assert engine.ppg_params.ac_red_mv == 50.0 and engine.ppg_params.spo2 == params().spo2


def test_a_flat_lane_fails_without_a_calibration():
    engine = FakeEngine(params())
    run = run_calibration(engine, FakeReceiver(engine, weak=True))
    assert run.calibration is None and run.error.startswith("reason:")
    assert not engine.running and engine.loaded is not None


def test_saved_fit_applies_only_at_its_dc_levels(monkeypatch):
    fit = cal.RxSpo2Calibration(118.0, 31.0, 1000.0, 1000.0, 0.5, ((98.0, 0.6), (70.0, 1.5)), 0.0)
    monkeypatch.setitem(cal._cache, "loaded", True)
    monkeypatch.setitem(cal._cache, "value", fit)
    assert cal.coefficients_for(params()) == (118.0, 31.0, "calibrated")
    assert cal.coefficients_for(params(dc_ir_mv=1200.0)) == (110.0, 25.0, "other_dc")
    assert cal.coefficients_for(params(output_dc_offset_mv=100.0))[2] == "other_dc"
    monkeypatch.setitem(cal._cache, "value", None)
    assert cal.coefficients_for(params()) == (110.0, 25.0, "none")


def test_config_round_trip_and_rejects_broken_entries():
    fit = cal.RxSpo2Calibration(118.0, 31.0, 1000.0, 1000.0, 0.5, ((98.0, 0.6), (70.0, 1.5)), 1.0)
    assert cal.RxSpo2Calibration.from_dict(fit.to_dict()) == fit
    for broken in ({}, {**fit.to_dict(), "b": -1}, {**fit.to_dict(), "a": float("nan")},
                   {**fit.to_dict(), "points": [[98, 0.6]]}, {**fit.to_dict(), "points": "x"}):
        assert cal.RxSpo2Calibration.from_dict(broken) is None


def test_the_calibration_survives_the_exit_save():
    from config_store import PRESERVED_KEYS
    assert cal.CONFIG_KEY in PRESERVED_KEYS
