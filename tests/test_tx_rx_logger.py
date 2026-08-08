"""
Stage 3 tests — non-blocking TX/RX session logger (core/tx_rx_logger.py).

Task-mandated properties under test:
  - no file I/O in the log_tx()/log_rx() call path (the 1 kHz DAC loop and the
    ADC read path only enqueue into bounded queues; a dedicated batch writer
    thread owns all file writes),
  - bounded queues with explicit overflow accounting (dropped records are
    counted, never silently lost),
  - A1 is never a valid Grove channel,
  - missing RX data stays missing: a failed read carries no fabricated code or
    voltage, and its CSV cells are empty, never zero,
  - monotonic-clock timestamps pass through verbatim; wall clock appears only
    in session metadata,
  - raw files tx_ir.csv / tx_red.csv / rx_ir.csv / rx_red.csv plus
    session_metadata.json; an existing session directory is never reused,
  - shutdown/close flushes every enqueued record, including via the context
    manager on an exception.

Run: python3 -m unittest tests.test_tx_rx_logger
"""

import csv
import dataclasses
import json
import os
import tempfile
import unittest

import config
from core.tx_rx_logger import (
    RX_FIELDS,
    TX_FIELDS,
    REQUIRED_METADATA_KEYS,
    RxRecord,
    TxRecord,
    TxRxSessionLogger,
    build_session_metadata,
)


def make_tx(channel="ir", sequence_id=0, dac_code=100, success=True, **over):
    """A valid TxRecord with every mandated field populated."""
    addr = config.DAC_ADDR_IR if channel == "ir" else config.DAC_ADDR_RED
    fields = dict(
        session_id="S1",
        sequence_id=sequence_id,
        t_mono_ns=1_000_000 + sequence_id,
        channel=channel,
        dac_address=addr,
        model_timestamp_s=0.01 * sequence_id,
        target_hr_bpm=75.0,
        target_rr_bpm=15.0,
        target_spo2_pct=98.0,
        target_pi_pct=2.0,
        target_r_ratio=0.55,
        requested_waveform_mv=820.0,
        requested_dac_voltage_v=0.82,
        dac_code=dac_code,
        ideal_dac_voltage_v_calculated=0.8008,
        write_start_mono_ns=2_000_000,
        write_end_mono_ns=2_400_000,
        write_duration_ns=400_000,
        success=success,
        error_type="" if success else "i2c_oserror",
    )
    fields.update(over)
    return TxRecord(**fields)


def make_rx(channel="ir", sequence_id=0, success=True, **over):
    """A valid RxRecord; a failed one carries no code and no voltage."""
    grove = "A0" if channel == "ir" else "A2"
    fields = dict(
        session_id="S1",
        sequence_id=sequence_id,
        t_mono_ns=5_000_000 + sequence_id,
        channel=channel,
        grove_channel=grove,
        adc_address=config.GROVE_ADC_ADDR,
        raw_code=2048 if success else None,
        converted_voltage_v=1.64 if success else None,
        read_start_mono_ns=6_000_000,
        read_end_mono_ns=6_450_000,
        read_duration_ns=450_000,
        valid=success,
        stale=False,
        saturated=False,
        clipped=False,
        success=success,
        error_type="" if success else "i2c_ioerror",
    )
    fields.update(over)
    return RxRecord(**fields)


class TestTxRecordValidation(unittest.TestCase):
    def test_valid_record_constructs(self):
        rec = make_tx()
        self.assertEqual(rec.channel, "ir")
        self.assertEqual(rec.dac_address, 0x60)

    def test_records_are_immutable(self):
        rec = make_tx()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            rec.dac_code = 0

    def test_unknown_channel_rejected(self):
        with self.assertRaises(ValueError):
            make_tx(channel="green", dac_address=0x60)

    def test_channel_address_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            make_tx(channel="ir", dac_address=config.DAC_ADDR_RED)
        with self.assertRaises(ValueError):
            make_tx(channel="red", dac_address=config.DAC_ADDR_IR)

    def test_dac_code_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            make_tx(dac_code=-1)
        with self.assertRaises(ValueError):
            make_tx(dac_code=4096)

    def test_failure_requires_error_type(self):
        with self.assertRaises(ValueError):
            make_tx(success=False, error_type="")

    def test_success_forbids_error_type(self):
        with self.assertRaises(ValueError):
            make_tx(success=True, error_type="i2c_oserror")


class TestRxRecordValidation(unittest.TestCase):
    def test_valid_ir_and_red_records_construct(self):
        self.assertEqual(make_rx("ir").grove_channel, "A0")
        self.assertEqual(make_rx("red").grove_channel, "A2")

    def test_a1_is_never_valid(self):
        with self.assertRaises(ValueError):
            make_rx("ir", grove_channel="A1")
        with self.assertRaises(ValueError):
            make_rx("red", grove_channel="A1")

    def test_channel_grove_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            make_rx("ir", grove_channel="A2")
        with self.assertRaises(ValueError):
            make_rx("red", grove_channel="A0")

    def test_wrong_adc_address_rejected(self):
        with self.assertRaises(ValueError):
            make_rx(adc_address=0x04)

    def test_raw_code_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            make_rx(raw_code=4096)
        with self.assertRaises(ValueError):
            make_rx(raw_code=-1)

    def test_successful_read_requires_data(self):
        with self.assertRaises(ValueError):
            make_rx(success=True, raw_code=None)
        with self.assertRaises(ValueError):
            make_rx(success=True, converted_voltage_v=None)

    def test_failed_read_must_not_carry_fabricated_data(self):
        # "Missing data must remain missing" — a failed read with a number in
        # it would be a fabricated measurement.
        with self.assertRaises(ValueError):
            make_rx(success=False, raw_code=0, converted_voltage_v=None)
        with self.assertRaises(ValueError):
            make_rx(success=False, raw_code=None, converted_voltage_v=0.0)

    def test_failed_read_requires_error_type_and_invalid_flag(self):
        with self.assertRaises(ValueError):
            make_rx(success=False, error_type="")
        with self.assertRaises(ValueError):
            make_rx(success=False, valid=True)


class TestSessionMetadata(unittest.TestCase):
    def test_build_contains_every_required_key(self):
        md = build_session_metadata(mode="dry-run")
        for key in REQUIRED_METADATA_KEYS:
            self.assertIn(key, md)

    def test_environment_facts_come_from_config(self):
        md = build_session_metadata(mode="dry-run")
        self.assertEqual(md["dac_address_ir"], config.DAC_ADDR_IR)
        self.assertEqual(md["dac_address_red"], config.DAC_ADDR_RED)
        self.assertEqual(md["adc_address"], config.GROVE_ADC_ADDR)
        self.assertEqual(md["dac_fullscale_v"], config.DAC_FULLSCALE_V)
        self.assertEqual(md["adc_reference_v"], config.ADC_VOLTAGE_REF)
        self.assertEqual(md["tx_sample_rate_hz"], config.FS_TIMER_HZ)
        self.assertEqual(md["rx_sample_rate_hz"], config.RX_SAMPLE_RATE_HZ)
        self.assertEqual(md["expected_r_sense_ir_ohm"], 82.0)
        self.assertEqual(md["expected_r_sense_red_ohm"], 100.0)

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            build_session_metadata(mode="bogus")

    def test_operator_values_default_to_none_never_invented(self):
        md = build_session_metadata(mode="dry-run")
        self.assertIsNone(md["led_opt101_distance_mm_operator"])
        self.assertIsNone(md["measured_rail_5v0_v_operator"])
        self.assertIsNone(md["measured_rail_3v28_v_operator"])

    def test_operator_values_pass_through(self):
        md = build_session_metadata(
            mode="hardware-capture",
            led_opt101_distance_mm=12.5,
            measured_rail_5v0_v=5.03,
            measured_rail_3v28_v=3.279,
            rbe_config="100k",
            input_cap_config="10nF",
            notes="bench session",
        )
        self.assertEqual(md["led_opt101_distance_mm_operator"], 12.5)
        self.assertEqual(md["measured_rail_5v0_v_operator"], 5.03)
        self.assertEqual(md["measured_rail_3v28_v_operator"], 3.279)
        self.assertEqual(md["rbe_config"], "100k")
        self.assertEqual(md["input_cap_config"], "10nF")


class LoggerTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = self._tmp.name
        self.metadata = build_session_metadata(mode="dry-run")
        self.addCleanup(self._tmp.cleanup)

    def open_logger(self, session_id="S1", **kw):
        return TxRxSessionLogger(self.base_dir, session_id, self.metadata, **kw)

    def read_rows(self, session_id, name):
        path = os.path.join(self.base_dir, session_id, name)
        with open(path, newline="") as f:
            return list(csv.DictReader(f))

    def read_raw_lines(self, session_id, name):
        path = os.path.join(self.base_dir, session_id, name)
        with open(path) as f:
            return f.read().splitlines()


class TestLoggerFilesAndHeaders(LoggerTestBase):
    def test_creates_four_raw_files_and_metadata(self):
        logger = self.open_logger()
        logger.close()
        session = os.path.join(self.base_dir, "S1")
        for name in ("tx_ir.csv", "tx_red.csv", "rx_ir.csv", "rx_red.csv",
                     "session_metadata.json"):
            self.assertTrue(os.path.exists(os.path.join(session, name)), name)

    def test_csv_headers_match_the_documented_schema(self):
        logger = self.open_logger()
        logger.close()
        for name in ("tx_ir.csv", "tx_red.csv"):
            self.assertEqual(self.read_raw_lines("S1", name)[0],
                             ",".join(TX_FIELDS))
        for name in ("rx_ir.csv", "rx_red.csv"):
            self.assertEqual(self.read_raw_lines("S1", name)[0],
                             ",".join(RX_FIELDS))

    def test_existing_session_directory_is_never_reused(self):
        # Raw files must never be modified after the fact; a second logger on
        # the same session id must refuse, not append or truncate.
        self.open_logger().close()
        with self.assertRaises(FileExistsError):
            self.open_logger()

    def test_metadata_missing_required_key_rejected(self):
        bad = dict(self.metadata)
        del bad["git_revision"]
        with self.assertRaises(ValueError):
            TxRxSessionLogger(self.base_dir, "S2", bad)

    def test_metadata_json_written_with_session_id_and_wall_clock(self):
        logger = self.open_logger()
        logger.close()
        with open(os.path.join(self.base_dir, "S1", "session_metadata.json")) as f:
            md = json.load(f)
        self.assertEqual(md["session_id"], "S1")
        self.assertIn("created_utc", md)   # wall clock lives ONLY here
        self.assertIn("final_counters", md)


class TestNoFileIOInLogPath(LoggerTestBase):
    def test_log_calls_only_enqueue(self):
        # With the writer thread deliberately not started, log_tx/log_rx must
        # leave the raw files untouched (header only): the log path performs
        # no file I/O of its own.
        logger = self.open_logger(autostart=False)
        for i in range(50):
            self.assertTrue(logger.log_tx(make_tx("ir", sequence_id=i)))
            self.assertTrue(logger.log_rx(make_rx("red", sequence_id=i)))
        self.assertEqual(len(self.read_raw_lines("S1", "tx_ir.csv")), 1)
        self.assertEqual(len(self.read_raw_lines("S1", "rx_red.csv")), 1)
        logger.start()
        logger.close()
        self.assertEqual(len(self.read_rows("S1", "tx_ir.csv")), 50)
        self.assertEqual(len(self.read_rows("S1", "rx_red.csv")), 50)


class TestQueueOverflowAccounting(LoggerTestBase):
    def test_overflow_drops_new_records_and_counts_them(self):
        logger = self.open_logger(autostart=False, queue_size=8)
        results = [logger.log_tx(make_tx("ir", sequence_id=i))
                   for i in range(20)]
        self.assertEqual(sum(results), 8)
        self.assertEqual(logger.counters()["tx_ir"]["dropped_queue_full"], 12)
        self.assertEqual(logger.counters()["tx_ir"]["enqueued"], 8)
        logger.start()
        logger.close()
        rows = self.read_rows("S1", "tx_ir.csv")
        self.assertEqual(len(rows), 8)
        # The drop counter is snapshotted into each row at enqueue time.
        self.assertEqual(rows[0]["dropped_total_at_enqueue"], "0")

    def test_final_counters_land_in_metadata(self):
        logger = self.open_logger(autostart=False, queue_size=4)
        for i in range(10):
            logger.log_tx(make_tx("ir", sequence_id=i))
        logger.start()
        logger.close()
        with open(os.path.join(self.base_dir, "S1", "session_metadata.json")) as f:
            md = json.load(f)
        self.assertEqual(md["final_counters"]["tx_ir"]["dropped_queue_full"], 6)
        self.assertEqual(md["final_counters"]["tx_ir"]["written"], 4)


class TestMalformedRecords(LoggerTestBase):
    def test_non_record_objects_rejected_and_counted(self):
        logger = self.open_logger(autostart=False)
        self.assertFalse(logger.log_tx("garbage"))
        self.assertFalse(logger.log_tx(None))
        self.assertFalse(logger.log_rx(42))
        self.assertEqual(logger.counters()["tx_ir"]["rejected_malformed"]
                         + logger.counters()["tx_red"]["rejected_malformed"], 2)
        self.assertEqual(logger.counters()["rx_ir"]["rejected_malformed"]
                         + logger.counters()["rx_red"]["rejected_malformed"], 1)
        logger.close()

    def test_wrong_record_type_for_stream_rejected(self):
        logger = self.open_logger(autostart=False)
        self.assertFalse(logger.log_tx(make_rx("ir")))
        self.assertFalse(logger.log_rx(make_tx("ir")))
        logger.close()


class TestShutdownAndFlush(LoggerTestBase):
    def test_close_flushes_every_enqueued_record(self):
        logger = self.open_logger()
        for i in range(200):
            logger.log_tx(make_tx("ir", sequence_id=i))
            logger.log_tx(make_tx("red", sequence_id=i))
            logger.log_rx(make_rx("ir", sequence_id=i))
            logger.log_rx(make_rx("red", sequence_id=i))
        logger.close()
        for name in ("tx_ir.csv", "tx_red.csv", "rx_ir.csv", "rx_red.csv"):
            self.assertEqual(len(self.read_rows("S1", name)), 200, name)

    def test_close_is_idempotent(self):
        logger = self.open_logger()
        logger.log_tx(make_tx("ir"))
        logger.close()
        logger.close()
        self.assertEqual(len(self.read_rows("S1", "tx_ir.csv")), 1)

    def test_context_manager_flushes_on_exception(self):
        with self.assertRaises(RuntimeError):
            with self.open_logger() as logger:
                for i in range(5):
                    logger.log_tx(make_tx("ir", sequence_id=i))
                raise RuntimeError("simulated capture failure")
        self.assertEqual(len(self.read_rows("S1", "tx_ir.csv")), 5)

    def test_log_after_close_is_rejected_and_counted(self):
        logger = self.open_logger()
        logger.close()
        self.assertFalse(logger.log_tx(make_tx("ir")))
        self.assertEqual(logger.counters()["tx_ir"]["rejected_after_close"], 1)


class TestCsvContent(LoggerTestBase):
    def test_failed_rx_read_stays_missing_in_csv(self):
        logger = self.open_logger()
        logger.log_rx(make_rx("ir", success=False))
        logger.close()
        row = self.read_rows("S1", "rx_ir.csv")[0]
        self.assertEqual(row["raw_code"], "")
        self.assertEqual(row["converted_voltage_v"], "")
        self.assertEqual(row["success"], "0")
        self.assertEqual(row["valid"], "0")
        self.assertEqual(row["error_type"], "i2c_ioerror")

    def test_monotonic_timestamps_pass_through_verbatim(self):
        logger = self.open_logger()
        logger.log_tx(make_tx("ir", t_mono_ns=123_456_789_012_345))
        logger.close()
        row = self.read_rows("S1", "tx_ir.csv")[0]
        self.assertEqual(row["t_mono_ns"], "123456789012345")

    def test_tx_row_carries_all_mandated_fields(self):
        logger = self.open_logger()
        logger.log_tx(make_tx("red", dac_code=1023))
        logger.close()
        row = self.read_rows("S1", "tx_red.csv")[0]
        self.assertEqual(row["session_id"], "S1")
        self.assertEqual(row["channel"], "red")
        self.assertEqual(row["dac_address"], "0x61")
        self.assertEqual(row["dac_code"], "1023")
        self.assertEqual(row["target_hr_bpm"], "75.0")
        self.assertEqual(row["write_duration_ns"], "400000")
        # The ideal DAC voltage column is named as a calculation, because it
        # was never measured.
        self.assertIn("ideal_dac_voltage_v_calculated", row)

    def test_rx_row_carries_all_mandated_fields(self):
        logger = self.open_logger()
        logger.log_rx(make_rx("red"))
        logger.close()
        row = self.read_rows("S1", "rx_red.csv")[0]
        self.assertEqual(row["grove_channel"], "A2")
        self.assertEqual(row["adc_address"], "0x08")
        self.assertEqual(row["raw_code"], "2048")
        self.assertEqual(row["stale"], "0")
        self.assertEqual(row["saturated"], "0")
        self.assertEqual(row["clipped"], "0")


if __name__ == "__main__":
    unittest.main()
