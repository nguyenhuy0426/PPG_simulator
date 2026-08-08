"""
Phase 5 tests — dual-channel OPT101 RX acquisition via Grove Base Hat ADC.

Covers: fixed channel mapping (A0=IR, A2=Red, A1 rejected), read order,
timestamp monotonicity, bounded per-channel buffers, invalid ADC code
rejection, saturation flagging, I2C error / disconnect handling (including
grove.adc's sys.exit(2)-on-IOError behavior surfacing as SystemExit),
one-channel-missing isolation, no-fabricated-values guarantee, stale-data
detection, dry-run labeling, thread-safety of concurrent reads, and a static
guard that the RX module contains no DAC write path.

All tests are hardware-free: they inject a scripted fake ADC object or use
explicit dry-run mode. No I2C access ever occurs.
Run: python3 -m unittest tests.test_phase5_rx
"""

import ast
import inspect
import logging
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import hw.opt101_rx as rx_module
from hw.opt101_rx import (
    OPT101Receiver,
    RXSample,
    raw_to_millivolts,
    RX_STATUS_OK,
    RX_STATUS_SATURATED,
    RX_STATUS_INVALID,
    RX_STATUS_ERROR,
    RX_STATUS_DISCONNECTED,
    RX_STATUS_DRY_RUN,
)

IR = config.ADC_CHANNEL_IR
RED = config.ADC_CHANNEL_RED


def setUpModule():
    # Error-path tests intentionally trigger rate-limited log.error calls;
    # keep the test run output clean.
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)


# ─────────────────────────── Fakes ───────────────────────────

class ScriptedADC:
    """Fake grove.adc.ADC: records every read_raw(channel) call and returns
    (or raises) whatever the per-channel behavior callable dictates."""

    DEFAULT_RAW = 1000

    def __init__(self):
        self.calls = []
        self.behavior = {}  # channel -> callable(channel) -> raw (may raise)

    def read_raw(self, channel):
        self.calls.append(channel)
        fn = self.behavior.get(channel)
        if fn is None:
            return self.DEFAULT_RAW
        return fn(channel)


def make_receiver(adc=None, **kwargs):
    """Receiver with an injected fake ADC, hardware mode, tiny defaults."""
    adc = adc if adc is not None else ScriptedADC()
    kwargs.setdefault("dry_run", False)
    kwargs.setdefault("buffer_size", 16)
    kwargs.setdefault("sample_rate_hz", 1000.0)
    rx = OPT101Receiver(adc=adc, **kwargs)
    assert rx.begin() is True
    adc.calls.clear()  # drop the begin() probe read from the journal
    return rx, adc


def raise_oserror(channel):
    raise OSError("simulated I2C NACK")


def raise_systemexit(channel):
    # grove.adc read_register() calls sys.exit(2) on IOError.
    raise SystemExit(2)


# ─────────────────────────── Channel mapping ───────────────────────────

class TestChannelMapping(unittest.TestCase):
    def test_config_constants_match_verified_hardware(self):
        # [VERIFIED-USER 2026-07-12]: IR on A0, Red on A2, A1 unused.
        self.assertEqual(config.ADC_CHANNEL_IR, 0)
        self.assertEqual(config.ADC_CHANNEL_RED, 2)
        # [VERIFIED-USER]: Grove Base HAT MCU is MM32 → ADC I2C address 0x08
        # (the STM32 revision of the same HAT answers at 0x04).
        self.assertEqual(config.GROVE_ADC_ADDR, 0x08)

    def test_acquisition_reads_a0_then_a2_only(self):
        rx, adc = make_receiver()
        for _ in range(3):
            rx._acquire_once()
        self.assertEqual(adc.calls, [IR, RED] * 3)
        self.assertNotIn(1, adc.calls)  # A1 must never be read

    def test_a1_and_unknown_channels_rejected(self):
        rx, _ = make_receiver()
        for bad in (1, 3, -1, None, "A0"):
            with self.assertRaises(ValueError):
                rx.get_latest(bad)
            with self.assertRaises(ValueError):
                rx.channel_status(bad)

    def test_channels_store_into_separate_buffers(self):
        rx, adc = make_receiver()
        adc.behavior[IR] = lambda ch: 111
        adc.behavior[RED] = lambda ch: 222
        rx._acquire_once()
        self.assertEqual(rx.get_latest(IR).raw, 111)
        self.assertEqual(rx.get_latest(RED).raw, 222)


# ─────────────────────────── Samples, timestamps, buffers ───────────────────────────

class TestSamplesAndBuffers(unittest.TestCase):
    def test_sample_has_timestamp_raw_and_saturation_flag(self):
        rx, _ = make_receiver()
        rx._acquire_once()
        s = rx.get_latest(IR)
        self.assertIsInstance(s, RXSample)
        self.assertIsInstance(s.timestamp, float)
        self.assertEqual(s.raw, ScriptedADC.DEFAULT_RAW)
        self.assertFalse(s.saturated)

    def test_timestamps_are_monotonic_non_decreasing(self):
        rx, _ = make_receiver()
        for _ in range(10):
            rx._acquire_once()
        for ch in (IR, RED):
            ts = [s.timestamp for s in rx.get_samples(ch)]
            self.assertEqual(len(ts), 10)
            self.assertEqual(ts, sorted(ts))

    def test_buffers_are_bounded_and_keep_newest(self):
        rx, adc = make_receiver(buffer_size=8)
        counter = iter(range(100, 200))
        adc.behavior[IR] = lambda ch: next(counter)
        for _ in range(20):
            rx._acquire_once()
        self.assertEqual(rx.sample_count(IR), 8)
        raws = [s.raw for s in rx.get_samples(IR)]
        self.assertEqual(raws, list(range(112, 120)))  # oldest 12 evicted

    def test_get_samples_returns_immutable_snapshot(self):
        rx, _ = make_receiver()
        rx._acquire_once()
        snap = rx.get_samples(IR)
        self.assertIsInstance(snap, tuple)
        rx._acquire_once()
        self.assertEqual(len(snap), 1)  # snapshot unaffected by later samples

    def test_get_samples_n_limits_to_most_recent(self):
        rx, adc = make_receiver()
        counter = iter(range(10))
        adc.behavior[RED] = lambda ch: next(counter)
        for _ in range(10):
            rx._acquire_once()
        raws = [s.raw for s in rx.get_samples(RED, n=3)]
        self.assertEqual(raws, [7, 8, 9])


# ─────────────────────────── Validation & saturation ───────────────────────────

class TestValidationAndSaturation(unittest.TestCase):
    def test_invalid_codes_discarded_and_counted(self):
        rx, adc = make_receiver()
        for bad in (-1, 4096, 65535, None, 3.5, "x", True):
            adc.behavior[IR] = lambda ch, v=bad: v
            rx._acquire_once()
        self.assertEqual(rx.sample_count(IR), 0)  # nothing fabricated/stored
        self.assertEqual(rx.invalid_count(IR), 7)
        self.assertEqual(rx.channel_status(IR), RX_STATUS_INVALID)
        # Red channel (default valid value) is unaffected.
        self.assertEqual(rx.sample_count(RED), 7)
        self.assertEqual(rx.channel_status(RED), RX_STATUS_OK)

    def test_full_scale_sample_stored_but_flagged_saturated(self):
        rx, adc = make_receiver()
        adc.behavior[IR] = lambda ch: config.ADC_MAX_VALUE
        rx._acquire_once()
        s = rx.get_latest(IR)
        self.assertEqual(s.raw, 4095)
        self.assertTrue(s.saturated)
        self.assertEqual(rx.channel_status(IR), RX_STATUS_SATURATED)
        self.assertEqual(rx.saturation_count(IR), 1)
        # Recovery to a mid-scale value restores OK status.
        adc.behavior[IR] = lambda ch: 2000
        rx._acquire_once()
        self.assertEqual(rx.channel_status(IR), RX_STATUS_OK)

    def test_zero_code_is_valid_dark_level_not_error(self):
        rx, adc = make_receiver()
        adc.behavior[RED] = lambda ch: 0
        rx._acquire_once()
        s = rx.get_latest(RED)
        self.assertEqual(s.raw, 0)
        self.assertFalse(s.saturated)
        self.assertEqual(rx.channel_status(RED), RX_STATUS_OK)

    def test_raw_to_millivolts_uses_adc_reference(self):
        self.assertEqual(raw_to_millivolts(0), 0.0)
        # [VERIFIED-USER]: Grove ADC reference = 3.28 V.
        self.assertAlmostEqual(raw_to_millivolts(config.ADC_MAX_VALUE), 3280.0)

    def test_raw_to_millivolts_tracks_adc_reference_not_dac_fullscale(self):
        # The RX scale factor must come from ADC_VOLTAGE_REF (Grove Base HAT,
        # RX path), never from DAC_FULLSCALE_V (MCP4725, TX path). Both are
        # 3.28 V on this hardware, so a numeric comparison can no longer tell
        # them apart — perturb the RX constant and check the output follows it.
        original = rx_module.ADC_VOLTAGE_REF
        try:
            rx_module.ADC_VOLTAGE_REF = 1.0
            self.assertAlmostEqual(raw_to_millivolts(config.ADC_MAX_VALUE), 1000.0)
        finally:
            rx_module.ADC_VOLTAGE_REF = original
        self.assertAlmostEqual(raw_to_millivolts(config.ADC_MAX_VALUE),
                               config.ADC_VOLTAGE_REF * 1000.0)


# ─────────────────────────── Errors, disconnects, isolation ───────────────────────────

class TestErrorHandling(unittest.TestCase):
    def test_oserror_counted_no_sample_appended(self):
        rx, adc = make_receiver()
        adc.behavior[IR] = raise_oserror
        rx._acquire_once()
        self.assertEqual(rx.error_count(IR), 1)
        self.assertEqual(rx.sample_count(IR), 0)
        self.assertEqual(rx.channel_status(IR), RX_STATUS_ERROR)

    def test_grove_sysexit_is_contained_as_channel_error(self):
        # grove.adc calls sys.exit(2) on IOError; SystemExit must never
        # propagate out of the acquisition path.
        rx, adc = make_receiver()
        adc.behavior[RED] = raise_systemexit
        try:
            rx._acquire_once()
        except BaseException as e:  # pragma: no cover - fails the test
            self.fail(f"exception escaped acquisition: {e!r}")
        self.assertEqual(rx.error_count(RED), 1)
        self.assertEqual(rx.sample_count(RED), 0)
        self.assertEqual(rx.channel_status(RED), RX_STATUS_ERROR)

    def test_begin_probe_sysexit_returns_false(self):
        adc = ScriptedADC()
        adc.behavior[IR] = raise_systemexit
        rx = OPT101Receiver(adc=adc, dry_run=False)
        self.assertFalse(rx.begin())
        self.assertFalse(rx.is_ready)
        self.assertFalse(rx.start())

    def test_disconnected_after_consecutive_error_threshold(self):
        rx, adc = make_receiver()
        adc.behavior[IR] = raise_oserror
        for _ in range(config.RX_DISCONNECT_ERROR_THRESHOLD - 1):
            rx._acquire_once()
        self.assertEqual(rx.channel_status(IR), RX_STATUS_ERROR)
        rx._acquire_once()  # crosses the threshold
        self.assertEqual(rx.channel_status(IR), RX_STATUS_DISCONNECTED)
        self.assertEqual(rx.error_count(IR), config.RX_DISCONNECT_ERROR_THRESHOLD)

    def test_successful_read_resets_consecutive_errors(self):
        rx, adc = make_receiver()
        adc.behavior[IR] = raise_oserror
        for _ in range(config.RX_DISCONNECT_ERROR_THRESHOLD):
            rx._acquire_once()
        self.assertEqual(rx.channel_status(IR), RX_STATUS_DISCONNECTED)
        adc.behavior[IR] = lambda ch: 1500  # cable back in
        rx._acquire_once()
        self.assertEqual(rx.channel_status(IR), RX_STATUS_OK)
        adc.behavior[IR] = raise_oserror  # a single new error is not disconnect
        rx._acquire_once()
        self.assertEqual(rx.channel_status(IR), RX_STATUS_ERROR)

    def test_one_channel_failing_does_not_block_the_other(self):
        rx, adc = make_receiver()
        adc.behavior[IR] = raise_oserror
        for _ in range(15):
            rx._acquire_once()
        self.assertEqual(rx.sample_count(IR), 0)
        self.assertEqual(rx.channel_status(IR), RX_STATUS_DISCONNECTED)
        self.assertEqual(rx.sample_count(RED), 15)
        self.assertEqual(rx.channel_status(RED), RX_STATUS_OK)

    def test_no_fabricated_values_on_failure(self):
        rx, adc = make_receiver()
        # Never-read channel: latest is None, not a made-up value.
        self.assertIsNone(rx.get_latest(IR))
        # One real sample, then failures: latest stays that real sample.
        adc.behavior[IR] = lambda ch: 1234
        rx._acquire_once()
        adc.behavior[IR] = raise_oserror
        for _ in range(5):
            rx._acquire_once()
        self.assertEqual(rx.sample_count(IR), 1)
        self.assertEqual(rx.get_latest(IR).raw, 1234)


# ─────────────────────────── Stale-data detection ───────────────────────────

class TestStaleData(unittest.TestCase):
    def test_channel_with_no_samples_is_stale(self):
        rx, _ = make_receiver()
        self.assertTrue(rx.is_stale(IR))

    def test_staleness_relative_to_newest_sample(self):
        rx, _ = make_receiver()
        rx._acquire_once()
        t0 = rx.get_latest(IR).timestamp
        self.assertFalse(rx.is_stale(IR, now=t0 + 0.1))
        self.assertFalse(rx.is_stale(IR, now=t0 + config.RX_STALE_THRESHOLD_S))
        self.assertTrue(rx.is_stale(IR, now=t0 + config.RX_STALE_THRESHOLD_S + 0.01))

    def test_staleness_threshold_is_injectable(self):
        rx, _ = make_receiver()
        rx._acquire_once()
        t0 = rx.get_latest(RED).timestamp
        self.assertTrue(rx.is_stale(RED, now=t0 + 0.02, threshold_s=0.01))
        self.assertFalse(rx.is_stale(RED, now=t0 + 0.02, threshold_s=0.05))


# ─────────────────────────── Dry-run labeling ───────────────────────────

class TestDryRun(unittest.TestCase):
    def test_dry_run_is_labeled_and_produces_no_samples(self):
        rx = OPT101Receiver(dry_run=True)
        self.assertTrue(rx.begin())
        self.assertTrue(rx.is_simulated)
        self.assertTrue(rx.is_ready)
        # No acquisition thread, no fabricated data — ever.
        self.assertFalse(rx.start())
        self.assertFalse(rx.is_running)
        for ch in (IR, RED):
            self.assertEqual(rx.channel_status(ch), RX_STATUS_DRY_RUN)
            self.assertEqual(rx.sample_count(ch), 0)
            self.assertIsNone(rx.get_latest(ch))
            self.assertTrue(rx.is_stale(ch))
        rx.shutdown()
        self.assertFalse(rx.is_ready)

    def test_hardware_mode_is_not_labeled_simulated(self):
        rx, _ = make_receiver()
        self.assertFalse(rx.is_simulated)


# ─────────────────────────── Thread lifecycle & concurrency ───────────────────────────

class TestThreading(unittest.TestCase):
    def test_thread_acquires_while_main_thread_reads(self):
        rx, _ = make_receiver(sample_rate_hz=2000.0, buffer_size=4096)
        self.assertTrue(rx.start())
        self.assertTrue(rx.is_running)
        deadline = time.monotonic() + 2.0
        while rx.sample_count(IR) < 20 and time.monotonic() < deadline:
            # Concurrent consumer access must never raise or see corruption.
            _ = rx.get_latest(IR)
            _ = rx.get_samples(RED, n=5)
            _ = rx.channel_status(IR)
            time.sleep(0.001)
        rx.stop()
        self.assertFalse(rx.is_running)
        self.assertIsNone(rx._thread)
        self.assertGreaterEqual(rx.sample_count(IR), 20)
        ts = [s.timestamp for s in rx.get_samples(IR)]
        self.assertEqual(ts, sorted(ts))

    def test_rx_thread_is_named_daemon_single_owner(self):
        rx, _ = make_receiver(sample_rate_hz=2000.0)
        rx.start()
        threads = [t for t in threading.enumerate() if t.name == "OPT101Rx"]
        self.assertEqual(len(threads), 1)
        self.assertTrue(threads[0].daemon)
        rx.start()  # idempotent — must not spawn a second owner
        threads = [t for t in threading.enumerate() if t.name == "OPT101Rx"]
        self.assertEqual(len(threads), 1)
        rx.shutdown()

    def test_stop_without_start_is_safe(self):
        rx, _ = make_receiver()
        rx.stop()
        rx.shutdown()
        self.assertFalse(rx.is_ready)

    def test_get_instance_returns_process_singleton(self):
        old = OPT101Receiver._instance
        OPT101Receiver._instance = None
        try:
            a = OPT101Receiver.get_instance()
            b = OPT101Receiver.get_instance()
            self.assertIs(a, b)
        finally:
            OPT101Receiver._instance = old


# ─────────────────────────── Static guards ───────────────────────────

class TestRxHasNoDacPath(unittest.TestCase):
    """AST-level guards: docstrings may mention the TX stack when documenting
    bus sharing, but the RX code must never import or invoke it."""

    @classmethod
    def setUpClass(cls):
        tree = ast.parse(inspect.getsource(rx_module))
        cls.imports = set()
        cls.attributes = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                cls.imports |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                cls.imports.add(node.module or "")
                cls.imports |= {alias.name for alias in node.names}
            elif isinstance(node, ast.Attribute):
                cls.attributes.add(node.attr)

    def test_rx_module_imports_no_dac_or_tx_stack(self):
        for forbidden in ("busio", "board", "adafruit_mcp4725",
                          "hw.dac_manager", "dac_manager", "DACManager",
                          "DAC_ADDR_IR", "DAC_ADDR_RED"):
            self.assertFalse(
                any(forbidden == name or name.startswith(forbidden + ".")
                    for name in self.imports),
                f"RX module must not import {forbidden!r}")

    def test_rx_module_performs_no_dac_writes(self):
        # set_values() and .raw_value are the only DAC write entry points.
        self.assertNotIn("set_values", self.attributes)
        self.assertNotIn("raw_value", self.attributes)

    def test_rx_module_uses_only_verified_grove_read_method(self):
        # read_raw(channel) is the only grove.adc data method Phase 5 uses;
        # read_voltage()/read() are deliberately not called (bus budget).
        self.assertIn("read_raw", self.attributes)
        self.assertNotIn("read_voltage", self.attributes)


if __name__ == "__main__":
    unittest.main()
