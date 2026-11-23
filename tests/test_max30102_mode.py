"""MAX30102 mode: RED-only on/off output with a preset amplitude; HR, SpO2, RR and noise stay the user's."""
import os
import threading
import time

os.environ.setdefault("PPG_DRY_RUN", "1")

import pytest

from calibration import dac_voltage_to_code
from config import DAC_IDLE_VALUE, MAX30102_AC_MV, MAX30102_DC_MV, MAX30102_PEAK_MAX_MV, MAX30102_WRITE_HZ
from config_store import config_from_ppg_params
from core.signal_engine import MAX30102_PRESET, SignalEngine


def _engine(**amplitude):
    engine = SignalEngine()
    engine.update_signal_settings(_form(engine, **amplitude))
    return engine


def _form(engine, **changes):
    p = engine.ppg_params
    values = {k: getattr(p, k) for k in (
        "dc_ir_mv", "dc_red_mv", "ac_ir_mv", "ac_red_mv", "output_dc_offset_mv", "amplification",
        "dicrotic_notch", "spo2", "waveform", "ac_polarity", "lock_ac", "lock_dc")}
    if values["ac_ir_mv"] is None:
        values["ac_ir_mv"] = p.perfusion_index * p.dc_ir_mv / 100
    for ch in ("ir", "red"):
        for kind in ("sp", "dn", "dp"):
            values[kind + "_ms_" + ch] = getattr(p, kind + "_ms_" + ch)
    values.update(changes)
    return values


USER_AMPLITUDE = dict(dc_ir_mv=1200.0, dc_red_mv=1100.0, ac_ir_mv=40.0, ac_red_mv=30.0,
                      output_dc_offset_mv=100.0, lock_ac=True, lock_dc=False)


def test_mode_applies_the_preset_and_puts_the_user_amplitude_back():
    engine = _engine(**USER_AMPLITUDE)
    engine.set_max30102_mode(True)
    p = engine.ppg_params
    assert engine.max30102_mode
    assert {k: getattr(p, k) for k in MAX30102_PRESET} == MAX30102_PRESET
    assert p.dc_red_mv == MAX30102_DC_MV and p.ac_red_mv == MAX30102_AC_MV

    engine.set_max30102_mode(False)
    p = engine.ppg_params
    assert not engine.max30102_mode
    for key, value in USER_AMPLITUDE.items():
        assert getattr(p, key) == value, key


def test_user_controls_stay_free_while_the_amplitude_is_held():
    engine = _engine()
    engine.set_max30102_mode(True)
    engine.update_heart_rate(96)
    engine.update_spo2_target(88)        # clears the manual RED AC in Classic
    engine.update_resp_rate(22)
    engine.update_noise_settings("white", 5.0, 0.0, 7, 0.0)
    engine.update_perfusion_index(9.0)   # would move AC
    engine.update_signal_settings(_form(engine, dc_red_mv=1400.0, ac_red_mv=50.0))
    p = engine.ppg_params
    assert (p.heart_rate, p.spo2, p.resp_rate, p.noise_kind, p.noise_amplitude_mv) == (96, 88, 22, "white", 5.0)
    assert {k: getattr(p, k) for k in MAX30102_PRESET} == MAX30102_PRESET
    assert engine.ppg_model.params.ac_red_mv == MAX30102_AC_MV


def test_saved_config_keeps_the_user_amplitude_not_the_preset():
    engine = _engine(**USER_AMPLITUDE)
    engine.update_heart_rate(70)
    engine.set_max30102_mode(True)
    engine.update_heart_rate(84)
    saved = config_from_ppg_params(engine.params_for_save())
    for key, value in USER_AMPLITUDE.items():
        assert saved[key] == value, key
    assert saved["heart_rate"] == 84


def test_loading_parameters_in_the_mode_keeps_the_preset():
    engine = SignalEngine()
    engine.set_max30102_mode(True)
    params = engine.ppg_params.copy()
    params.dc_red_mv, params.ac_red_mv = 1500.0, None
    engine.load_parameters(params)
    assert engine.ppg_params.dc_red_mv == MAX30102_DC_MV
    assert engine.ppg_params.ac_red_mv == MAX30102_AC_MV


class _BusDACs:
    """DAC pair that records writes and takes ~0.3 ms per I2C transaction, like the Pi bus."""

    is_ready = True

    def __init__(self):
        self.writes = []
        self.last_ir = self.last_red = DAC_IDLE_VALUE
        self._lock = threading.Lock()

    def _record(self, channel, code):
        time.sleep(0.0003)
        with self._lock:
            self.writes.append((channel, code))

    def set_values(self, ir, red):
        self.last_ir, self.last_red = ir, red
        self._record("ir", ir)
        self._record("red", red)

    def set_red(self, red):
        self.last_red = red
        self._record("red", red)

    def begin(self):
        return True


def _run(engine, seconds):
    engine.dac_manager = _BusDACs()
    engine.start_simulation(engine.ppg_params.condition)
    try:
        time.sleep(seconds)
    finally:
        engine.stop_simulation()
    return engine.dac_manager.writes


def _red_while_running(writes):
    running = list(writes)
    while running[-1][1] == DAC_IDLE_VALUE:   # the parking writes of stop_simulation
        running.pop()
    return running, [code for ch, code in running if ch == "red"]


def test_output_is_red_only_on_off_following_the_pulse():
    engine = SignalEngine()
    engine.update_heart_rate(120)
    engine.update_noise_settings("none", 0.0, 0.0, None, 0.0)
    engine.set_max30102_mode(True)
    running, red = _red_while_running(_run(engine, 1.2))
    assert all(code == DAC_IDLE_VALUE for ch, code in running if ch == "ir")
    first = next(i for i, code in enumerate(red) if code != DAC_IDLE_VALUE)   # level is 0 until the first sample
    on, off = red[first::2], red[first + 1::2]
    assert set(off) == {DAC_IDLE_VALUE}
    low = dac_voltage_to_code(MAX30102_DC_MV / 1000) - 5
    assert min(on[50:]) >= low                               # never below the DC between beats
    assert max(on) <= dac_voltage_to_code(MAX30102_PEAK_MAX_MV / 1000)
    assert max(on) - min(on[50:]) > dac_voltage_to_code(0.6 * MAX30102_AC_MV / 1000)   # pulses reach the LED
    assert engine.get_stats()["max30102_writes"] >= len(red) - 1


def test_writes_are_paced_at_the_configured_rate():
    """Free-running near 2000 writes/s aliased onto the HR band on the bench; the rate is a deadline schedule."""
    engine = SignalEngine()
    engine.set_max30102_mode(True)
    seconds = 2.0
    _, red = _red_while_running(_run(engine, seconds))
    assert 0.85 * MAX30102_WRITE_HZ * seconds <= len(red) <= 1.02 * MAX30102_WRITE_HZ * seconds


def test_peak_is_capped_with_noise():
    engine = SignalEngine()
    engine.update_noise_settings("white", 200.0, 0.0, 3, 0.0)
    engine.set_max30102_mode(True)
    writes = _run(engine, 0.6)
    peak = dac_voltage_to_code(MAX30102_PEAK_MAX_MV / 1000)
    assert max(code for ch, code in writes if ch == "red") <= peak
    assert engine.get_stats()["max30102_clipped"] > 0


def test_classic_output_is_unchanged_when_the_mode_is_off():
    engine = SignalEngine()
    writes = _run(engine, 0.4)
    while writes[-1][1] == DAC_IDLE_VALUE:   # the parking writes of stop_simulation
        writes.pop()
    assert not any(ch == "red" and code == DAC_IDLE_VALUE for ch, code in writes)
    assert any(ch == "ir" and code > DAC_IDLE_VALUE for ch, code in writes)
    assert engine.get_stats()["max30102_writes"] == 0


@pytest.mark.parametrize("stored, expected", [(None, False), (True, True), (False, False)])
def test_config_flag_defaults_off(tmp_path, monkeypatch, stored, expected):
    import json
    import config_store
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "CONFIG_JSON_PATH", str(path))
    data = {"heart_rate": 70.0}
    if stored is not None:
        data["max30102_mode"] = stored
    path.write_text(json.dumps(data))
    assert config_store.load_config()["max30102_mode"] is expected


def test_writer_loop_toggles_on_schedule_and_parks():
    from hw.max30102_flicker import run
    t = [0.0]

    def clock():                                              # every read costs 1 us, so the spin ends
        t[0] += 1e-6
        return t[0]

    def sleep(dt):
        t[0] += dt

    feed = iter([[700], [], [5000], [], [], [800], None])   # 5000 is above the peak
    writes = []

    def write(code):
        writes.append((round(t[0], 6), code))
        t[0] += 0.0004                                        # one I2C transaction
    n = run(write, lambda: next(feed), 1500, 1000, clock=clock, sleep=lambda dt: sleep(dt))
    assert n == len(writes) == 6
    assert [c for _, c in writes] == [700, 0, 1000, 0, 1000, 0]
    gaps = [b[0] - a[0] for a, b in zip(writes, writes[1:])]
    assert all(abs(g - 1 / 1500) < 5e-6 for g in gaps)


def test_writer_reads_levels_from_a_pipe_and_stops_on_q_or_eof():
    from hw.max30102_flicker import _stdin_levels
    r, w = os.pipe()
    read = _stdin_levels(r)
    assert read() == []
    os.write(w, b"12\n3")
    assert read() == [12]
    os.write(w, b"4\n\nq\n")
    assert read() is None
    os.close(w)
    r2, w2 = os.pipe()
    read2 = _stdin_levels(r2)
    os.close(w2)
    assert read2() is None
    os.close(r)
    os.close(r2)


def test_rx_acquisition_is_paused_during_the_output_and_resumed(monkeypatch):
    from hw.opt101_rx import OPT101Receiver
    calls = []

    class _Rx:
        is_running = True

        def stop(self):
            calls.append("stop")
            self.is_running = False

        def start(self):
            calls.append("start")
            self.is_running = True
            return True
    monkeypatch.setattr(OPT101Receiver, "get_instance", classmethod(lambda cls: _rx))
    _rx = _Rx()
    engine = SignalEngine()
    engine.set_max30102_mode(True)
    _run(engine, 0.3)
    assert calls == ["stop", "start"]


def test_writer_process_follows_the_levels_and_parks_red(tmp_path, monkeypatch):
    """The real script in its own process, with smbus2 replaced by a recorder (no I2C on the test host)."""
    from hw.max30102_flicker import FlickerProcess
    log_path = tmp_path / "writes.txt"
    (tmp_path / "smbus2.py").write_text(
        "class SMBus:\n"
        "    def __init__(self, bus): self.f = open(%r, 'a')\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): self.f.close()\n"
        "    def write_byte_data(self, addr, hi, lo): self.f.write(f'{addr} {(hi << 8) | lo}\\n')\n" % str(log_path))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    writer = FlickerProcess(1, 0x60, 1500, 1000)
    writer.set_level(800)
    time.sleep(0.3)
    writer.set_level(4000)                      # capped at the peak in the process
    time.sleep(0.3)
    writes, errors, status = writer.stop()
    rows = [tuple(map(int, line.split())) for line in log_path.read_text().splitlines()]
    codes = [code for addr, code in rows]
    assert status == 0 and errors == 0
    assert all(addr == 0x60 for addr, _ in rows)
    assert writes == len(codes) - 1             # plus the parking write
    assert codes[-1] == 0
    assert 800 in codes and 1000 in codes and max(codes) == 1000
    assert 0.8 * 1500 * 0.6 <= writes <= 1.1 * 1500 * 0.6


def _pulse_clip(name="clip", seconds=3.0, rate=100.0, dc=1.5, ac=0.045, hr=90, flat_ir=False):
    """IR and RED pulses at `hr` (RED at half the AC), the way Model and Recording clips carry them."""
    import math
    from core.waveform_clip import WaveformClip
    rows = []
    for i in range(int(seconds * rate)):
        t = i / rate
        x = 0.5 + 0.5 * math.sin(2 * math.pi * hr / 60 * t)
        rows.append((t, dc if flat_ir else dc + ac * x, dc + 0.5 * ac * x))
    return WaveformClip(tuple(rows), rate, name)


def test_pulse_span_picks_the_lane_with_the_larger_pulse():
    from core.waveform_clip import pulse_span
    lane, low, high = pulse_span(_pulse_clip())
    assert lane == 1 and low == pytest.approx(1.5, abs=2e-3) and high == pytest.approx(1.545, abs=2e-3)
    assert pulse_span(_pulse_clip(flat_ir=True))[0] == 2


@pytest.mark.parametrize("flat_ir", [False, True])
def test_model_and_recording_clips_flicker_red_at_the_preset(flat_ir):
    """Model (GAN/Gaussian) and Recording pages play WaveformClips; the sensor needs them on the RED flicker too."""
    engine = SignalEngine()
    engine.set_max30102_mode(True)
    engine.dac_manager = _BusDACs()
    engine.start_waveform(_pulse_clip(dc=1.2, ac=0.08, flat_ir=flat_ir))
    try:
        time.sleep(1.2)
    finally:
        engine.stop_simulation()
    running, red = _red_while_running(engine.dac_manager.writes)
    assert all(code == DAC_IDLE_VALUE for ch, code in running if ch == "ir")
    first = next(i for i, code in enumerate(red) if code != DAC_IDLE_VALUE)
    on, off = red[first::2], red[first + 1::2]
    assert set(off) == {DAC_IDLE_VALUE}
    dc, top = dac_voltage_to_code(MAX30102_DC_MV / 1000), dac_voltage_to_code((MAX30102_DC_MV + MAX30102_AC_MV) / 1000)
    assert min(on) >= dc - 15 and max(on) <= top + 15          # the clip's own 1.2 V / 80 mV is not used
    assert max(on) - min(on) > 0.8 * (top - dc)
    assert engine.get_stats()["max30102_writes"] >= len(red) - 1


def test_clip_output_is_unchanged_when_the_mode_is_off():
    engine = SignalEngine()
    engine.dac_manager = _BusDACs()
    engine.start_waveform(_pulse_clip(dc=1.2, ac=0.08))
    try:
        time.sleep(0.4)
    finally:
        engine.stop_simulation()
    running, red = _red_while_running(engine.dac_manager.writes)
    assert DAC_IDLE_VALUE not in red
    assert min(red) >= dac_voltage_to_code(1.2) - 2
    assert engine.get_stats()["max30102_writes"] == 0


def test_a_flat_clip_holds_the_preset_dc():
    engine = SignalEngine()
    engine.set_max30102_mode(True)
    clip = _pulse_clip(ac=0.0)
    engine.start_simulation(engine.ppg_params.condition, waveform_clip=clip)
    engine.stop_simulation()
    with engine._model_lock:
        assert engine._max30102_clip_level(1.5, 1.5) == pytest.approx(MAX30102_DC_MV / 1000)


def test_writer_process_parks_red_on_sigterm(tmp_path, monkeypatch):
    """systemd stops the app's unit with SIGTERM to every process in it, the writer included."""
    import signal
    from hw.max30102_flicker import FlickerProcess
    log_path = tmp_path / "writes.txt"
    (tmp_path / "smbus2.py").write_text(
        "class SMBus:\n"
        "    def __init__(self, bus): self.f = open(%r, 'a')\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): self.f.close()\n"
        "    def write_byte_data(self, addr, hi, lo): self.f.write(f'{addr} {(hi << 8) | lo}\\n')\n" % str(log_path))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    writer = FlickerProcess(1, 0x60, 1500, 1000)
    writer.set_level(800)
    time.sleep(0.4)
    writer._proc.send_signal(signal.SIGTERM)
    out, _ = writer._proc.communicate(timeout=2)
    codes = [int(line.split()[1]) for line in log_path.read_text().splitlines()]
    assert writer._proc.returncode == 0 and out.startswith("writes ")
    assert 800 in codes and codes[-1] == 0
