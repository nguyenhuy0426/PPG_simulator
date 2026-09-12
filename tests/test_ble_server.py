"""BLE server logic tests (no BlueZ required — handler + status builder only).

Run: PPG_DRY_RUN=1 python3 -m pytest tests/test_ble_server.py -q
"""

import json

import pytest

from comm.ble_server import BLECommandHandler, BleServer, build_status_json
from models.limits import AC_LEVEL_MV, DC_LEVEL_MV, HEART_RATE


class FakeEngine:
    """Minimal engine double recording wrapper calls (limits still applied)."""

    def __init__(self):
        from models.ppg_model import PPGParameters

        self.ppg_params = PPGParameters()
        self.calls = []
        self.state = 0  # SIG_STOPPED
        self.started = 0

    def _rec(self, name):
        self.calls.append(name)

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
        self.ppg_params.perfusion_index = v

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

    def update_dc_levels(self, dc_ir, dc_red=None):
        self._rec("dc_levels")
        self.ppg_params.dc_ir_mv = dc_ir
        self.ppg_params.dc_red_mv = dc_red

    def start_simulation(self, condition=0):
        self.started += 1
        self.state = 1  # SIG_RUNNING
        self.ppg_params.condition = condition

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
    p = handler.engine.ppg_params
    assert p.heart_rate == 120 and p.spo2 == 95 and p.resp_rate == 20
    assert p.perfusion_index == 5.5 and p.noise_level == 0.3
    assert p.ac_ir_mv == 60.0 and p.ac_red_mv == 70.0
    assert p.dc_ir_mv == 1200.0 and p.dc_red_mv == 1300.0


def test_delta_merge_only_applies_present_keys(handler):
    applied = handler.handle_command({"hr": 90})
    assert applied == {"hr": 90}
    p = handler.engine.ppg_params
    assert p.heart_rate == 90
    assert p.spo2 == 98.0 and p.resp_rate == 16.0  # defaults untouched


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


def test_auto_start_on_first_command_when_stopped(handler):
    handler.engine.state = 0  # SIG_STOPPED
    handler.handle_command({"hr": 80})
    assert handler.engine.started == 1
    # Only once per handler lifetime, and not when already running
    handler.handle_command({"hr": 81})
    assert handler.engine.started == 1


def test_status_json_exact_keys_and_compact():
    from models.ppg_model import PPGParameters

    p = PPGParameters()
    js = build_status_json(p, "rpi", 7)
    obj = json.loads(js)
    assert set(obj) == {
        "hr", "spo2", "rr", "pi", "noise", "condition",
        "ac_ir_mv", "ac_red_mv", "dc_ir_mv", "dc_red_mv", "origin", "seq",
    }
    assert obj["origin"] == "rpi" and obj["seq"] == 7
    assert ": " not in js and ", " not in js  # compact separators
    assert len(js) <= 180


def test_status_json_reports_nominal_ac_when_derived():
    from models.ppg_model import PPGParameters

    p = PPGParameters()  # ac_ir_mv / ac_red_mv are None (derive mode)
    obj = json.loads(build_status_json(p, "rpi", 1))
    # PI 3% at DC 1500 -> nominal AC 45 mV
    assert obj["ac_ir_mv"] == pytest.approx(45.0, abs=0.2)
    assert obj["dc_ir_mv"] == 1500.0


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


def test_ble_server_wraps_engine_without_bless(real_engine):
    """BleServer object lifecycle works without bless imported (lazy import)."""
    server = BleServer(real_engine)
    server.on_write(b'{"hr": 66}')
    assert real_engine.get_ppg_params().heart_rate == 66
    assert server._pending_android is True
    server.on_write(b"garbage")
    assert server._pending_android is True  # unchanged by failed parse
    assert server.status_bytes() == b"{}"   # status loop not running yet
