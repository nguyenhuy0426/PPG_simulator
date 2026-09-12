"""BLE server logic tests (no BlueZ required — handler + status builder only).

Run: PPG_DRY_RUN=1 python3 -m pytest tests/test_ble_server.py -q
"""

import json
import time

import pytest

from comm.ble_server import (
    ANDROID_GRACE_S,
    PB_FILE_MAX_CHARS,
    BLECommandHandler,
    BleServer,
    build_status_json,
    origin_for_tick,
)
from models.limits import AC_LEVEL_MV, DC_LEVEL_MV, HEART_RATE


class FakeEngine:
    """Minimal engine double recording wrapper calls (limits still applied)."""

    def __init__(self):
        from models.ppg_model import PPGParameters

        self.ppg_params = PPGParameters()
        self.calls = []
        self.state = 0  # SIG_STOPPED
        self._running = False
        self.started = 0
        self.stopped = 0
        self.ac_dc_locked = False
        self._recording = False
        self.rec_calls = []
        self.play_requests = []

    def _rec(self, name):
        self.calls.append(name)

    @property
    def recording(self):
        return self._recording

    def update_heart_rate(self, v):
        self._rec("hr")
        self.ppg_params.heart_rate = v

    def update_spo2(self, v):
        self._rec("spo2")
        self.ppg_params.spo2 = v

    def update_resp_rate(self, v):
        self._rec("rr")
        self.ppg_params.resp_rate = v

    def update_perfusion_index(self, v):
        self._rec("pi")
        if self.ac_dc_locked:
            return  # mirrors the real engine's silent drop (the BLE layer
            # translates locked PI writes before ever reaching this)
        self.ppg_params.perfusion_index = v
        dc = self.ppg_params.dc_ir_mv
        self.ppg_params.ac_ir_mv = v / 100.0 * dc if dc > 0 else 0.0

    def update_noise_level(self, v):
        self._rec("noise")
        self.ppg_params.noise_level = v

    def change_condition(self, v):
        self._rec("condition")
        self.ppg_params.condition = v

    def update_ac_levels(self, ac_ir, ac_red=None):
        self._rec("ac_levels")
        self.ppg_params.ac_ir_mv = ac_ir
        self.ppg_params.ac_red_mv = ac_red
        dc = self.ppg_params.dc_ir_mv
        self.ppg_params.perfusion_index = ac_ir / dc * 100.0 if dc > 0 else 0.0

    def update_dc_levels(self, dc_ir, dc_red=None):
        self._rec("dc_levels")
        self.ppg_params.dc_ir_mv = dc_ir
        self.ppg_params.dc_red_mv = dc_red
        if not self.ac_dc_locked:
            self.ppg_params.ac_ir_mv = self.ppg_params.perfusion_index / 100.0 * dc_ir

    def start_simulation(self, condition=0):
        self.started += 1
        self.state = 1  # SIG_RUNNING
        self._running = True
        self.ppg_params.condition = condition

    def stop_simulation(self):
        self.stopped += 1
        self.state = 0  # SIG_STOPPED
        self._running = False

    def start_recording(self):
        self.rec_calls.append("start")
        self._recording = True
        return True

    def stop_recording(self):
        self.rec_calls.append("stop")
        self._recording = False
        return True

    def request_playback(self, action, filename=""):
        self.play_requests.append((action, filename))

    def get_playback_state(self):
        return (False, "", "")

    def get_ppg_params(self):
        return self.ppg_params


@pytest.fixture()
def handler():
    return BLECommandHandler(FakeEngine())


def test_full_command_applies_everything(handler):
    cmd = {
        "hr": 120, "spo2": 95, "rr": 20, "pi": 5.5, "noise": 0.3,
        "condition": 2, "ac_ir_mv": 60.0, "ac_red_mv": 70.0,
        "dc_ir_mv": 1200.0, "dc_red_mv": 1300.0, "origin": "android",
    }
    applied = handler.handle_command(cmd)
    assert applied["hr"] == 120
    assert applied["spo2"] == 95
    assert applied["condition"] == 2
    assert "run" not in applied and "origin" not in applied and "seq" not in applied
    p = handler.engine.ppg_params
    assert p.heart_rate == 120 and p.spo2 == 95 and p.resp_rate == 20
    assert p.noise_level == 0.3
    # Explicit AC and DC are authoritative when a full snapshot also carries
    # PI: AC/DC wins and PI is derived from the resulting physical pair.
    assert p.perfusion_index == pytest.approx(5.0)
    assert p.ac_ir_mv == 60.0 and p.ac_red_mv == 70.0
    assert p.dc_ir_mv == 1200.0 and p.dc_red_mv == 1300.0


def test_full_snapshot_does_not_let_pi_overwrite_explicit_ac_dc(handler):
    """A phone full snapshot must preserve all four amplitude sliders."""
    handler.handle_command({
        "pi": 7.5,
        "ac_ir_mv": 321.0,
        "ac_red_mv": 654.0,
        "dc_ir_mv": 1111.0,
        "dc_red_mv": 1222.0,
    })
    p = handler.engine.ppg_params
    assert p.ac_ir_mv == pytest.approx(321.0)
    assert p.ac_red_mv == pytest.approx(654.0)
    assert p.dc_ir_mv == pytest.approx(1111.0)
    assert p.dc_red_mv == pytest.approx(1222.0)
    assert p.perfusion_index == pytest.approx(321.0 / 1111.0 * 100.0)


def test_partial_pi_then_dc_keeps_pi_intent(handler):
    """A PI edit plus a DC edit still derives AC from the requested PI."""
    handler.handle_command({"pi": 7.5, "dc_ir_mv": 1000.0, "dc_red_mv": 1100.0})
    p = handler.engine.ppg_params
    assert p.perfusion_index == pytest.approx(7.5)
    assert p.ac_ir_mv == pytest.approx(75.0)


def test_delta_merge_only_applies_present_keys(handler):
    applied = handler.handle_command({"hr": 90})
    assert applied == {"hr": 90}
    p = handler.engine.ppg_params
    assert p.heart_rate == 90
    assert p.spo2 == 98.0 and p.resp_rate == 16.0  # defaults untouched
    assert handler.engine.started == 0  # T6: commands never auto-start; RUN is explicit


def test_values_clamped_to_limits(handler):
    applied = handler.handle_command(
        {"hr": 9999, "ac_ir_mv": 99999, "dc_ir_mv": -50, "condition": 42}
    )
    p = handler.engine.ppg_params
    assert applied["hr"] == HEART_RATE.maximum
    assert applied["ac_ir_mv"] == AC_LEVEL_MV.maximum      # 1500
    assert applied["dc_ir_mv"] == DC_LEVEL_MV.minimum      # 0
    assert p.condition == 5


def test_garbage_is_ignored_or_defensive(handler):
    assert handler.handle_raw(b"not json") == {}
    assert handler.handle_raw(b"") == {}
    # Non-numeric values fall back to the limit default (never crash)
    applied = handler.handle_raw(b'{"hr": "abc"}')
    assert applied.get("hr") == HEART_RATE.default
    # "origin"/"seq" arrive from the phone but are server-side bookkeeping only
    assert handler.handle_command({"origin": "android", "seq": 99}) == {}


def test_commands_never_autostart_the_engine(handler):
    """Protocol v2 (T6): the phone's RUN command is the only start trigger."""
    handler.handle_command({"hr": 80})
    assert handler.engine.started == 0
    assert handler.engine.state == 0
    handler.handle_command({"run": True})
    assert handler.engine.started == 1


def test_run_command_toggles_simulation_idempotently(handler):
    assert handler.handle_command({"run": True}) == {"run": True}
    assert handler.engine.started == 1 and handler.engine._running
    assert handler.handle_command({"run": True}) == {"run": True}  # no re-start
    assert handler.engine.started == 1
    assert handler.handle_command({"run": False}) == {"run": False}
    assert handler.engine.stopped == 1 and not handler.engine._running
    handler.handle_command({"run": False})  # no double-stop
    assert handler.engine.stopped == 1
    assert handler.handle_command({"run": "true"}) == {"run": True}
    assert handler.engine.started == 2


def test_record_command_toggles_engine_recording(handler):
    assert handler.handle_command({"record": True}) == {"record": True}
    assert handler.engine.recording and handler.engine.rec_calls == ["start"]
    assert handler.handle_command({"record": True}) == {"record": True}  # idempotent
    assert handler.engine.rec_calls == ["start"]
    assert handler.handle_command({"record": False}) == {"record": False}
    assert not handler.engine.recording
    assert handler.engine.rec_calls == ["start", "stop"]


def test_pb_command_is_queued_for_the_tk_thread(handler):
    applied = handler.handle_command({"pb": "start", "pb_file": "data_3.csv"})
    assert applied["pb"] == "start" and applied["pb_file"] == "data_3.csv"
    assert handler.engine.play_requests == [("start", "data_3.csv")]
    handler.handle_command({"pb": "pause"})
    assert handler.engine.play_requests[-1] == ("pause", "")
    assert handler.handle_command({"pb": "bogus"}) == {}  # unknown action ignored
    assert len(handler.engine.play_requests) == 2


def test_pi_while_locked_becomes_an_ac_write(handler):
    """T2: with AC and DC both held, update_perfusion_index would drop the
    write; the handler must translate the phone's PI into the AC level."""
    eng = handler.engine
    eng.ac_dc_locked = True
    applied = handler.handle_command({"pi": 10.0})
    assert applied == {"pi": 10.0}
    assert "ac_levels" in eng.calls
    p = eng.ppg_params
    assert p.ac_ir_mv == pytest.approx(10.0 / 100 * 1500.0)  # 150 mV at DC 1500
    assert p.perfusion_index == pytest.approx(10.0)
    eng.ac_dc_locked = False
    eng.update_perfusion_index(3.0)
    assert eng.ppg_params.perfusion_index == 3.0  # normal path still works


def test_one_failing_key_does_not_abort_the_rest():
    """T3: a mid-command exception must only skip its own key."""
    class ExplodingEngine(FakeEngine):
        def update_heart_rate(self, v):
            raise ValueError("boom")

    handler = BLECommandHandler(ExplodingEngine())
    applied = handler.handle_command({"hr": 80, "spo2": 92, "rr": 14})
    assert "hr" not in applied
    assert applied["spo2"] == 92 and applied["rr"] == 14
    p = handler.engine.ppg_params
    assert p.spo2 == 92 and p.resp_rate == 14 and p.heart_rate == 75.0
    assert handler.handle_raw(b'{"hr": 81, "noise": 0.5}') == {"noise": 0.5}


def test_status_json_exact_keys_and_compact():
    from models.ppg_model import PPGParameters

    p = PPGParameters()
    js = build_status_json(p, "rpi", 7)
    obj = json.loads(js)
    assert set(obj) == {
        "hr", "spo2", "rr", "pi", "noise", "condition",
        "ac_ir_mv", "ac_red_mv", "dc_ir_mv", "dc_red_mv",
        "running", "recording", "pb", "origin", "seq",
    }
    assert obj["origin"] == "rpi" and obj["seq"] == 7
    assert obj["running"] is False and obj["recording"] is False and obj["pb"] == 0
    assert "pb_file" not in obj  # only present while playback is active
    assert ": " not in js and ", " not in js  # compact separators
    assert len(js) <= 250


def test_status_json_reports_nominal_ac_when_derived():
    from models.ppg_model import PPGParameters

    p = PPGParameters()  # ac_ir_mv / ac_red_mv are None (derive mode)
    obj = json.loads(build_status_json(p, "rpi", 1))
    # PI 3% at DC 1500 -> nominal AC 45 mV
    assert obj["ac_ir_mv"] == pytest.approx(45.0, abs=0.2)
    assert obj["dc_ir_mv"] == 1500.0


def test_status_json_control_state_and_pb_file():
    from models.ppg_model import PPGParameters

    js = build_status_json(
        PPGParameters(), "android", 12,
        running=True, recording=True, pb=2, pb_file="data_123.csv",
    )
    obj = json.loads(js)
    assert obj["running"] is True and obj["recording"] is True
    assert obj["pb"] == 2 and obj["pb_file"] == "data_123.csv"

    long_js = build_status_json(
        PPGParameters(), "android", 12, running=True, pb=1,
        pb_file="a-very-long-recording-name.csv",
    )
    obj = json.loads(long_js)
    assert obj["pb"] == 1
    assert obj["pb_file"] == "a-very-long-recording-name.csv"[:PB_FILE_MAX_CHARS]
    assert len(obj["pb_file"]) == PB_FILE_MAX_CHARS
    assert len(long_js) <= 247  # must fit one MTU-247 notification


def test_origin_for_tick_grace_window():
    """T4 pure helper: 'android' only inside the post-command grace window."""
    assert origin_for_tick(10.0, 10.0 + 0.5) == "android"
    assert origin_for_tick(10.49, 10.5) == "android"
    assert origin_for_tick(10.5, 10.5) == "rpi"      # window is exclusive
    assert origin_for_tick(11.0, 10.5) == "rpi"
    assert origin_for_tick(5.0, 0.0) == "rpi"        # no command yet ever
    assert ANDROID_GRACE_S == 1.0


@pytest.fixture(scope="module")
def real_engine():
    from core.signal_engine import SignalEngine

    engine = SignalEngine.get_instance()
    engine.begin()
    return engine


def test_real_dry_run_engine_roundtrip(real_engine):
    """Integration: the handler drives the real SignalEngine in dry-run."""
    handler = BLECommandHandler(real_engine)
    applied = handler.handle_command({"hr": 111, "pi": 4.0})
    assert applied["hr"] == 111
    assert real_engine.get_ppg_params().heart_rate == 111
    assert real_engine.get_ppg_params().perfusion_index == 4.0
    # restore defaults for other tests
    handler.handle_command({"hr": 75, "pi": 3.0})


def test_pi_while_locked_moves_real_engine_ac(real_engine):
    """T2 on the REAL engine: the phone's PI must actually reach the device."""
    from models.ppg_model import PPGParameters

    try:
        real_engine.update_lock(True, True)
        assert real_engine.ac_dc_locked
        applied = BLECommandHandler(real_engine).handle_command({"pi": 8.0})
        assert applied == {"pi": 8.0}
        p = real_engine.get_ppg_params()
        assert p.ac_ir_mv == pytest.approx(8.0 / 100 * p.dc_ir_mv)
        assert p.perfusion_index == pytest.approx(8.0)
    finally:
        real_engine.load_parameters(PPGParameters())  # clears locks + derivations
    assert real_engine.ac_dc_locked is False


def test_ble_server_wraps_engine_without_bless(real_engine):
    """BleServer object lifecycle works without bless imported (lazy import)."""
    server = BleServer(real_engine)
    assert server._android_grace_until == 0.0
    server.on_write(b'{"hr": 66}')
    assert real_engine.get_ppg_params().heart_rate == 66
    grace = server._android_grace_until
    assert grace > time.monotonic()  # T4: an applied Bluetooth write opens
    assert origin_for_tick(time.monotonic(), grace) == "android"  # the 1 s window
    server.on_write(b"garbage")
    assert server._android_grace_until == grace  # failed parse must not extend it
    assert server.status_bytes() == b"{}"  # status loop not running yet
