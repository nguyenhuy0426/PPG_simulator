"""
core/tx_rx_logger.py — Stage 3 non-blocking TX/RX session logger.

Design constraints (task-mandated):

  * NO file I/O in the log_tx()/log_rx() call path. The 1 kHz DAC timing loop
    and the ADC read critical path only validate a record and enqueue it into
    a bounded queue.  A single dedicated batch writer thread owns every file
    handle and performs all writes.
  * Bounded queues with explicit overflow accounting: when a queue is full the
    NEW record is dropped and counted per stream — never silently lost, never
    blocking the timing loop.
  * Monotonic timestamps (time.monotonic_ns() domain) in every record; the
    wall clock appears only once, as session metadata (created_utc).
  * A1 is never a valid Grove channel.  IR is A0, Red is A2 [VERIFIED-USER].
  * Missing RX data stays missing: a failed read must carry raw_code=None and
    converted_voltage_v=None (empty CSV cells), never zeros or TX-derived
    values.  Record validation enforces this at construction time.
  * Raw session files — tx_ir.csv, tx_red.csv, rx_ir.csv, rx_red.csv,
    session_metadata.json — live in <base_dir>/<session_id>/.  An existing
    session directory is refused (FileExistsError): raw files are never
    reused, appended to or modified after their session ends.

Producers must stop before close(): a log_* call racing close() may be
rejected (counted as rejected_after_close) — records are never silently lost,
but the writer makes no ordering guarantee against a concurrent shutdown.

Malformed objects that carry no identifiable channel are counted under the
"ir" stream of the intended direction (tx or rx); this is an accounting
convention, not a data statement.

This module performs NO hardware access and imports no I2C/GPIO libraries.
Nothing here is a measurement; the "ideal_dac_voltage_v_calculated" column is
named to state exactly that.
"""

import csv
import dataclasses
import datetime
import json
import logging
import os
import platform
import queue
import subprocess
import sys
import threading

import config
from led_driver.params import IR_CHANNEL_5V, RED_CHANNEL_5V

log = logging.getLogger("ppg_simulator")

VALID_CHANNELS = ("ir", "red")

# Fixed, task-mandated mappings.  A1 does not appear anywhere.
_CHANNEL_TO_DAC_ADDR = {"ir": config.DAC_ADDR_IR, "red": config.DAC_ADDR_RED}
_CHANNEL_TO_GROVE = {"ir": "A0", "red": "A2"}

TX_FIELDS = (
    "session_id", "sequence_id", "t_mono_ns", "channel", "dac_address",
    "model_timestamp_s", "target_hr_bpm", "target_rr_bpm", "target_spo2_pct",
    "target_pi_pct", "target_r_ratio", "requested_waveform_mv",
    "requested_dac_voltage_v", "dac_code", "ideal_dac_voltage_v_calculated",
    "write_start_mono_ns", "write_end_mono_ns", "write_duration_ns",
    "success", "error_type", "dropped_total_at_enqueue",
)

RX_FIELDS = (
    "session_id", "sequence_id", "t_mono_ns", "channel", "grove_channel",
    "adc_address", "raw_code", "converted_voltage_v", "read_start_mono_ns",
    "read_end_mono_ns", "read_duration_ns", "valid", "stale", "saturated",
    "clipped", "success", "error_type", "dropped_total_at_enqueue",
)

VALID_MODES = ("dry-run", "read-only-verify", "hardware-capture")

REQUIRED_METADATA_KEYS = (
    "software_version", "git_revision", "platform", "python_version", "mode",
    "i2c_bus", "dac_address_ir", "dac_address_red", "adc_address",
    "dac_fullscale_v", "adc_reference_v", "tx_sample_rate_hz",
    "rx_sample_rate_hz", "expected_r_sense_ir_ohm", "expected_r_sense_red_ohm",
    "rbe_config", "input_cap_config", "led_opt101_distance_mm_operator",
    "measured_rail_5v0_v_operator", "measured_rail_3v28_v_operator", "notes",
)


def _fmt(value) -> str:
    """CSV cell format: None -> empty (missing stays missing), bool -> 1/0."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _check_channel(channel: str) -> None:
    if channel not in VALID_CHANNELS:
        raise ValueError(f"channel must be one of {VALID_CHANNELS}, "
                         f"got {channel!r}")


def _check_error_labelling(success: bool, error_type: str) -> None:
    if success and error_type:
        raise ValueError("a successful record must not carry an error_type")
    if not success and not error_type:
        raise ValueError("a failed record must name its error_type")


@dataclasses.dataclass(frozen=True)
class TxRecord:
    """One MCP4725 write attempt.  All timestamps are monotonic ns."""

    session_id: str
    sequence_id: int
    t_mono_ns: int
    channel: str
    dac_address: int
    model_timestamp_s: float
    target_hr_bpm: float
    target_rr_bpm: float
    target_spo2_pct: float
    target_pi_pct: float
    target_r_ratio: float
    requested_waveform_mv: float
    requested_dac_voltage_v: float
    dac_code: int
    ideal_dac_voltage_v_calculated: float
    write_start_mono_ns: int
    write_end_mono_ns: int
    write_duration_ns: int
    success: bool
    error_type: str

    def __post_init__(self) -> None:
        _check_channel(self.channel)
        expected = _CHANNEL_TO_DAC_ADDR[self.channel]
        if self.dac_address != expected:
            raise ValueError(
                f"channel {self.channel!r} uses DAC address 0x{expected:02x},"
                f" got 0x{self.dac_address:02x}")
        if not 0 <= self.dac_code <= config.DAC_MAX_VALUE:
            raise ValueError(f"dac_code {self.dac_code} outside "
                             f"0..{config.DAC_MAX_VALUE}")
        _check_error_labelling(self.success, self.error_type)

    def row(self, dropped_total_at_enqueue: int) -> list:
        return [
            self.session_id, _fmt(self.sequence_id), _fmt(self.t_mono_ns),
            self.channel, f"0x{self.dac_address:02x}",
            _fmt(self.model_timestamp_s), _fmt(self.target_hr_bpm),
            _fmt(self.target_rr_bpm), _fmt(self.target_spo2_pct),
            _fmt(self.target_pi_pct), _fmt(self.target_r_ratio),
            _fmt(self.requested_waveform_mv),
            _fmt(self.requested_dac_voltage_v), _fmt(self.dac_code),
            _fmt(self.ideal_dac_voltage_v_calculated),
            _fmt(self.write_start_mono_ns), _fmt(self.write_end_mono_ns),
            _fmt(self.write_duration_ns), _fmt(self.success),
            self.error_type, _fmt(dropped_total_at_enqueue),
        ]


@dataclasses.dataclass(frozen=True)
class RxRecord:
    """One Grove ADC read attempt.  A failed read carries NO data values."""

    session_id: str
    sequence_id: int
    t_mono_ns: int
    channel: str
    grove_channel: str
    adc_address: int
    raw_code: int
    converted_voltage_v: float
    read_start_mono_ns: int
    read_end_mono_ns: int
    read_duration_ns: int
    valid: bool
    stale: bool
    saturated: bool
    clipped: bool
    success: bool
    error_type: str

    def __post_init__(self) -> None:
        _check_channel(self.channel)
        expected = _CHANNEL_TO_GROVE[self.channel]
        if self.grove_channel != expected:
            raise ValueError(
                f"channel {self.channel!r} is fixed to Grove {expected} "
                f"(A1 is never used), got {self.grove_channel!r}")
        if self.adc_address != config.GROVE_ADC_ADDR:
            raise ValueError(
                f"ADC address must be 0x{config.GROVE_ADC_ADDR:02x}, "
                f"got 0x{self.adc_address:02x}")
        if self.raw_code is not None and \
                not 0 <= self.raw_code <= config.ADC_MAX_VALUE:
            raise ValueError(f"raw_code {self.raw_code} outside "
                             f"0..{config.ADC_MAX_VALUE}")
        if self.success:
            if self.raw_code is None or self.converted_voltage_v is None:
                raise ValueError("a successful read must carry raw_code and "
                                 "converted_voltage_v")
        else:
            if self.raw_code is not None or self.converted_voltage_v is not None:
                raise ValueError(
                    "a failed read must not carry data values: missing data "
                    "must remain missing (no zeros, no substitutes)")
            if self.valid:
                raise ValueError("a failed read cannot be flagged valid")
        _check_error_labelling(self.success, self.error_type)

    def row(self, dropped_total_at_enqueue: int) -> list:
        return [
            self.session_id, _fmt(self.sequence_id), _fmt(self.t_mono_ns),
            self.channel, self.grove_channel,
            f"0x{self.adc_address:02x}", _fmt(self.raw_code),
            _fmt(self.converted_voltage_v), _fmt(self.read_start_mono_ns),
            _fmt(self.read_end_mono_ns), _fmt(self.read_duration_ns),
            _fmt(self.valid), _fmt(self.stale), _fmt(self.saturated),
            _fmt(self.clipped), _fmt(self.success), self.error_type,
            _fmt(dropped_total_at_enqueue),
        ]


def _git_revision() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def build_session_metadata(mode: str,
                           rbe_config: str = "DNP",
                           input_cap_config: str = "DNP",
                           led_opt101_distance_mm: float = None,
                           measured_rail_5v0_v: float = None,
                           measured_rail_3v28_v: float = None,
                           notes: str = "") -> dict:
    """Session metadata.  Operator-entered values default to None — a value
    the operator did not enter is recorded as absent, never invented."""
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    return {
        "software_version": config.FIRMWARE_VERSION,
        "git_revision": _git_revision(),
        "platform": platform.platform(),
        "python_version": sys.version,
        "mode": mode,
        "i2c_bus": config.I2C_BUS,
        "dac_address_ir": config.DAC_ADDR_IR,
        "dac_address_red": config.DAC_ADDR_RED,
        "adc_address": config.GROVE_ADC_ADDR,
        "dac_fullscale_v": config.DAC_FULLSCALE_V,
        "adc_reference_v": config.ADC_VOLTAGE_REF,
        "tx_sample_rate_hz": config.FS_TIMER_HZ,
        "rx_sample_rate_hz": config.RX_SAMPLE_RATE_HZ,
        "expected_r_sense_ir_ohm": IR_CHANNEL_5V.rsense_ohm,
        "expected_r_sense_red_ohm": RED_CHANNEL_5V.rsense_ohm,
        "rbe_config": rbe_config,
        "input_cap_config": input_cap_config,
        "led_opt101_distance_mm_operator": led_opt101_distance_mm,
        "measured_rail_5v0_v_operator": measured_rail_5v0_v,
        "measured_rail_3v28_v_operator": measured_rail_3v28_v,
        "notes": notes,
    }


class TxRxSessionLogger:
    """Bounded-queue session logger with one batch writer thread."""

    _STREAMS = ("tx_ir", "tx_red", "rx_ir", "rx_red")
    _COUNTER_KEYS = ("enqueued", "written", "dropped_queue_full",
                     "rejected_malformed", "rejected_after_close",
                     "io_errors")

    def __init__(self, base_dir: str, session_id: str, metadata: dict,
                 queue_size: int = 4096, autostart: bool = True,
                 flush_interval_s: float = 0.2):
        missing = [k for k in REQUIRED_METADATA_KEYS if k not in metadata]
        if missing:
            raise ValueError(f"session metadata missing keys: {missing}")

        self.session_id = session_id
        self._metadata = dict(metadata)
        self._flush_interval_s = flush_interval_s

        os.makedirs(base_dir, exist_ok=True)
        self.session_dir = os.path.join(base_dir, session_id)
        # Raw files are never reused or modified: an existing session
        # directory raises FileExistsError.
        os.mkdir(self.session_dir)

        self._files = {}
        self._writers = {}
        for stream in self._STREAMS:
            path = os.path.join(self.session_dir, f"{stream}.csv")
            f = open(path, "w", newline="")
            w = csv.writer(f)
            w.writerow(TX_FIELDS if stream.startswith("tx") else RX_FIELDS)
            f.flush()
            self._files[stream] = f
            self._writers[stream] = w

        self._queues = {s: queue.Queue(maxsize=queue_size)
                        for s in self._STREAMS}
        self._counters = {s: {k: 0 for k in self._COUNTER_KEYS}
                          for s in self._STREAMS}
        self._counter_lock = threading.Lock()
        self._data_event = threading.Event()
        self._stop_event = threading.Event()
        self._close_lock = threading.Lock()
        self._thread = None
        self._closed = False

        self._write_metadata()
        if autostart:
            self.start()

    # ---------------------------------------------------------------- log path
    # These two methods are the ONLY entry points for the 1 kHz DAC loop and
    # the ADC read path.  They perform no file I/O: validate, snapshot the
    # drop counter, put_nowait, done.

    def log_tx(self, record) -> bool:
        return self._enqueue(record, TxRecord, "tx")

    def log_rx(self, record) -> bool:
        return self._enqueue(record, RxRecord, "rx")

    def _enqueue(self, record, cls, direction: str) -> bool:
        channel = getattr(record, "channel", None)
        stream = (f"{direction}_{channel}" if channel in VALID_CHANNELS
                  else f"{direction}_ir")
        if self._closed:
            with self._counter_lock:
                self._counters[stream]["rejected_after_close"] += 1
            return False
        if not isinstance(record, cls):
            with self._counter_lock:
                self._counters[stream]["rejected_malformed"] += 1
            return False
        with self._counter_lock:
            dropped_snapshot = self._counters[stream]["dropped_queue_full"]
        try:
            self._queues[stream].put_nowait((record, dropped_snapshot))
        except queue.Full:
            with self._counter_lock:
                self._counters[stream]["dropped_queue_full"] += 1
            return False
        with self._counter_lock:
            self._counters[stream]["enqueued"] += 1
        self._data_event.set()
        return True

    # ------------------------------------------------------------ writer side

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("logger already closed")
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="tx-rx-log-writer", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._data_event.wait(self._flush_interval_s)
            self._data_event.clear()
            self._drain()
        self._drain()

    def _drain(self) -> None:
        for stream, q in self._queues.items():
            wrote = 0
            while True:
                try:
                    record, dropped_snapshot = q.get_nowait()
                except queue.Empty:
                    break
                try:
                    self._writers[stream].writerow(record.row(dropped_snapshot))
                    wrote += 1
                except OSError as exc:
                    with self._counter_lock:
                        self._counters[stream]["io_errors"] += 1
                    log.error("[TxRxSessionLogger] write failed on %s: %s",
                              stream, exc)
            if wrote:
                with self._counter_lock:
                    self._counters[stream]["written"] += wrote
                try:
                    self._files[stream].flush()
                except OSError as exc:
                    with self._counter_lock:
                        self._counters[stream]["io_errors"] += 1
                    log.error("[TxRxSessionLogger] flush failed on %s: %s",
                              stream, exc)

    # --------------------------------------------------------------- shutdown

    def close(self) -> None:
        """Flush every enqueued record, stop the writer, finalize metadata.
        Idempotent.  Producers must be stopped before calling."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self._stop_event.set()
        self._data_event.set()
        if self._thread is not None:
            self._thread.join()
        else:
            self._drain()
        for f in self._files.values():
            f.close()
        self._write_metadata(final_counters=self.counters())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # ------------------------------------------------------------------ state

    def counters(self) -> dict:
        with self._counter_lock:
            return {s: dict(c) for s, c in self._counters.items()}

    def _write_metadata(self, final_counters: dict = None) -> None:
        md = dict(self._metadata)
        md["session_id"] = self.session_id
        # The wall clock appears here and ONLY here; all record timestamps
        # are monotonic.
        md["created_utc"] = self._metadata.setdefault(
            "created_utc",
            datetime.datetime.now(datetime.timezone.utc).isoformat())
        if final_counters is not None:
            md["final_counters"] = final_counters
        path = os.path.join(self.session_dir, "session_metadata.json")
        with open(path, "w") as f:
            json.dump(md, f, indent=2)
