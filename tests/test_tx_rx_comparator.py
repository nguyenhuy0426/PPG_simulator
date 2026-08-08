"""
tests/test_tx_rx_comparator.py — Stage 4 TX/RX comparison tests (TDD, RED first).

Run: python3 -m unittest tests.test_tx_rx_comparator

Properties under test (task-mandated):

  * TX (1 kHz) and RX (100 Hz) rates differ — alignment is by TIMESTAMP only.
    A test constructs data where index pairing gives a demonstrably different
    answer than timestamp pairing.
  * Interpolation is BOUNDED: refused outside the series' own time span
    (boundary) and refused when the bracketing gap exceeds the limit.
  * The overlap window is explicit and reported.
  * Best-lag search by normalized cross-correlation; delay reported.
  * Normalized RMS shape error, gain ratio, DC offset.
  * Per channel: AC pk-pk, AC RMS, DC mean, measured PI = AC/DC*100.
  * R ratio from measured RX values; measured SpO2 ONLY via the configured
    calibration, and ONLY when neither channel is invalid, clipped, saturated,
    stale or short of data.
  * Peak timing error, interval statistics, jitter.
  * Dropped / stale / saturation / clipping counts are carried through.
  * Missing data stays missing: failed reads never become zeros or TX values.
  * Raw session files are never modified by analysis.
  * matplotlib is optional — plotting degrades to a labelled skip.
"""

import csv
import json
import math
import os
import tempfile
import unittest

import config
from core.tx_rx_logger import (
    RX_FIELDS,
    TX_FIELDS,
    RxRecord,
    TxRecord,
    build_session_metadata,
)
from core import tx_rx_comparator as cmp


# ──────────────────────────────────────────────────────────── row/file helpers

def tx_row(channel="ir", sequence_id=0, t_ns=0, voltage=1.0, code=1248,
           success=True, error_type="", dropped=0):
    """A valid TX CSV row, built through the real TxRecord (schema-faithful)."""
    addr = config.DAC_ADDR_IR if channel == "ir" else config.DAC_ADDR_RED
    rec = TxRecord(
        session_id="sess", sequence_id=sequence_id, t_mono_ns=t_ns,
        channel=channel, dac_address=addr, model_timestamp_s=t_ns / 1e9,
        target_hr_bpm=75.0, target_rr_bpm=15.0, target_spo2_pct=98.0,
        target_pi_pct=2.0, target_r_ratio=0.48,
        requested_waveform_mv=voltage * 1000.0, requested_dac_voltage_v=voltage,
        dac_code=code, ideal_dac_voltage_v_calculated=code * 3.28 / 4096.0,
        write_start_mono_ns=t_ns, write_end_mono_ns=t_ns + 400_000,
        write_duration_ns=400_000, success=success, error_type=error_type)
    return rec.row(dropped)


def rx_row(channel="ir", sequence_id=0, t_ns=0, voltage=1.0, success=True,
           valid=True, stale=False, saturated=False, clipped=False,
           error_type="", dropped=0):
    """A valid RX CSV row.  voltage=None models a failed read (no data)."""
    grove = "A0" if channel == "ir" else "A2"
    if voltage is None:
        code = None
        volts = None
    else:
        code = max(0, min(config.ADC_MAX_VALUE,
                          int(round(voltage / config.ADC_VOLTAGE_REF
                                    * config.ADC_MAX_VALUE))))
        volts = code * config.ADC_VOLTAGE_REF / config.ADC_MAX_VALUE
    rec = RxRecord(
        session_id="sess", sequence_id=sequence_id, t_mono_ns=t_ns,
        channel=channel, grove_channel=grove,
        adc_address=config.GROVE_ADC_ADDR, raw_code=code,
        converted_voltage_v=volts, read_start_mono_ns=t_ns,
        read_end_mono_ns=t_ns + 200_000, read_duration_ns=200_000,
        valid=valid, stale=stale, saturated=saturated, clipped=clipped,
        success=success, error_type=error_type)
    return rec.row(dropped)


def write_csv(path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def synth_pair(channel="ir", duration_s=2.0, tx_hz=1000.0, rx_hz=100.0,
               sig_hz=1.25, dc=1.200, ac=0.060, delay_s=0.020, gain=0.500,
               rx_dc_offset=0.150, rx_t0_s=0.0, flag_last=None):
    """Synthetic TX/RX row pairs for one channel.

    TX command:  dc + ac*sin(2*pi*sig_hz*t)
    RX detector: rx_dc_offset + gain * tx(t - delay_s)   (quantized by the ADC)

    flag_last: optional dict of RxRecord flags applied to the final RX row
    (e.g. {"clipped": True}) so gating can be exercised.
    """
    def tx_v(t):
        return dc + ac * math.sin(2.0 * math.pi * sig_hz * t)

    tx_rows = []
    n_tx = int(duration_s * tx_hz)
    for i in range(n_tx):
        t = i / tx_hz
        tx_rows.append(tx_row(channel=channel, sequence_id=i,
                              t_ns=int(round(t * 1e9)), voltage=tx_v(t),
                              code=int(round(tx_v(t) / 3.28 * 4095))))
    rx_rows = []
    n_rx = int(duration_s * rx_hz)
    for i in range(n_rx):
        t = rx_t0_s + i / rx_hz
        src = t - delay_s
        v = rx_dc_offset + gain * tx_v(src)
        flags = {}
        if flag_last and i == n_rx - 1:
            flags = dict(flag_last)
        rx_rows.append(rx_row(channel=channel, sequence_id=i,
                              t_ns=int(round(t * 1e9)), voltage=v, **flags))
    return tx_rows, rx_rows


def make_session(base_dir, session_id="sess", tx_ir=(), tx_red=(),
                 rx_ir=(), rx_red=(), metadata=None):
    d = os.path.join(base_dir, session_id)
    os.makedirs(d)
    write_csv(os.path.join(d, "tx_ir.csv"), TX_FIELDS, tx_ir)
    write_csv(os.path.join(d, "tx_red.csv"), TX_FIELDS, tx_red)
    write_csv(os.path.join(d, "rx_ir.csv"), RX_FIELDS, rx_ir)
    write_csv(os.path.join(d, "rx_red.csv"), RX_FIELDS, rx_red)
    md = metadata if metadata is not None else build_session_metadata("dry-run")
    md = dict(md)
    md["session_id"] = session_id
    with open(os.path.join(d, "session_metadata.json"), "w") as f:
        json.dump(md, f, indent=2)
    return d


class TempDirTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()


# ───────────────────────────────────────────────────────────────── 1. loaders

class TestLoaders(TempDirTest):

    def test_tx_series_uses_requested_voltage_and_monotonic_time(self):
        p = os.path.join(self.tmp, "tx_ir.csv")
        write_csv(p, TX_FIELDS, [
            tx_row(t_ns=0, voltage=1.0, sequence_id=0),
            tx_row(t_ns=1_000_000, voltage=1.5, sequence_id=1),
        ])
        s = cmp.load_tx_series(p)
        self.assertEqual(s.kind, "tx")
        self.assertEqual(s.channel, "ir")
        self.assertEqual(s.times_ns, (0, 1_000_000))
        self.assertEqual(s.values, (1.0, 1.5))

    def test_failed_tx_write_is_counted_and_excluded_from_samples(self):
        p = os.path.join(self.tmp, "tx_ir.csv")
        write_csv(p, TX_FIELDS, [
            tx_row(t_ns=0, voltage=1.0),
            tx_row(t_ns=1_000_000, voltage=1.5, success=False,
                   error_type="i2c_oserror"),
            tx_row(t_ns=2_000_000, voltage=2.0),
        ])
        s = cmp.load_tx_series(p)
        self.assertEqual(s.n, 2)
        self.assertEqual(s.quality.n_rows, 3)
        self.assertEqual(s.quality.n_failed, 1)
        self.assertEqual(s.times_ns, (0, 2_000_000))

    def test_rx_series_loads_converted_voltage(self):
        p = os.path.join(self.tmp, "rx_red.csv")
        write_csv(p, RX_FIELDS, [rx_row(channel="red", t_ns=0, voltage=1.0)])
        s = cmp.load_rx_series(p)
        self.assertEqual(s.kind, "rx")
        self.assertEqual(s.channel, "red")
        self.assertEqual(s.n, 1)
        self.assertAlmostEqual(s.values[0], 1.0, places=3)

    def test_failed_rx_read_stays_missing_never_zero(self):
        p = os.path.join(self.tmp, "rx_ir.csv")
        write_csv(p, RX_FIELDS, [
            rx_row(t_ns=0, voltage=1.0),
            rx_row(t_ns=10_000_000, voltage=None, success=False, valid=False,
                   error_type="i2c_ioerror"),
        ])
        s = cmp.load_rx_series(p)
        self.assertEqual(s.n, 1)
        self.assertEqual(s.quality.n_failed, 1)
        self.assertEqual(s.quality.n_missing_value, 1)
        self.assertNotIn(0.0, s.values)

    def test_invalid_flagged_rx_row_excluded_but_counted(self):
        p = os.path.join(self.tmp, "rx_ir.csv")
        write_csv(p, RX_FIELDS, [
            rx_row(t_ns=0, voltage=1.0),
            rx_row(t_ns=10_000_000, voltage=1.1, valid=False),
        ])
        s = cmp.load_rx_series(p)
        self.assertEqual(s.n, 1)
        self.assertEqual(s.quality.n_rows, 2)
        self.assertEqual(s.quality.n_valid, 1)

    def test_stale_saturated_clipped_counted(self):
        p = os.path.join(self.tmp, "rx_ir.csv")
        write_csv(p, RX_FIELDS, [
            rx_row(t_ns=0, voltage=1.0),
            rx_row(t_ns=10_000_000, voltage=1.0, stale=True),
            rx_row(t_ns=20_000_000, voltage=3.2, saturated=True),
            rx_row(t_ns=30_000_000, voltage=2.1, clipped=True),
        ])
        s = cmp.load_rx_series(p)
        self.assertEqual(s.quality.n_stale, 1)
        self.assertEqual(s.quality.n_saturated, 1)
        self.assertEqual(s.quality.n_clipped, 1)

    def test_dropped_counter_carried_through_as_max(self):
        p = os.path.join(self.tmp, "rx_ir.csv")
        write_csv(p, RX_FIELDS, [
            rx_row(t_ns=0, voltage=1.0, dropped=0),
            rx_row(t_ns=10_000_000, voltage=1.0, dropped=7),
            rx_row(t_ns=20_000_000, voltage=1.0, dropped=7),
        ])
        s = cmp.load_rx_series(p)
        self.assertEqual(s.quality.dropped_queue_full_max, 7)

    def test_timestamp_disorder_is_counted_and_sorted(self):
        p = os.path.join(self.tmp, "rx_ir.csv")
        write_csv(p, RX_FIELDS, [
            rx_row(t_ns=20_000_000, voltage=1.0),
            rx_row(t_ns=10_000_000, voltage=1.1),
            rx_row(t_ns=30_000_000, voltage=1.2),
        ])
        s = cmp.load_rx_series(p)
        self.assertEqual(s.quality.n_out_of_order, 1)
        self.assertEqual(s.times_ns, (10_000_000, 20_000_000, 30_000_000))

    def test_empty_file_gives_empty_series_not_an_exception(self):
        p = os.path.join(self.tmp, "tx_ir.csv")
        write_csv(p, TX_FIELDS, [])
        s = cmp.load_tx_series(p)
        self.assertEqual(s.n, 0)
        self.assertIsNone(s.start_ns)
        self.assertIsNone(s.duration_s)

    def test_load_session_reads_four_streams_and_metadata(self):
        tx_ir, rx_ir = synth_pair("ir", duration_s=0.5)
        tx_red, rx_red = synth_pair("red", duration_s=0.5)
        d = make_session(self.tmp, "s1", tx_ir, tx_red, rx_ir, rx_red)
        sess = cmp.load_session(d)
        self.assertEqual(sess.session_id, "s1")
        self.assertEqual(sess.tx_ir.channel, "ir")
        self.assertEqual(sess.rx_red.channel, "red")
        self.assertEqual(sess.metadata["mode"], "dry-run")
        self.assertEqual(sess.metadata["adc_address"], config.GROVE_ADC_ADDR)

    def test_load_session_rejects_missing_directory(self):
        with self.assertRaises(FileNotFoundError):
            cmp.load_session(os.path.join(self.tmp, "nope"))


# ─────────────────────────────────────────────── 2. overlap and interpolation

class TestOverlapAndInterpolation(unittest.TestCase):

    def _series(self, times_ns, values, kind="tx", channel="ir"):
        return cmp.Series(
            kind=kind, channel=channel,
            samples=tuple(cmp.Sample(t, v) for t, v in zip(times_ns, values)),
            quality=cmp.SeriesQuality())

    def test_overlap_window_is_explicit(self):
        a = self._series([0, 1_000_000_000], [0.0, 1.0])
        b = self._series([500_000_000, 2_000_000_000], [0.0, 1.0], kind="rx")
        self.assertEqual(cmp.overlap_window(a, b),
                         (500_000_000, 1_000_000_000))

    def test_no_overlap_returns_none(self):
        a = self._series([0, 100_000_000], [0.0, 1.0])
        b = self._series([200_000_000, 300_000_000], [0.0, 1.0], kind="rx")
        self.assertIsNone(cmp.overlap_window(a, b))

    def test_overlap_of_empty_series_is_none(self):
        a = self._series([], [])
        b = self._series([0, 1], [0.0, 1.0], kind="rx")
        self.assertIsNone(cmp.overlap_window(a, b))

    def test_interpolate_at_node_returns_node_value(self):
        s = self._series([0, 1_000_000], [1.0, 2.0])
        self.assertEqual(cmp.interpolate_at(s, 1_000_000, 2_000_000), 2.0)

    def test_interpolate_midpoint_is_linear(self):
        s = self._series([0, 1_000_000], [1.0, 2.0])
        self.assertAlmostEqual(cmp.interpolate_at(s, 500_000, 2_000_000), 1.5)

    def test_interpolation_refused_before_first_sample(self):
        s = self._series([1_000_000, 2_000_000], [1.0, 2.0])
        self.assertIsNone(cmp.interpolate_at(s, 500_000, 2_000_000))

    def test_interpolation_refused_after_last_sample(self):
        s = self._series([1_000_000, 2_000_000], [1.0, 2.0])
        self.assertIsNone(cmp.interpolate_at(s, 2_500_000, 2_000_000))

    def test_interpolation_refused_when_gap_exceeds_bound(self):
        s = self._series([0, 50_000_000], [1.0, 2.0])   # 50 ms hole
        self.assertIsNone(cmp.interpolate_at(s, 25_000_000, 5_000_000))

    def test_interpolation_allowed_when_gap_equals_bound(self):
        s = self._series([0, 5_000_000], [1.0, 2.0])
        self.assertAlmostEqual(
            cmp.interpolate_at(s, 2_500_000, 5_000_000), 1.5)

    def test_interpolate_on_empty_series_is_none(self):
        self.assertIsNone(cmp.interpolate_at(self._series([], []), 0, 1000))


# ────────────────────────────────────────── 3. alignment is never by index

class TestAlignmentByTimestamp(TempDirTest):

    def _load(self, tx_rows, rx_rows):
        ptx = os.path.join(self.tmp, "tx_ir.csv")
        prx = os.path.join(self.tmp, "rx_ir.csv")
        write_csv(ptx, TX_FIELDS, tx_rows)
        write_csv(prx, RX_FIELDS, rx_rows)
        return cmp.load_tx_series(ptx), cmp.load_rx_series(prx)

    def test_pairs_come_from_timestamps_not_array_index(self):
        # TX value == its own time in seconds; 1 kHz for 1 s.
        tx_rows = [tx_row(t_ns=i * 1_000_000, voltage=i / 1000.0,
                          sequence_id=i, code=i) for i in range(1000)]
        # RX at 100 Hz: 10x fewer samples.  Index pairing would match RX i
        # with TX i (t = i ms); timestamp pairing must give t = i*10 ms.
        rx_rows = [rx_row(t_ns=i * 10_000_000, voltage=1.0, sequence_id=i)
                   for i in range(100)]
        tx, rx = self._load(tx_rows, rx_rows)
        pairs = cmp.align_series(tx, rx, max_gap_s=0.005)
        self.assertEqual(len(pairs.tx_values), len(pairs.rx_values))
        self.assertGreater(len(pairs.tx_values), 90)
        for t_ns, tx_v in zip(pairs.t_ns, pairs.tx_values):
            self.assertAlmostEqual(tx_v, t_ns / 1e9, places=6)
        # Explicit index-pairing counter-check: the 50th pair is t = 0.49 s,
        # not the 50th TX sample (0.049 s).
        self.assertAlmostEqual(pairs.tx_values[49], 0.490, places=6)
        self.assertNotAlmostEqual(pairs.tx_values[49], tx.values[49], places=3)

    def test_unequal_rates_do_not_raise_and_pair_count_follows_rx(self):
        tx_rows = [tx_row(t_ns=i * 1_000_000, voltage=1.0) for i in range(500)]
        rx_rows = [rx_row(t_ns=i * 7_000_000, voltage=0.5) for i in range(70)]
        tx, rx = self._load(tx_rows, rx_rows)
        pairs = cmp.align_series(tx, rx, max_gap_s=0.005)
        # TX covers 0..0.499 s; RX samples beyond that are refused, not paired.
        self.assertEqual(len(pairs.t_ns), 72 - 1 - 1)  # 0..0.483 s inclusive
        self.assertGreater(pairs.n_refused_boundary, 0)

    def test_samples_outside_overlap_window_are_refused_and_counted(self):
        tx_rows = [tx_row(t_ns=100_000_000 + i * 1_000_000, voltage=1.0)
                   for i in range(100)]           # 0.100 .. 0.199 s
        rx_rows = [rx_row(t_ns=i * 10_000_000, voltage=0.5)
                   for i in range(30)]            # 0.000 .. 0.290 s
        tx, rx = self._load(tx_rows, rx_rows)
        pairs = cmp.align_series(tx, rx, max_gap_s=0.005)
        self.assertEqual(pairs.window_start_ns, 100_000_000)
        self.assertEqual(pairs.window_end_ns, 199_000_000)
        self.assertEqual(len(pairs.t_ns), 10)      # 0.10 .. 0.19 s
        self.assertEqual(pairs.n_refused_boundary, 20)

    def test_gap_in_tx_refuses_those_pairs(self):
        # 50 ms TX hole in the middle; bounded interpolation must refuse it.
        tx_rows = [tx_row(t_ns=i * 1_000_000, voltage=1.0) for i in range(100)]
        tx_rows += [tx_row(t_ns=150_000_000 + i * 1_000_000, voltage=1.0)
                    for i in range(100)]
        rx_rows = [rx_row(t_ns=i * 10_000_000, voltage=0.5) for i in range(25)]
        tx, rx = self._load(tx_rows, rx_rows)
        pairs = cmp.align_series(tx, rx, max_gap_s=0.005)
        self.assertGreater(pairs.n_refused_gap, 0)
        self.assertLess(len(pairs.t_ns), 25)

    def test_lag_shifts_the_effective_tx_window(self):
        tx_rows = [tx_row(t_ns=i * 1_000_000, voltage=i / 1000.0)
                   for i in range(1000)]
        rx_rows = [rx_row(t_ns=i * 10_000_000, voltage=1.0) for i in range(100)]
        tx, rx = self._load(tx_rows, rx_rows)
        pairs = cmp.align_series(tx, rx, max_gap_s=0.005, lag_s=0.020)
        self.assertEqual(pairs.lag_s, 0.020)
        # TX is sampled at (t_rx - lag): the first usable RX time is 0.020 s.
        self.assertEqual(pairs.t_ns[0], 20_000_000)
        self.assertAlmostEqual(pairs.tx_values[0], 0.0, places=6)


# ─────────────────────────────────────────── 4. lag, correlation, shape error

class TestBestLagAndShapeError(TempDirTest):

    def _series_from_fn(self, kind, rate_hz, duration_s, fn, t0_s=0.0):
        n = int(duration_s * rate_hz)
        samples = []
        for i in range(n):
            t = t0_s + i / rate_hz
            samples.append(cmp.Sample(int(round(t * 1e9)), fn(t)))
        return cmp.Series(kind=kind, channel="ir", samples=tuple(samples),
                          quality=cmp.SeriesQuality())

    def test_injected_delay_is_recovered(self):
        f = 2.0
        delay = 0.020
        tx = self._series_from_fn(
            "tx", 1000.0, 1.0, lambda t: math.sin(2 * math.pi * f * t))
        rx = self._series_from_fn(
            "rx", 100.0, 1.0,
            lambda t: 0.2 + 0.5 * math.sin(2 * math.pi * f * (t - delay)))
        res = cmp.best_lag(tx, rx, max_gap_s=0.005, search_s=0.050,
                           step_s=0.0005)
        self.assertIsNotNone(res.lag_s)
        self.assertAlmostEqual(res.lag_s, delay, delta=0.0006)
        self.assertGreater(res.correlation, 0.999)
        self.assertFalse(res.at_search_limit)

    def test_zero_delay_gives_zero_lag(self):
        f = 2.0
        tx = self._series_from_fn(
            "tx", 1000.0, 1.0, lambda t: math.sin(2 * math.pi * f * t))
        rx = self._series_from_fn(
            "rx", 100.0, 1.0, lambda t: math.sin(2 * math.pi * f * t))
        res = cmp.best_lag(tx, rx, max_gap_s=0.005, search_s=0.050,
                           step_s=0.0005)
        self.assertAlmostEqual(res.lag_s, 0.0, delta=0.0006)

    def test_lag_beyond_search_range_is_flagged_at_limit(self):
        f = 1.0
        tx = self._series_from_fn(
            "tx", 1000.0, 2.0, lambda t: math.sin(2 * math.pi * f * t))
        rx = self._series_from_fn(
            "rx", 100.0, 2.0,
            lambda t: math.sin(2 * math.pi * f * (t - 0.100)))
        res = cmp.best_lag(tx, rx, max_gap_s=0.005, search_s=0.020,
                           step_s=0.0005)
        self.assertTrue(res.at_search_limit)

    def test_constant_series_yields_no_correlation_not_a_crash(self):
        tx = self._series_from_fn("tx", 1000.0, 0.5, lambda t: 1.0)
        rx = self._series_from_fn("rx", 100.0, 0.5, lambda t: 0.5)
        res = cmp.best_lag(tx, rx, max_gap_s=0.005, search_s=0.010,
                           step_s=0.0005)
        self.assertIsNone(res.correlation)
        self.assertIsNone(res.lag_s)

    def test_gain_and_offset_recovered_exactly(self):
        tx_v = [0.0, 1.0, 2.0, 3.0, 4.0]
        rx_v = [0.5 + 2.0 * v for v in tx_v]
        sh = cmp.shape_error(tx_v, rx_v)
        self.assertAlmostEqual(sh.gain, 2.0, places=9)
        self.assertAlmostEqual(sh.offset_v, 0.5, places=9)
        self.assertAlmostEqual(sh.nrms_error, 0.0, places=9)

    def test_residual_raises_normalized_rms_error(self):
        tx_v = [math.sin(i / 10.0) for i in range(200)]
        rx_v = [0.5 * v + (0.05 if i % 2 else -0.05)
                for i, v in enumerate(tx_v)]
        sh = cmp.shape_error(tx_v, rx_v)
        self.assertGreater(sh.nrms_error, 0.0)
        self.assertLess(sh.nrms_error, 1.0)
        self.assertGreater(sh.rms_residual_v, 0.0)

    def test_shape_error_undefined_for_flat_signals(self):
        sh = cmp.shape_error([1.0] * 10, [2.0] * 10)
        self.assertIsNone(sh.gain)
        self.assertIsNone(sh.nrms_error)

    def test_shape_error_needs_at_least_two_points(self):
        sh = cmp.shape_error([1.0], [2.0])
        self.assertIsNone(sh.gain)

    def test_shape_error_rejects_length_mismatch(self):
        with self.assertRaises(ValueError):
            cmp.shape_error([1.0, 2.0], [1.0])


# ──────────────────────────────────────────── 5. per-channel signal metrics

class TestSignalAndTimingStats(unittest.TestCase):

    def test_dc_ac_and_pi(self):
        vals = [1.0 + 0.1 * math.sin(2 * math.pi * i / 100.0)
                for i in range(100)]
        st = cmp.signal_stats(vals)
        self.assertAlmostEqual(st.dc_mean, 1.0, places=6)
        self.assertAlmostEqual(st.ac_pkpk, 0.2, delta=0.002)
        self.assertAlmostEqual(st.ac_amplitude, 0.1, delta=0.001)
        self.assertAlmostEqual(st.ac_rms, 0.1 / math.sqrt(2.0), delta=0.002)
        # PI is the strict clinical relation AC/DC*100 on the one-sided AC.
        self.assertAlmostEqual(st.pi_pct, 10.0, delta=0.1)

    def test_pi_undefined_for_non_positive_dc(self):
        st = cmp.signal_stats([-1.0, 0.0, 1.0])
        self.assertIsNone(st.pi_pct)

    def test_signal_stats_on_empty_values(self):
        st = cmp.signal_stats([])
        self.assertEqual(st.n, 0)
        self.assertIsNone(st.dc_mean)
        self.assertIsNone(st.pi_pct)

    def test_timing_stats_on_exact_grid(self):
        times = [i * 1_000_000 for i in range(1000)]
        ts = cmp.timing_stats(times, expected_rate_hz=1000.0)
        self.assertAlmostEqual(ts.mean_interval_s, 0.001, places=9)
        self.assertAlmostEqual(ts.jitter_stdev_s, 0.0, places=12)
        self.assertAlmostEqual(ts.mean_rate_hz, 1000.0, places=6)
        self.assertAlmostEqual(ts.expected_interval_s, 0.001, places=9)

    def test_timing_stats_reports_jitter_and_extremes(self):
        times = [0, 1_000_000, 2_500_000, 3_500_000]
        ts = cmp.timing_stats(times)
        self.assertAlmostEqual(ts.min_interval_s, 0.001, places=9)
        self.assertAlmostEqual(ts.max_interval_s, 0.0015, places=9)
        self.assertGreater(ts.jitter_stdev_s, 0.0)

    def test_timing_stats_needs_two_samples(self):
        ts = cmp.timing_stats([5])
        self.assertEqual(ts.n_intervals, 0)
        self.assertIsNone(ts.mean_interval_s)
        self.assertIsNone(ts.jitter_stdev_s)


class TestPeaks(unittest.TestCase):

    def _sine(self, rate_hz, duration_s, freq_hz, t0=0.0, shift=0.0):
        n = int(rate_hz * duration_s)
        times, vals = [], []
        for i in range(n):
            t = t0 + i / rate_hz
            times.append(int(round(t * 1e9)))
            vals.append(1.0 + 0.2 * math.sin(2 * math.pi * freq_hz
                                             * (t - shift)))
        return times, vals

    def test_finds_one_peak_per_cycle(self):
        times, vals = self._sine(100.0, 4.0, 1.25)     # 5 cycles
        idx = cmp.find_peaks(times, vals, min_interval_s=0.4)
        self.assertEqual(len(idx), 5)

    def test_min_interval_suppresses_close_maxima(self):
        times, vals = self._sine(100.0, 4.0, 1.25)
        idx = cmp.find_peaks(times, vals, min_interval_s=1.5)
        self.assertLessEqual(len(idx), 3)

    def test_no_peaks_in_flat_signal(self):
        times = [i * 10_000_000 for i in range(100)]
        self.assertEqual(cmp.find_peaks(times, [1.0] * 100, 0.2), ())

    def test_peak_timing_error_recovers_injected_delay(self):
        tx_t, tx_v = self._sine(1000.0, 4.0, 1.25)
        rx_t, rx_v = self._sine(100.0, 4.0, 1.25, shift=0.020)
        pk = cmp.peak_timing(tx_t, tx_v, rx_t, rx_v,
                             min_interval_s=0.4, max_match_s=0.100)
        self.assertEqual(pk.n_matched, 5)
        self.assertAlmostEqual(pk.mean_error_s, 0.020, delta=0.006)
        self.assertLess(pk.max_abs_error_s, 0.030)
        self.assertAlmostEqual(pk.mean_interval_rx_s, 0.8, delta=0.02)
        self.assertIsNotNone(pk.interval_jitter_rx_s)

    def test_unmatched_peaks_are_counted(self):
        tx_t, tx_v = self._sine(1000.0, 4.0, 1.25)
        rx_t, rx_v = self._sine(100.0, 2.0, 1.25)      # half the record
        pk = cmp.peak_timing(tx_t, tx_v, rx_t, rx_v,
                             min_interval_s=0.4, max_match_s=0.100)
        self.assertGreater(pk.n_unmatched_tx, 0)

    def test_peak_timing_with_no_peaks(self):
        times = [i * 10_000_000 for i in range(50)]
        pk = cmp.peak_timing(times, [1.0] * 50, times, [1.0] * 50,
                             min_interval_s=0.2, max_match_s=0.1)
        self.assertEqual(pk.n_matched, 0)
        self.assertIsNone(pk.mean_error_s)


class TestSpectrum(unittest.TestCase):

    def test_dc_only_signal_peaks_at_zero(self):
        times = [i * 10_000_000 for i in range(256)]
        sp = cmp.spectrum(times, [1.0] * 256, grid_hz=100.0)
        self.assertEqual(sp.dominant_hz, 0.0)

    def test_five_hz_tone_is_found(self):
        times, vals = [], []
        for i in range(512):
            t = i / 100.0
            times.append(int(round(t * 1e9)))
            vals.append(math.sin(2 * math.pi * 5.0 * t))
        sp = cmp.spectrum(times, vals, grid_hz=100.0)
        self.assertAlmostEqual(sp.dominant_hz, 5.0, delta=0.5)

    def test_reported_band_never_exceeds_nyquist(self):
        times, vals = [], []
        for i in range(256):
            t = i / 100.0
            times.append(int(round(t * 1e9)))
            vals.append(math.sin(2 * math.pi * 5.0 * t))
        sp = cmp.spectrum(times, vals, grid_hz=100.0)
        self.assertEqual(sp.nyquist_hz, 50.0)
        self.assertLessEqual(max(sp.freqs), 50.0)

    def test_spectrum_of_short_series_is_empty_not_an_error(self):
        sp = cmp.spectrum([0, 10_000_000], [1.0, 1.0], grid_hz=100.0)
        self.assertIsNone(sp.dominant_hz)


# ────────────────────────────────────── 6. channel comparison + SpO2 gating

class TestChannelComparison(TempDirTest):

    def _compare(self, channel="ir", **kw):
        tx_rows, rx_rows = synth_pair(channel, **kw)
        ptx = os.path.join(self.tmp, f"tx_{channel}.csv")
        prx = os.path.join(self.tmp, f"rx_{channel}.csv")
        write_csv(ptx, TX_FIELDS, tx_rows)
        write_csv(prx, RX_FIELDS, rx_rows)
        tx = cmp.load_tx_series(ptx)
        rx = cmp.load_rx_series(prx)
        return cmp.compare_channel(tx, rx, cmp.ComparisonConfig())

    def test_clean_channel_is_usable_and_fully_reported(self):
        res = self._compare(duration_s=4.0)
        self.assertEqual(res.channel, "ir")
        self.assertTrue(res.usable, res.gate_reasons)
        self.assertEqual(res.gate_reasons, ())
        self.assertAlmostEqual(res.lag.lag_s, 0.020, delta=0.002)
        self.assertAlmostEqual(res.shape.gain, 0.500, delta=0.02)
        self.assertAlmostEqual(res.shape.offset_v, 0.150, delta=0.02)
        self.assertLess(res.shape.nrms_error, 0.05)
        self.assertAlmostEqual(res.rx_stats.dc_mean, 0.150 + 0.5 * 1.200,
                               delta=0.01)
        self.assertIsNotNone(res.rx_stats.pi_pct)
        self.assertGreater(res.n_pairs, 300)
        self.assertGreater(res.overlap_s, 3.0)

    def test_measured_pi_matches_ac_over_dc(self):
        res = self._compare(duration_s=4.0)
        st = res.rx_stats
        self.assertAlmostEqual(st.pi_pct, st.ac_amplitude / st.dc_mean * 100.0,
                               places=6)

    def test_tx_and_rx_timing_are_reported_separately(self):
        res = self._compare(duration_s=2.0)
        self.assertAlmostEqual(res.tx_timing.mean_interval_s, 0.001, places=6)
        self.assertAlmostEqual(res.rx_timing.mean_interval_s, 0.010, places=6)

    def test_clipping_blocks_usability(self):
        res = self._compare(duration_s=2.0, flag_last={"clipped": True})
        self.assertFalse(res.usable)
        self.assertTrue(any("clip" in r for r in res.gate_reasons),
                        res.gate_reasons)

    def test_saturation_blocks_usability(self):
        res = self._compare(duration_s=2.0, flag_last={"saturated": True})
        self.assertFalse(res.usable)
        self.assertTrue(any("satur" in r for r in res.gate_reasons),
                        res.gate_reasons)

    def test_staleness_blocks_usability(self):
        res = self._compare(duration_s=2.0, flag_last={"stale": True})
        self.assertFalse(res.usable)
        self.assertTrue(any("stale" in r for r in res.gate_reasons),
                        res.gate_reasons)

    def test_insufficient_data_blocks_usability(self):
        res = self._compare(duration_s=0.2)      # 20 RX samples
        self.assertFalse(res.usable)
        self.assertTrue(any("insufficient" in r for r in res.gate_reasons),
                        res.gate_reasons)

    def test_all_reads_failed_blocks_usability(self):
        ptx = os.path.join(self.tmp, "tx_ir.csv")
        prx = os.path.join(self.tmp, "rx_ir.csv")
        tx_rows, _ = synth_pair("ir", duration_s=2.0)
        write_csv(ptx, TX_FIELDS, tx_rows)
        write_csv(prx, RX_FIELDS, [
            rx_row(t_ns=i * 10_000_000, voltage=None, success=False,
                   valid=False, error_type="i2c_ioerror") for i in range(200)])
        res = cmp.compare_channel(cmp.load_tx_series(ptx),
                                  cmp.load_rx_series(prx),
                                  cmp.ComparisonConfig())
        self.assertFalse(res.usable)
        self.assertEqual(res.rx_stats.n, 0)
        self.assertIsNone(res.rx_stats.pi_pct)

    def test_dropped_records_block_usability(self):
        ptx = os.path.join(self.tmp, "tx_ir.csv")
        prx = os.path.join(self.tmp, "rx_ir.csv")
        tx_rows, rx_rows = synth_pair("ir", duration_s=4.0)
        rx_rows[-1] = rx_row(channel="ir", t_ns=int(3.99 * 1e9), voltage=1.0,
                             dropped=12)
        write_csv(ptx, TX_FIELDS, tx_rows)
        write_csv(prx, RX_FIELDS, rx_rows)
        res = cmp.compare_channel(cmp.load_tx_series(ptx),
                                  cmp.load_rx_series(prx),
                                  cmp.ComparisonConfig())
        self.assertFalse(res.usable)
        self.assertTrue(any("drop" in r for r in res.gate_reasons),
                        res.gate_reasons)

    def test_tx_rate_vs_rx_nyquist_is_measured_not_assumed(self):
        res = self._compare(duration_s=2.0)
        self.assertTrue(res.tx_rate_above_rx_nyquist)
        self.assertAlmostEqual(res.rx_spectrum.nyquist_hz, 50.0, places=6)
        self.assertNotEqual(res.aliasing_note, "")

    def test_no_overlap_is_handled(self):
        ptx = os.path.join(self.tmp, "tx_ir.csv")
        prx = os.path.join(self.tmp, "rx_ir.csv")
        write_csv(ptx, TX_FIELDS,
                  [tx_row(t_ns=i * 1_000_000, voltage=1.0) for i in range(100)])
        write_csv(prx, RX_FIELDS,
                  [rx_row(t_ns=1_000_000_000 + i * 10_000_000, voltage=1.0)
                   for i in range(100)])
        res = cmp.compare_channel(cmp.load_tx_series(ptx),
                                  cmp.load_rx_series(prx),
                                  cmp.ComparisonConfig())
        self.assertFalse(res.usable)
        self.assertEqual(res.n_pairs, 0)
        self.assertIsNone(res.overlap_s)
        self.assertTrue(any("overlap" in r for r in res.gate_reasons),
                        res.gate_reasons)


class TestSessionComparisonAndSpo2Gating(TempDirTest):

    def _session(self, ir_kw=None, red_kw=None, duration_s=4.0):
        ir_kw = dict(ir_kw or {})
        red_kw = dict(red_kw or {})
        tx_ir, rx_ir = synth_pair("ir", duration_s=duration_s, dc=1.200,
                                  ac=0.060, gain=0.500, rx_dc_offset=0.150,
                                  **ir_kw)
        # Red AC deliberately smaller so R != 1.
        red_defaults = dict(dc=1.200, ac=0.030, gain=0.500,
                            rx_dc_offset=0.150)
        red_defaults.update(red_kw)
        tx_red, rx_red = synth_pair("red", duration_s=duration_s,
                                    **red_defaults)
        d = make_session(self.tmp, "sess", tx_ir, tx_red, rx_ir, rx_red)
        return cmp.load_session(d)

    def test_channels_are_reported_independently(self):
        res = cmp.compare_session(self._session(), cmp.ComparisonConfig())
        self.assertEqual(res.ir.channel, "ir")
        self.assertEqual(res.red.channel, "red")
        self.assertTrue(res.ir.usable, res.ir.gate_reasons)
        self.assertTrue(res.red.usable, res.red.gate_reasons)
        self.assertIsNotNone(res.ir.rx_stats.pi_pct)
        self.assertIsNotNone(res.red.rx_stats.pi_pct)

    def test_r_ratio_from_measured_ac_dc(self):
        res = cmp.compare_session(self._session(), cmp.ComparisonConfig())
        expected = ((res.red.rx_stats.ac_amplitude / res.red.rx_stats.dc_mean)
                    / (res.ir.rx_stats.ac_amplitude / res.ir.rx_stats.dc_mean))
        self.assertAlmostEqual(res.r_ratio, expected, places=6)
        self.assertAlmostEqual(res.r_ratio, 0.5, delta=0.05)

    def test_spo2_uses_the_configured_calibration(self):
        cfg = cmp.ComparisonConfig(spo2_a=110.0, spo2_b=25.0)
        res = cmp.compare_session(self._session(), cfg)
        self.assertIsNotNone(res.spo2_measured_pct)
        self.assertAlmostEqual(res.spo2_measured_pct,
                               110.0 - 25.0 * res.r_ratio, places=6)
        self.assertEqual(res.calibration_a, 110.0)
        self.assertEqual(res.calibration_b, 25.0)

    def test_other_coefficients_give_a_different_spo2(self):
        base = cmp.compare_session(self._session(), cmp.ComparisonConfig())
        alt = cmp.compare_session(
            self._session(), cmp.ComparisonConfig(spo2_a=104.0, spo2_b=17.0))
        self.assertNotAlmostEqual(base.spo2_measured_pct,
                                  alt.spo2_measured_pct, places=3)
        self.assertAlmostEqual(alt.spo2_measured_pct,
                               104.0 - 17.0 * alt.r_ratio, places=6)

    def test_spo2_refused_when_ir_is_clipped(self):
        sess = self._session(ir_kw={"flag_last": {"clipped": True}})
        res = cmp.compare_session(sess, cmp.ComparisonConfig())
        self.assertIsNone(res.spo2_measured_pct)
        self.assertTrue(any("ir" in r for r in res.spo2_gate_reasons),
                        res.spo2_gate_reasons)
        # The Red channel is still reported on its own.
        self.assertTrue(res.red.usable, res.red.gate_reasons)
        self.assertIsNotNone(res.red.rx_stats.pi_pct)

    def test_spo2_refused_when_red_is_saturated(self):
        sess = self._session(red_kw={"flag_last": {"saturated": True}})
        res = cmp.compare_session(sess, cmp.ComparisonConfig())
        self.assertIsNone(res.spo2_measured_pct)
        self.assertTrue(any("red" in r for r in res.spo2_gate_reasons))

    def test_spo2_refused_when_a_channel_is_stale(self):
        sess = self._session(ir_kw={"flag_last": {"stale": True}})
        res = cmp.compare_session(sess, cmp.ComparisonConfig())
        self.assertIsNone(res.spo2_measured_pct)

    def test_spo2_refused_on_insufficient_data(self):
        res = cmp.compare_session(self._session(duration_s=0.3),
                                  cmp.ComparisonConfig())
        self.assertIsNone(res.spo2_measured_pct)
        self.assertTrue(any("insufficient" in r
                            for r in res.spo2_gate_reasons),
                        res.spo2_gate_reasons)

    def test_r_ratio_and_spo2_refused_when_a_channel_has_no_data(self):
        tx_ir, rx_ir = synth_pair("ir", duration_s=4.0)
        tx_red, _ = synth_pair("red", duration_s=4.0)
        d = make_session(self.tmp, "sess2", tx_ir, tx_red, rx_ir, ())
        res = cmp.compare_session(cmp.load_session(d), cmp.ComparisonConfig())
        self.assertIsNone(res.r_ratio)
        self.assertIsNone(res.spo2_measured_pct)
        self.assertTrue(res.spo2_gate_reasons)

    def test_logger_counters_are_carried_into_the_summary(self):
        md = build_session_metadata("dry-run")
        md["final_counters"] = {"rx_ir": {"dropped_queue_full": 3,
                                          "enqueued": 10, "written": 10}}
        tx_ir, rx_ir = synth_pair("ir", duration_s=1.0)
        tx_red, rx_red = synth_pair("red", duration_s=1.0)
        d = make_session(self.tmp, "sess3", tx_ir, tx_red, rx_ir, rx_red,
                         metadata=md)
        res = cmp.compare_session(cmp.load_session(d), cmp.ComparisonConfig())
        summary = res.summary_dict()
        self.assertEqual(
            summary["logger_counters"]["rx_ir"]["dropped_queue_full"], 3)

    def test_summary_dict_is_json_serializable_and_labelled(self):
        res = cmp.compare_session(self._session(), cmp.ComparisonConfig())
        text = json.dumps(res.summary_dict())
        self.assertIn("DESIGN CALCULATED", text.upper())
        parsed = json.loads(text)
        self.assertIn("ir", parsed["channels"])
        self.assertIn("red", parsed["channels"])
        self.assertIn("dc_mean", parsed["channels"]["ir"]["rx_stats"])


# ─────────────────────────────────────────────────────── 7. output artefacts

class TestOutputs(TempDirTest):

    def _session_dir(self):
        tx_ir, rx_ir = synth_pair("ir", duration_s=2.0)
        tx_red, rx_red = synth_pair("red", duration_s=2.0, ac=0.030)
        return make_session(self.tmp, "sess", tx_ir, tx_red, rx_ir, rx_red)

    def test_writes_summary_timeseries_and_report(self):
        sess_dir = self._session_dir()
        res = cmp.compare_session(cmp.load_session(sess_dir),
                                  cmp.ComparisonConfig())
        out = os.path.join(self.tmp, "analysis")
        written = cmp.write_comparison_outputs(res, out)
        for key in ("comparison_summary.json", "comparison_timeseries.csv",
                    "comparison_report.txt"):
            self.assertTrue(os.path.isfile(os.path.join(out, key)), key)
            self.assertIn(key, written)
        with open(os.path.join(out, "comparison_summary.json")) as f:
            summary = json.load(f)
        self.assertIn("channels", summary)

    def test_timeseries_has_paired_rows_only(self):
        sess_dir = self._session_dir()
        res = cmp.compare_session(cmp.load_session(sess_dir),
                                  cmp.ComparisonConfig())
        out = os.path.join(self.tmp, "analysis")
        cmp.write_comparison_outputs(res, out)
        with open(os.path.join(out, "comparison_timeseries.csv")) as f:
            rows = list(csv.DictReader(f))
        self.assertGreater(len(rows), 100)
        self.assertIn("t_s", rows[0])
        self.assertIn("tx_ir_v_interp", rows[0])
        self.assertIn("rx_ir_v", rows[0])
        self.assertIn("residual_ir_v", rows[0])

    def test_analysis_never_modifies_the_raw_files(self):
        sess_dir = self._session_dir()
        before = {}
        for name in ("tx_ir.csv", "tx_red.csv", "rx_ir.csv", "rx_red.csv",
                     "session_metadata.json"):
            with open(os.path.join(sess_dir, name), "rb") as f:
                before[name] = f.read()
        res = cmp.compare_session(cmp.load_session(sess_dir),
                                  cmp.ComparisonConfig())
        cmp.write_comparison_outputs(res, os.path.join(self.tmp, "analysis"))
        for name, blob in before.items():
            with open(os.path.join(sess_dir, name), "rb") as f:
                self.assertEqual(f.read(), blob, name)

    def test_report_text_states_the_no_validation_caveat(self):
        sess_dir = self._session_dir()
        res = cmp.compare_session(cmp.load_session(sess_dir),
                                  cmp.ComparisonConfig())
        out = os.path.join(self.tmp, "analysis")
        cmp.write_comparison_outputs(res, out)
        with open(os.path.join(out, "comparison_report.txt")) as f:
            text = f.read()
        self.assertIn("HARDWARE NOT VERIFIED", text.upper())
        self.assertIn("not", text.lower())
        self.assertIn("clinical", text.lower())

    def test_plots_degrade_to_a_labelled_skip_without_matplotlib(self):
        sess_dir = self._session_dir()
        res = cmp.compare_session(cmp.load_session(sess_dir),
                                  cmp.ComparisonConfig())
        out = os.path.join(self.tmp, "analysis")
        result = cmp.make_plots(res, out, _force_unavailable=True)
        self.assertEqual(result["plots"], [])
        self.assertIn("matplotlib", result["skipped_reason"])

    def test_make_plots_is_reported_by_write_outputs(self):
        sess_dir = self._session_dir()
        res = cmp.compare_session(cmp.load_session(sess_dir),
                                  cmp.ComparisonConfig())
        out = os.path.join(self.tmp, "analysis")
        written = cmp.write_comparison_outputs(res, out)
        self.assertIn("plots", written)


if __name__ == "__main__":
    unittest.main()
