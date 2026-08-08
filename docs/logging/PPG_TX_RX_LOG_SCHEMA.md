# PPG TX/RX Session Log Schema

Authoritative source: `core/tx_rx_logger.py` (`TX_FIELDS`, `RX_FIELDS`,
`REQUIRED_METADATA_KEYS`). `tests/test_tx_rx_logger.py` pins the headers to
this schema. This document describes the format; the code is the contract.

## 1. Session directory layout

```
<base_dir>/<session_id>/
    tx_ir.csv               raw TX records, IR channel (MCP4725 0x60)
    tx_red.csv              raw TX records, Red channel (MCP4725 0x61)
    rx_ir.csv               raw RX records, IR channel (OPT101 → Grove A0)
    rx_red.csv              raw RX records, Red channel (OPT101 → Grove A2)
    session_metadata.json   session metadata + final counters
```

Rules:

- An existing `<session_id>` directory is **refused** (`FileExistsError`).
  Raw CSVs are written once, by one session, and never modified afterwards.
  Derived/comparison outputs (Stage 4) go elsewhere and never touch these.
- **A1 is never used.** Record validation rejects any Grove channel other
  than A0 (IR) / A2 (Red).
- Producers (the 1 kHz DAC loop, the ADC read path) call only
  `log_tx()`/`log_rx()`, which enqueue into bounded queues — **no file I/O
  happens on those paths**. One batch writer thread owns all file handles.

## 2. Clock convention

Every per-record timestamp is `time.monotonic_ns()` (int ns, monotonic,
unaffected by NTP/wall-clock steps). Timestamps from different boots or
different machines are not comparable. The wall clock appears exactly once,
as `created_utc` in `session_metadata.json` — metadata, never analysis input.

## 3. TX record (`tx_ir.csv`, `tx_red.csv`)

One row per MCP4725 write **attempt** (success or failure).

| Column | Type | Meaning |
|---|---|---|
| session_id | str | session identifier |
| sequence_id | int | per-channel monotonically increasing counter, from 0 |
| t_mono_ns | int | record timestamp, monotonic ns |
| channel | str | `ir` or `red` |
| dac_address | hex str | `0x60` (ir) / `0x61` (red) — validated, mismatch impossible |
| model_timestamp_s | float | PPG model time of this sample, s |
| target_hr_bpm | float | model target heart rate |
| target_rr_bpm | float | model target respiratory rate |
| target_spo2_pct | float | model target SpO2 |
| target_pi_pct | float | model target perfusion index |
| target_r_ratio | float | model target R ratio |
| requested_waveform_mv | float | model waveform output, mV |
| requested_dac_voltage_v | float | voltage the software asked for, V |
| dac_code | int | 0–4095 code actually written |
| ideal_dac_voltage_v_calculated | float | `code × 3.28 / 4096` — a **calculation**, not a measurement; the column name states this deliberately |
| write_start_mono_ns | int | monotonic ns just before the I2C write |
| write_end_mono_ns | int | monotonic ns just after the I2C write |
| write_duration_ns | int | end − start |
| success | 1/0 | whether the I2C write succeeded |
| error_type | str | empty on success; mandatory short label on failure (e.g. `i2c_oserror`, `timeout`) |
| dropped_total_at_enqueue | int | this stream's queue-full drop count at the moment this record was enqueued |

Validation (raises `ValueError` at construction): unknown channel;
channel/address mismatch; code outside 0–4095; success with an error label;
failure without one.

## 4. RX record (`rx_ir.csv`, `rx_red.csv`)

One row per Grove ADC read **attempt**.

| Column | Type | Meaning |
|---|---|---|
| session_id, sequence_id, t_mono_ns, channel | | as in TX |
| grove_channel | str | `A0` (ir) / `A2` (red); **A1 rejected always** |
| adc_address | hex str | `0x08` (Grove HAT MM32) — validated |
| raw_code | int or **empty** | 12-bit ADC code; **empty cell when the read failed** |
| converted_voltage_v | float or **empty** | `raw_code × 3.28 / 4095`; empty when failed |
| read_start_mono_ns / read_end_mono_ns / read_duration_ns | int | I2C read timing, monotonic ns |
| valid | 1/0 | data usable (always 0 on failure) |
| stale | 1/0 | value older than the staleness threshold |
| saturated | 1/0 | at/near ADC full scale |
| clipped | 1/0 | at/near the OPT101 output ceiling (≈ 2.13 V calculated) |
| success | 1/0 | I2C read outcome |
| error_type | str | empty on success; mandatory label on failure |
| dropped_total_at_enqueue | int | as in TX |

**Missing data stays missing.** A failed read must carry `raw_code=None` and
`converted_voltage_v=None` — validation rejects a failed record holding any
number (a zero would be a fabricated measurement). The CSV cells are empty,
never `0`. No RX cell is ever filled from TX data.

## 5. `session_metadata.json`

All `REQUIRED_METADATA_KEYS` (checked at logger construction) plus
`session_id`, `created_utc` (the only wall-clock value), and, after close,
`final_counters`:

| Key | Source |
|---|---|
| software_version | `config.FIRMWARE_VERSION` |
| git_revision | `git rev-parse HEAD` (or `"unknown"`) |
| platform, python_version | `platform.platform()`, `sys.version` |
| mode | `dry-run` / `read-only-verify` / `hardware-capture` |
| i2c_bus, dac_address_ir, dac_address_red, adc_address | `config` (1, 0x60, 0x61, 0x08) |
| dac_fullscale_v, adc_reference_v | 3.28 / 3.28 (independent TX/RX quantities) |
| tx_sample_rate_hz, rx_sample_rate_hz | 1000 / 100 |
| expected_r_sense_ir_ohm, expected_r_sense_red_ohm | 82.0 / 100.0 (design values, `led_driver.params`) |
| rbe_config, input_cap_config | operator-entered build state (e.g. `DNP`, `100k`, `10nF`) |
| led_opt101_distance_mm_operator | operator-entered; **`null` when not entered — never invented** |
| measured_rail_5v0_v_operator, measured_rail_3v28_v_operator | operator DMM readings; `null` when not entered |
| notes | free text |

## 6. Counters (`logger.counters()`, and `final_counters` after close)

Per stream (`tx_ir`, `tx_red`, `rx_ir`, `rx_red`):

- `enqueued` — accepted into the queue
- `written` — rows actually written to the CSV
- `dropped_queue_full` — records dropped because the bounded queue was full
  (the new record is dropped and counted; the loop is never blocked)
- `rejected_malformed` — objects that were not a valid record of the right
  type (unknown-channel objects are counted under the `_ir` stream of their
  direction, by convention)
- `rejected_after_close` — log calls after `close()`
- `io_errors` — writer-thread write/flush failures (logged, counted, never
  silently swallowed)

After a clean close, `enqueued == written` per stream; any difference is an
`io_errors` event and is visible in the counters.

## 7. What these files do NOT claim

Rows record what the software requested and what the ADC returned. Nothing
here is an optical, electrical or clinical measurement claim; the calculated
DAC voltage column is explicitly labelled a calculation. Analysis of these
files (Stage 4) reports signal comparisons, not validation.
