"""TDM mode: RED and IR share one chamber and one OPT101 (A0).

Covers the receiver's slot routing (IR/RED lanes and the separate DARK
buffer all read physical A0), the engine slot master (break-before-make LED
writes, slot order, one read per settled slot, outputs parked on stop) and
the RX panel labelling. Hardware-free: fake ADC, mocked DAC manager.
"""
import json
import logging
import os
import time
import unittest
from unittest.mock import Mock

import pytest

import config
from core.signal_engine import SignalEngine
from hw.opt101_rx import (OPT101Receiver, RX_STATUS_ERROR, RX_STATUS_OK,
                          TDM_SLOT_DARK, TDM_SLOT_IR, TDM_SLOT_RED)
from ui.rx_monitor import RXPanel

IR = config.ADC_CHANNEL_IR
RED = config.ADC_CHANNEL_RED


@pytest.fixture(autouse=True)
def quiet_logs():
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


class FakeADC:
    def __init__(self, values=None):
        self.calls = []
        self.values = list(values or [])

    def read_raw(self, channel):
        self.calls.append(channel)
        value = self.values.pop(0) if self.values else 1000
        if isinstance(value, Exception):
            raise value
        return value


def tdm_receiver(adc=None, **kwargs):
    adc = adc if adc is not None else FakeADC()
    scripted, adc.values = adc.values, []  # begin()'s probe must not eat them
    kwargs.setdefault("dry_run", False)
    rx = OPT101Receiver(adc=adc, mode="tdm", buffer_size=16, **kwargs)
    assert rx.begin()
    adc.calls.clear()
    adc.values = scripted
    return rx, adc


# ─────────────────────────── receiver ───────────────────────────

def test_slots_route_to_logical_lanes_but_always_read_the_shared_sensor():
    rx, adc = tdm_receiver(FakeADC([1100, 2200, 30]))

    assert rx.acquire_tdm_slot(TDM_SLOT_RED).raw == 1100
    assert rx.acquire_tdm_slot(TDM_SLOT_IR).raw == 2200
    assert rx.acquire_tdm_slot(TDM_SLOT_DARK).raw == 30

    assert adc.calls == [config.RX_TDM_ADC_CHANNEL] * 3
    assert [s.raw for s in rx.get_samples(RED)] == [1100]
    assert [s.raw for s in rx.get_samples(IR)] == [2200]
    assert [s.raw for s in rx.get_dark_samples()] == [30]
    assert rx.physical_channel(RED) == rx.physical_channel(IR) == config.RX_TDM_ADC_CHANNEL


def test_tdm_start_spawns_no_free_running_reader():
    rx, adc = tdm_receiver()
    assert rx.start() is True
    time.sleep(0.03)
    assert adc.calls == []
    assert not rx.is_running


def test_failed_slot_read_is_charged_to_that_lane_and_stores_nothing():
    rx, _ = tdm_receiver(FakeADC([OSError("NACK"), 900]))

    assert rx.acquire_tdm_slot(TDM_SLOT_RED) is None
    assert rx.acquire_tdm_slot(TDM_SLOT_IR).raw == 900
    assert rx.channel_status(RED) == RX_STATUS_ERROR
    assert rx.error_count(RED) == 1 and rx.sample_count(RED) == 0
    assert rx.channel_status(IR) == RX_STATUS_OK and rx.error_count(IR) == 0


def test_dry_run_tdm_produces_no_samples():
    rx = OPT101Receiver(mode="tdm", dry_run=True)
    assert rx.begin()
    assert rx.acquire_tdm_slot(TDM_SLOT_RED) is None
    assert rx.sample_count(RED) == 0 and rx.get_dark_samples() == ()


def test_slot_api_is_rejected_outside_tdm_and_for_unknown_slots():
    dual = OPT101Receiver(adc=FakeADC(), mode="dual", dry_run=False)
    with pytest.raises(RuntimeError):
        dual.acquire_tdm_slot(TDM_SLOT_RED)
    rx, _ = tdm_receiver()
    with pytest.raises(ValueError):
        rx.acquire_tdm_slot("green")
    with pytest.raises(ValueError):
        OPT101Receiver(adc=FakeADC(), mode="ppg")


def test_tdm_feeds_both_lanes_even_when_only_one_dual_sensor_is_installed():
    rx = OPT101Receiver(adc=FakeADC(), mode="tdm", enabled_channels=(IR,), dry_run=False)
    assert rx.enabled_channels == (IR, RED)


def test_lane_period_is_one_slot_frame():
    rx, _ = tdm_receiver()
    assert rx.sample_period_s == pytest.approx(config.RX_TDM_SLOT_S * len(config.RX_TDM_SLOTS))


# ─────────────────────────── engine slot master ───────────────────────────

def test_slot_codes_keep_one_led_on_and_switch_the_outgoing_led_first():
    assert SignalEngine._tdm_slot_codes("red", 1800, 1900) == (0, 1900, False)
    assert SignalEngine._tdm_slot_codes("ir", 1800, 1900) == (1800, 0, True)
    assert SignalEngine._tdm_slot_codes("dark", 1800, 1900) == (0, 0, False)


def test_latest_sample_consumes_the_ring_without_counting_underruns():
    engine = SignalEngine()
    assert engine._take_latest_dac_sample() is None
    engine._buf_ir[:3], engine._buf_red[:3] = [10, 20, 30], [11, 21, 31]
    engine._write_idx = 3
    assert engine._take_latest_dac_sample() == (30, 31)
    assert engine._take_latest_dac_sample() is None
    assert engine.get_stats()["underruns"] == 0


def run_tdm(seconds):
    engine = SignalEngine()
    engine.rx_mode = "tdm"
    engine.dac_manager = Mock(is_ready=True)
    receiver = Mock()
    engine.set_tdm_receiver(receiver)
    engine.start_simulation()
    time.sleep(seconds)
    engine._stop_thread()
    return engine, receiver


def test_engine_multiplexes_slots_and_reads_once_per_settled_slot():
    engine, receiver = run_tdm(0.25)
    try:
        slots = [c.args[0] for c in receiver.acquire_tdm_slot.call_args_list]
        assert len(slots) >= 2 * len(config.RX_TDM_SLOTS)
        expected = [config.RX_TDM_SLOTS[i % len(config.RX_TDM_SLOTS)] for i in range(len(slots))]
        assert slots == expected

        writes = engine.dac_manager.set_values.call_args_list
        slot_writes = [c for c in writes if c.kwargs]  # loop writes carry red_first
        assert slot_writes, "TDM loop wrote no LED slots"
        for call in slot_writes:
            ir, red = call.args
            assert ir == 0 or red == 0, f"both LEDs commanded on: {call}"
            # Red is written first only when it is the LED being switched off.
            assert not call.kwargs["red_first"] or red == 0
        # The red slot drives red, the ir slot drives ir, both from the model.
        assert any(c.args[0] == 0 and c.args[1] > 0 for c in slot_writes)
        assert any(c.args[0] > 0 and c.args[1] == 0 for c in slot_writes)
        assert writes[-1].args == (0, 0)
        assert engine.get_stats()["tdm_slots"] == len(slots)
    finally:
        engine.stop_simulation()


def test_engine_tdm_without_receiver_still_multiplexes_and_parks():
    engine = SignalEngine()
    engine.rx_mode = "tdm"
    engine.dac_manager = Mock(is_ready=True)
    engine.start_simulation()
    time.sleep(0.08)
    engine.stop_simulation()
    writes = engine.dac_manager.set_values.call_args_list
    assert any(c.kwargs for c in writes)
    assert writes[-1].args == (0, 0)


# ─────────────────────────── RX panel ───────────────────────────

def test_rx_panel_names_the_shared_sensor_and_shows_dark_level():
    rx, _ = tdm_receiver(FakeADC([1200, 2400, 40]))
    for slot in (TDM_SLOT_RED, TDM_SLOT_IR, TDM_SLOT_DARK):
        rx.acquire_tdm_slot(slot)
    panel = RXPanel.__new__(RXPanel)  # exercise the lane logic without a Tk window
    panel.receiver, panel.language, panel.channels = rx, "en", ((IR, "IR", "#0f0"), (RED, "RED", "#f00"))
    panel._last_update, panel.window_s, panel._rates = 0.0, 8.0, {}
    panel.winfo_ismapped = lambda: True
    captured = {}
    panel.update_lanes = lambda lanes, end_s=None: captured.setdefault("lanes", lanes)

    panel.periodic_update()

    titles = [lane.title for lane in captured["lanes"]]
    assert titles == [f"A{config.RX_TDM_ADC_CHANNEL} TDM  IR", f"A{config.RX_TDM_ADC_CHANNEL} TDM  RED"]
    assert all("dark" in lane.detail for lane in captured["lanes"])
    assert all(lane.max_gap_s >= 1.5 * rx.sample_period_s for lane in captured["lanes"])


# ─────────────────────────── runtime mode switch ───────────────────────────

def test_switching_to_tdm_stops_the_free_running_reader_and_clears_lanes():
    adc = FakeADC()
    rx = OPT101Receiver(adc=adc, mode="dual", enabled_channels=(IR,), dry_run=False,
                        sample_rate_hz=500.0, buffer_size=16)
    assert rx.begin() and rx.start()
    time.sleep(0.03)
    assert rx.sample_count(IR) > 0

    rx.set_mode("tdm")
    assert not rx.is_running and rx.mode == "tdm"
    assert rx.sample_count(IR) == rx.sample_count(RED) == 0
    reads = len(adc.calls)
    time.sleep(0.03)
    assert len(adc.calls) == reads, "no reads may happen without a slot master"

    rx.set_mode("dual")
    time.sleep(0.03)
    assert rx.is_running and rx.enabled_channels == (IR,)
    assert rx.channel_status(RED) == "disabled"
    rx.shutdown()


def test_mode_switch_before_start_does_not_start_acquisition():
    rx = OPT101Receiver(adc=FakeADC(), mode="tdm", enabled_channels=(IR,), dry_run=False)
    rx.set_mode("dual")
    assert not rx.is_running


def test_engine_refuses_mode_change_while_output_runs():
    engine = SignalEngine()
    engine.dac_manager = Mock(is_ready=True)
    receiver = Mock()
    engine.start_simulation()
    try:
        with pytest.raises(RuntimeError):
            engine.set_rx_mode("tdm", receiver)
        receiver.set_mode.assert_not_called()
        assert engine.rx_mode == config.RX_MODE
    finally:
        engine.stop_simulation()
    engine.set_rx_mode("tdm", receiver)
    receiver.set_mode.assert_called_once_with("tdm")
    assert engine.rx_mode == "tdm" and engine._tdm_receiver is receiver
    engine.set_rx_mode("dual", receiver)
    assert engine._tdm_receiver is None
    with pytest.raises(ValueError):
        engine.set_rx_mode("both", receiver)


def test_saved_rx_mode_is_normalised(monkeypatch, tmp_path):
    import config_store
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "CONFIG_JSON_PATH", str(path))
    path.write_text(json.dumps({"rx_mode": "tdm"}))
    assert config_store.load_config()["rx_mode"] == "tdm"
    path.write_text(json.dumps({"rx_mode": "triple"}))
    assert config_store.load_config()["rx_mode"] == "dual"


def _import_main(monkeypatch, argv):
    """main.py parses sys.argv and exports --rx-mode into the environment at
    import time; monkeypatch.setenv first so both are restored afterwards."""
    import importlib
    import sys
    monkeypatch.setenv("PPG_DRY_RUN", "1")
    monkeypatch.setenv("PPG_RX_MODE", "")
    monkeypatch.setattr(sys, "argv", ["main.py"] + argv)
    monkeypatch.delitem(sys.modules, "main", raising=False)
    return importlib.import_module("main")


@pytest.mark.parametrize("saved", ["dual", "tdm"])
def test_exit_save_keeps_settings_rx_mode_not_cli_override(monkeypatch, tmp_path, saved):
    """`main.py --rx-mode X` is a one-run override: saving on exit must keep
    the mode chosen in Settings, or the next run without the flag stays in X."""
    import config_store
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "CONFIG_JSON_PATH", str(path))
    path.write_text(json.dumps({"rx_mode": saved}))
    override = "dual" if saved == "tdm" else "tdm"
    main = _import_main(monkeypatch, ["--dry-run", "--rx-mode", override])
    assert main.resolve_rx_mode(config_store.load_config()) == override
    engine = SignalEngine()
    engine.set_rx_mode(override, Mock())
    main.save_current_config(engine)
    assert json.loads(path.read_text())["rx_mode"] == saved


def test_exit_save_keeps_rx_mode_changed_in_settings(monkeypatch, tmp_path):
    """Settings writes rx_mode immediately; the exit save must not undo it."""
    import config_store
    path = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "CONFIG_JSON_PATH", str(path))
    path.write_text(json.dumps({"rx_mode": "dual"}))
    main = _import_main(monkeypatch, ["--dry-run"])
    engine = SignalEngine()
    engine.set_rx_mode("tdm", Mock())
    config_store.save_config({**config_store.load_config(), "rx_mode": "tdm"})  # Settings
    main.save_current_config(engine)
    assert json.loads(path.read_text())["rx_mode"] == "tdm"


HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@unittest.skipUnless(HAS_DISPLAY, "needs a display server to create a Tk window")
class TestSettingsRxModeSwitch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from ui.ctk_app import CTkApp
        CTkApp._maximize_to_work_area = lambda self: None
        cls.app = CTkApp(language="en")
        cls.saved = []
        cls.app._save_ui_setting = lambda key, value: cls.saved.append((key, value))
        cls.app.withdraw()
        cls.engine = cls.app.engine
        cls.receiver = OPT101Receiver(adc=FakeADC(), mode="dual", dry_run=False)
        cls._real_instance = OPT101Receiver._instance
        OPT101Receiver._instance = cls.receiver
        cls.engine.dac_manager = Mock(is_ready=True)

    @classmethod
    def tearDownClass(cls):
        cls.engine.stop_simulation()
        cls.engine.set_rx_mode("dual")
        OPT101Receiver._instance = cls._real_instance
        cls.app.on_closing()

    def setUp(self):
        self.app.open_signal_setup()
        self.app.update()

    def tearDown(self):
        self.app.close_signal_setup()

    def test_choosing_tdm_switches_engine_and_receiver_and_persists_it(self):
        self.app._set_rx_mode_from_label("1 × OPT101 (TDM)")
        self.assertEqual(self.engine.rx_mode, "tdm")
        self.assertEqual(self.receiver.mode, "tdm")
        self.assertIn(("rx_mode", "tdm"), self.saved)
        self.assertEqual(self.app.rx_mode_switch.get(), "1 × OPT101 (TDM)")
        self.app._set_rx_mode_from_label("2 × OPT101 (dual)")
        self.assertEqual(self.engine.rx_mode, "dual")

    def switch_states(self):
        # CTkSegmentedButton cannot cget("state"); its segment buttons can.
        return {b.cget("state") for b in self.app.rx_mode_switch._buttons_dict.values()}

    def test_switch_is_locked_while_output_runs(self):
        self.engine.start_simulation()
        try:
            self.app.update_gui()
            self.assertEqual(self.switch_states(), {"disabled"})
            self.app._set_rx_mode_from_label("1 × OPT101 (TDM)")
            self.assertEqual(self.engine.rx_mode, "dual")
            self.assertEqual(self.app.rx_mode_switch.get(), "2 × OPT101 (dual)")
        finally:
            self.engine.stop_simulation()
        self.app.update_gui()
        self.assertEqual(self.switch_states(), {"normal"})
