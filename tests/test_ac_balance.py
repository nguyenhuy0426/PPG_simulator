"""AC balance: gain table, trim step, per-beat AC, the engine's AC scaling and the closed loop on a simulated path.

The optical path here is simulated (a fixed gain plus an offset); none of this is a hardware measurement.
"""
import math
from types import SimpleNamespace

import pytest

from core import ac_balance as ab
from hw.opt101_rx import RXSample, raw_to_millivolts

HZ = 100


def pulse(phase):
    """A PPG-like beat, 0..~1: systolic peak and a smaller diastolic wave."""
    return math.exp(-((phase - .2) / .08) ** 2) + .4 * math.exp(-((phase - .45) / .1) ** 2)


def wave(seconds, amplitude, start=0.0, bpm=75.0):
    return [(start + i / HZ, amplitude * pulse((i / HZ * bpm / 60.0) % 1.0)) for i in range(int(seconds * HZ))]


def test_gain_table_interpolates_and_holds_its_ends():
    points = ((300, 1.0), (500, 2.0))
    assert ab.gain_at(points, 400) == pytest.approx(1.5)
    assert ab.gain_at(points, 100) == 1.0
    assert ab.gain_at(points, 1500) == 2.0
    assert ab.smoothed(((1, 1.0), (2, 4.0), (3, 1.0)))[1][1] == pytest.approx(2.0)


def test_saved_table_is_used_only_when_complete_and_plausible():
    good = {"IR": [[300, 1.3], [1500, 2.0]], "RED": [[300, 1.1], [1500, 1.2]]}
    assert ab.parse_table(good)["IR"] == ((300.0, 1.3), (1500.0, 2.0))
    assert ab.parse_table({"IR": good["IR"]}) is None
    assert ab.parse_table({**good, "RED": [[300, 1.1]]}) is None
    assert ab.parse_table({**good, "RED": [[300, 9.0], [1500, 1.2]]}) is None
    assert ab.parse_table("x") is None


def test_trim_moves_half_the_log_error_within_its_limits():
    assert ab.next_trim(1.0, 1.01) == 1.0                         # deadband
    assert ab.next_trim(1.0, 1.21) == pytest.approx(1 / 1.1)       # 1.21 ** -0.5
    assert ab.next_trim(1.0, 4.0) == pytest.approx(1 / ab.MAX_STEP)
    assert ab.next_trim(1.55, 0.25) == ab.TRIM_RANGE[1]


def test_beat_ac_reads_the_same_ratio_as_the_amplitudes():
    tx, _iqr, beats = ab.beat_ac([v for _t, v in wave(10, 40.0)])
    rx, _iqr, _ = ab.beat_ac([1000.0 + v for _t, v in wave(10, 72.0)])
    assert beats >= 10
    assert rx / tx == pytest.approx(1.8, rel=0.01)


def test_engine_scales_only_the_ac_part():
    from core.signal_engine import SignalEngine
    engine = SignalEngine.__new__(SignalEngine)
    engine._ac_comp, engine._ac_comp_clipped = (1.0, 1.0), 0
    assert engine._compensate(1.040, 0.530, 0.040, 0.030) == (1.040, 0.530)
    engine.set_ac_compensation(0.5, 2.0)
    ir, red = engine._compensate(1.040, 0.530, 0.040, 0.030)
    assert (ir, red) == (pytest.approx(1.020), pytest.approx(0.560))
    assert engine.ac_balance_active
    with pytest.raises(ValueError):
        engine.set_ac_compensation(float("nan"), 1.0)


class FakeEngine:
    is_running, is_calibrating, is_waveform_playing = True, False, False

    def __init__(self, dc=1000.0, ac=43.0):
        self.params = SimpleNamespace(dc_ir_mv=dc, dc_red_mv=dc, ac_ir_mv=ac, ac_red_mv=ac, heart_rate=75.0, spo2=99.0,
                                      condition=0, perfusion_index=ac / dc * 100, output_dc_offset_mv=0.0)
        self.factors = (1.0, 1.0)
        self.now = 0.0

    def get_ppg_params(self):
        return self.params

    def set_ac_compensation(self, ir, red):
        self.factors = (ir, red)

    def get_display_history(self):
        ac = self.params.ac_ir_mv / 1000.0
        return [(t, v, v) for t, v in wave(12, ac, start=self.now - 12)]


class FakePath:
    """RX = offset + true gain x DAC AC, sampled at 100 Hz, as 12-bit codes."""

    def __init__(self, engine, gain_ir, gain_red):
        self.engine, self.gain = engine, {4: gain_ir, 0: gain_red}

    def get_samples_since(self, channel, since):
        k = self.engine.factors[0 if channel == 4 else 1]
        ac = self.engine.params.ac_ir_mv * k * self.gain[channel]
        out = []
        for t, v in wave(self.engine.now - since, ac, start=since):
            out.append(RXSample(t, round((900.0 + v) / raw_to_millivolts(1)), False))
        return out


def run_loop(balance, engine, seconds):
    t = 0.0
    while t < seconds:
        engine.now = t
        balance.tick(t)
        if balance._job is not None:
            balance._job.join()
        t += 0.5


def test_loop_brings_received_ac_to_the_set_ac_when_the_table_is_off_by_20_percent():
    engine = FakeEngine()
    table = {"IR": ((300, 1.9), (1500, 1.9)), "RED": ((300, 1.2), (1500, 1.2))}
    balance = ab.AcBalance(engine, FakePath(engine, 1.9 * 1.2, 1.2 * 0.8), table=table)
    run_loop(balance, engine, 120)
    for name in ab.CHANNELS:
        assert balance.state[name].reason == "ok"
        assert balance.state[name].ratio == pytest.approx(1.0, abs=0.05)
    assert balance.state["IR"].trim == pytest.approx(1 / 1.2, rel=0.05)
    assert balance.state["RED"].trim == pytest.approx(1 / 0.8, rel=0.05)


def test_feedforward_alone_when_the_table_is_right():
    engine = FakeEngine(dc=600.0)
    balance = ab.AcBalance(engine, FakePath(engine, 1.66, 1.20), table=ab.MEASURED_GAIN, loop=False)
    balance.tick(0.0)
    ir, red = engine.factors
    assert 1.66 * ir == pytest.approx(1.0, abs=0.03)
    assert 1.20 * red == pytest.approx(1.0, abs=0.03)


def test_loop_holds_while_not_in_classic_or_held_and_off_restores_unity():
    engine = FakeEngine()
    balance = ab.AcBalance(engine, FakePath(engine, 2.0, 1.2), hold=lambda: True)
    run_loop(balance, engine, 40)
    assert balance.state["IR"].trim == 1.0 and balance.state["IR"].reason == "held"
    balance.set_enabled(False)
    assert engine.factors == (1.0, 1.0)


def test_saturated_window_does_not_move_the_trim():
    engine = FakeEngine()
    path = FakePath(engine, 2.0, 1.2)
    original = path.get_samples_since
    path.get_samples_since = lambda ch, since: [s._replace(saturated=True) for s in original(ch, since)]
    balance = ab.AcBalance(engine, path)
    run_loop(balance, engine, 40)
    assert balance.state["IR"].reason == "saturated" and balance.state["IR"].trim == 1.0


def test_spo2_fits_apply_only_in_the_balance_state_they_were_made_in():
    from core import rx_spo2_cal as cal
    old = cal.RxSpo2Calibration(118.0, 31.0, 1000.0, 1000.0, 0.5, ((98.0, 0.6), (70.0, 1.5)), 1.0)
    new = cal.RxSpo2Calibration(112.0, 28.0, 1000.0, 1000.0, 0.5, ((98.0, 0.6), (70.0, 1.5)), 2.0, True)
    assert old.applies_to(1000.0, 1000.0) and not old.applies_to(1000.0, 1000.0, True)
    assert cal.with_calibration((old,), new) == (old, new)          # both kept: different states
    assert cal.RxSpo2Calibration.from_dict(new.to_dict()) == new
    assert cal.RxSpo2Calibration.from_dict({k: v for k, v in old.to_dict().items() if k != "ac_balance"}) == old
