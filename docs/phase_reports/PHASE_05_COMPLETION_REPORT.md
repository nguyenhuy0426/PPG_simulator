# Phase 5 Completion Report — OPT101 Dual-Channel Acquisition via Grove Base Hat ADC

Date: 2026-07-12
Executor: Claude Code (senior embedded engineer persona)
Scope executed: `docs/claude_phases/05_PHASE_OPT101_AND_GROVE_ADC_ACQUISITION.md` — and only Phase 5.
New RX module: `hw/opt101_rx.py`

---

## 1. Execution environment (honest constraints)

- Development machine is **x86_64 Linux** (`huynn-lap`, Ubuntu, kernel 6.17), **not** the Raspberry Pi 4. No project hardware is attached and the Pi is not reachable from this session (no SSH route).
- `grove.py` is **not installed** on this machine (searched `~/.local/lib/python3*`, `/usr/lib/python3/dist-packages`, `/usr/local/lib`, project `.venv`). The mandated grove.adc source audit was therefore performed on the **official Seeed `grove.py` 0.6 package downloaded from PyPI** (`python3 -m pip download grove.py --no-deps` → `grove.py-0.6.tar.gz`), which is real published code, version-pinned — not memory, not invention.
- **Inspecting the actually-installed grove.adc on the Pi is BLOCKED from this machine.** Before first hardware run, execute on the Pi: `python3 -c "import grove.adc, inspect; print(inspect.getsourcefile(grove.adc))"` and diff against the audit in §3. If the installed version differs in class/method names or the sys.exit behavior, §3 and the RX error handling must be re-checked.
- Consequence: **all hardware validation items are NOT RUN / BLOCKED** (consistent with Phases 2–4). No measurement, timing, or successful-hardware claim is made anywhere in this report.

## 2. Channel mapping — user facts override stale docs

**[VERIFIED-USER 2026-07-12, authoritative]:**

| Grove ADC port | Channel # | Function |
|---|---|---|
| A0 | 0 | OPT101 **IR** photodiode |
| A2 | 2 | OPT101 **Red** photodiode |
| A1 | 1 | **NOT used** for OPT101 |

**Discrepancy flagged and corrected:** the Phase 5 spec, `00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md`, `00_README_FROM_PHASE_4.md`, and the Phase-4-era `config.py` comment all said *A1 = Red, A2 obsolete*. The user's Phase 5 instructions state **A2 = Red, A1 unused** — user-verified hardware facts take precedence. Corrected in this phase: `config.py` (comment + new constants) and `00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md` (three occurrences, with a supersession note). `00_README_FROM_PHASE_4.md` and the Phase 5 spec were left untouched as historical records per the precedence rule already written into the source-of-truth file. The new constants are test-locked (`ADC_CHANNEL_IR == 0`, `ADC_CHANNEL_RED == 2`, A1 rejected with `ValueError`).

## 3. grove.adc API audit (grove.py 0.6, PyPI — `grove/adc.py`, `grove/i2c.py`)

All items below are **[VERIFIED-CODE — grove.py 0.6 source]**:

- **Class:** `ADC(object)`; **constructor** `ADC(address=0x04)` — default matches the user-verified 0x04.
- **Bus:** `grove.i2c.Bus` — a **singleton `smbus2.SMBus`** (class attribute `instance`); selects bus 1 on Pi 2+ via `RPi.GPIO.RPI_REVISION`. Imports `smbus2` and `RPi.GPIO` at module import time → the import must stay inside `begin()` so dry-run never touches it.
- **Register map (from source comments + code):** `0x10+ch` = raw ADC data, `0x20+ch` = input voltage (mV), `0x30+ch` = input/output ratio (%), `0x00` = PID (0x0004 RPi hat / 0x0005 Zero hat), `0x03` = version.
- **Read methods:** `read_raw(channel)` → `read_register(0x10+ch)`; `read_voltage(channel)` → mV; `read(channel)` → ratio. All return `int` (16-bit SMBus word; raw is a 12-bit conversion, expected 0..4095).
- **Transaction pattern:** `read_register(n)` = `bus.write_byte(addr, n)` **then** `bus.read_word_data(addr, n)` — two separate kernel-serialized transactions. `read_word_data` re-addresses register `n` itself (SMBus write-then-read with repeated start), so a DAC write interleaved between the two transactions **cannot** corrupt the ADC read.
- **⚠ CRITICAL error behavior:** `read_register()` catches `IOError` (`OSError` in Python 3, which is what smbus2 raises on NACK/bus faults), prints a hint, and calls **`sys.exit(2)`**. A transient I2C error inside the library therefore raises `SystemExit` — a `BaseException` that a bare `except Exception` does **not** catch. Every `read_raw` call in `hw/opt101_rx.py` (probe and loop) explicitly catches `SystemExit` and converts it to a per-channel error so a bus fault can never terminate the RX thread or the process. This containment is unit-tested.
- **Not used, deliberately:** `read_voltage()` (would double per-sample bus traffic), `read()`, `name`/`version` properties. Phase 5 uses exactly one grove.adc data method: `read_raw(channel)` — enforced by an AST-level test.

## 4. Exact files changed

| File | Change |
|------|--------|
| `config.py` | Grove ADC section rewritten to the verified mapping and extended: `GROVE_ADC_ADDR = 0x04`, `ADC_CHANNEL_IR = 0`, `ADC_CHANNEL_RED = 2` (A1 explicitly documented as not used; `GROVE_ADC_CHANNEL` re-flagged legacy-only). New RX section: `RX_SAMPLE_RATE_HZ = 100`, `RX_BUFFER_SIZE = 1024`, `RX_STALE_THRESHOLD_S = 0.5`, `RX_DISCONNECT_ERROR_THRESHOLD = 10`, with the Phase 4 timing-budget rationale in the comment. `ADC_VOLTAGE_REF` comment now warns it is not the DAC 3.2 V. No existing constant's value changed. |
| `hw/opt101_rx.py` | **New** — `OPT101Receiver` (process singleton via `get_instance()`, house pattern): dedicated daemon thread `"OPT101Rx"` as sole Grove-ADC reader at 100 Hz/channel (perf_counter-paced with fall-behind resync); per-channel `deque(maxlen=1024)` of immutable `RXSample(timestamp, raw, saturated)` (`time.monotonic()` timestamps); per-channel status (`init/ok/saturated/invalid/error/disconnected/dry-run`) and counters (error, invalid, saturation, consecutive-error); validation discards non-int/out-of-range codes; `SystemExit` containment per §3; disconnect declared after 10 consecutive errors, auto-recovery on next good read; rate-limited logging (1st + every 100th, DACManager pattern); consumer API `get_latest / get_samples / sample_count / channel_status / is_stale / error_count / invalid_count / saturation_count`; labeled `raw_to_millivolts()` estimator (see §6); dry-run = labeled simulation producing **zero** samples. Contains **no DAC writes and no TX imports** (AST-test-enforced). |
| `main.py` | Minimal lifecycle wiring: `rx = OPT101Receiver.get_instance(); rx.begin() and rx.start()` after `engine.begin()` (RX failure logs and degrades to TX-only — never blocks the app), `rx.shutdown()` before `engine.shutdown()` in `finally:`. |
| `tests/test_phase5_rx.py` | **New** — 32 hardware-free stdlib-unittest tests (see §7). |
| `docs/claude_phases/00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md` | A1→A2 mapping correction in three places with `[VERIFIED-USER 2026-07-12]` tags and a supersession note (see §2). |

Not touched (deliberately): `hw/dac_manager.py`, `calibration.py`, `core/signal_engine.py`, `models/ppg_model.py`, `config_store.py`, `hw/adc_reader.py` (deprecated legacy — superseded, not modified), all Phase 2–4 tests, UI frames (RX display is Phase 7), TX mappings 0x60/0x61, `DAC_FULLSCALE_V = 3.2`.

## 5. RX design under the one-Pi / one-HAT shared bus

- **Thread ownership:** the `"OPT101Rx"` daemon thread is the **only** code that touches the Grove ADC. It never calls `DACManager`, never imports Blinka, and holds no lock shared with the TX path. SignalGen keeps sole TX ownership through the Phase 4 write lock. Consumers read RX buffers under the receiver's internal lock via snapshot-returning methods.
- **Rate decoupling [ENGINEERING-INFERENCE from Phase 4 budget, unmeasured]:** at a 100 kHz bus each register read ≈ 0.45 ms and each `read_raw` is two transactions, so per-1 kHz-tick RX cannot fit alongside the two DAC writes (≈ 0.56 ms/tick). RX runs at **100 Hz per channel** (both channels per tick): PPG bandwidth is 0.5–10 Hz, so this is 10× Nyquist while adding ~4 transactions (≈ 1.3–1.8 ms bus time) per 10 ms window. Worst-case TX jitter from a DAC write queuing behind one ADC transaction is ≈ 0.5 ms at 100 kHz [INFERENCE]. The actual bus clock on the target Pi remains **UNKNOWN**; if it is 400 kHz all margins improve ~4×.
- **Transaction safety:** kernel i2c-core serializes individual transactions per adapter; grove.adc's `read_word_data` re-addresses its register within its own transaction (§3), so TX/RX interleaving cannot corrupt either side. No multi-transaction atomicity is needed by this design.
- **Failure semantics (no fabricated values, ever):** a failed/invalid/unavailable read appends **nothing**; `get_latest` returns the last real sample or `None`; one channel failing (e.g., cable out of A0) does not block or contaminate the other; a hat-level failure at `begin()` degrades the app to TX-only with a logged error. Dry-run is a clearly labeled simulation (`is_simulated`, status `"dry-run"`) with empty buffers — the acquisition thread is not even started.
- **Staleness hook:** `is_stale(channel, now=None, threshold_s=0.5)` — `True` when no sample exists or the newest is older than the threshold; `now` is injectable for deterministic tests and Phase 6/7 polling.

## 6. Raw vs voltage — what is and is not verified

- The **authoritative stored value is the raw 12-bit code** (0..4095) from register `0x10+ch`.
- `raw_to_millivolts(raw)` derives mV assuming the documented 3.3 V Grove ADC reference (`ADC_VOLTAGE_REF`). This is a **derived estimate, not a measured value** — the function docstring says so explicitly. The STM32's own mV register (`0x20+ch`) is the authoritative converted value but is deliberately not read per-sample (bus budget). **Hardware cross-check (NOT RUN):** on the Pi, compare `read_raw(ch)*3300/4095` against `read_voltage(ch)` for both channels.
- `raw == 4095` is stored but flagged `saturated` (real data, clipping warning); `raw == 0` is a valid dark level, not an error; codes outside 0..4095 or non-int values are discarded as `invalid` (a >4095 word from a 12-bit converter indicates a protocol/firmware fault, not light).

## 7. New tests (tests/test_phase5_rx.py — 32 tests, all hardware-free)

- **Mapping:** `ADC_CHANNEL_IR == 0`, `ADC_CHANNEL_RED == 2`, `GROVE_ADC_ADDR == 0x04`; acquisition reads exactly A0-then-A2 each tick and **never** A1; A1/unknown channels raise `ValueError`; channels land in separate buffers.
- **Samples/buffers:** `RXSample` carries float monotonic timestamp, raw, saturation flag; timestamps non-decreasing; `deque(maxlen)` bounds hold (oldest evicted, newest kept); snapshots are immutable tuples unaffected by later acquisition; `n`-limited retrieval returns the most recent n.
- **Validation/saturation:** −1, 4096, 65535, `None`, 3.5, `"x"`, `True` all discarded and counted with status `invalid` while the other channel keeps acquiring; 4095 stored + flagged + status `saturated` with recovery to `ok`; 0 accepted as dark level; `raw_to_millivolts(4095) == 3300.0 ≠ DAC_FULLSCALE_MV`.
- **Errors/disconnects:** `OSError` → counted, no sample, status `error`; **grove's `SystemExit(2)` contained** in both the loop and the `begin()` probe (probe failure → `begin()` False, `start()` refused); status `disconnected` exactly at the 10th consecutive error; one good read resets the consecutive counter; a failing IR channel does not block Red (15 Red samples while IR has 0); no fabricated values (never-read channel → `None`; after failures `get_latest` still returns the last real sample, count unchanged).
- **Staleness:** no-sample ⇒ stale; boundary behavior at exactly `RX_STALE_THRESHOLD_S`; injectable `now` and `threshold_s`.
- **Dry-run:** labeled (`is_simulated`), `begin()` ok, `start()` refused, statuses `"dry-run"`, zero samples, `get_latest` None, stale True, shutdown clears readiness; hardware mode is not labeled simulated.
- **Threading:** live thread at 2 kHz acquires while the main thread concurrently reads (no exception, ordered timestamps, ≥20 samples); exactly one daemon thread named `"OPT101Rx"`, `start()` idempotent; `stop()` joins and clears; stop-without-start safe; `get_instance()` singleton.
- **Static guards (AST, not substring):** RX module imports none of `busio/board/adafruit_mcp4725/dac_manager/DAC_ADDR_*`; uses no `set_values`/`raw_value` attribute (the only DAC write entry points); uses `read_raw` and not `read_voltage`.

## 8. Commands actually run and real results

| Command | Result |
|---------|--------|
| `python3 -m unittest tests.test_calibration tests.test_phase3_acdc tests.test_phase4_dac` (baseline, before changes) | **PASS — Ran 82 tests, OK** |
| `python3 -m pip download grove.py --no-deps` + source read of `grove/adc.py`, `grove/i2c.py` (0.6) | Done — findings in §3 |
| `python3 -m unittest tests.test_phase5_rx` (new suite alone) | **PASS — Ran 32 tests, OK** |
| `python3 -m unittest tests.test_calibration tests.test_phase3_acdc tests.test_phase4_dac tests.test_phase5_rx` (full) | **PASS — Ran 114 tests, OK** (82 preserved + 32 new) |
| Dry-run RX lifecycle smoke (`PPG_DRY_RUN=1`: get_instance → begin → start refused → labeled statuses → shutdown) | **PASS** — logs show labeled DRY-RUN messages, no samples, clean shutdown |
| `python3 -m py_compile config.py main.py hw/opt101_rx.py tests/test_phase5_rx.py` | **PASS** |
| On-Pi grove.adc inspection, `i2cdetect`, any I2C/OPT101/oscilloscope measurement | **NOT RUN / BLOCKED** — no Pi, no HAT, no OPT101 on this machine |

Phase-5-attributable diff (the repo also carries uncommitted Phase 2–4 work): `config.py` +≈25 lines (two sections), `main.py` +9 lines, `hw/opt101_rx.py` new (≈330 lines), `tests/test_phase5_rx.py` new (≈420 lines), source-of-truth doc 3 mapping corrections.

## 9. Hardware validation plan — ALL ITEMS NOT RUN / BLOCKED

To be executed on the actual Pi 4 + Grove Base Hat + OPT101s before trusting RX data:

1. **Installed grove.adc diff** (§1) — confirm class/methods/`sys.exit` behavior match the 0.6 audit.
2. `i2cdetect -y 1` → expect 0x04, 0x60, 0x61.
3. Actual I2C bus clock (`/boot/firmware/config.txt` `dtparam=i2c_arm_baudrate`, default 100 kHz) — resolves the §5 timing inferences.
4. Dark-level and LED-on raw codes per channel; verify IR responds on A0 and Red on A2 (cover one OPT101 at a time to confirm the mapping physically).
5. Saturation headroom: raise DAC drive and confirm the `saturated` flag before clipping corrupts the AC waveform.
6. `read_raw` vs `read_voltage` cross-check (§6).
7. Disconnect tests: unplug one Grove cable (expect per-channel `disconnected`, other channel unaffected), unplug the hat mid-run (expect both channels `disconnected`, app alive, TX unaffected).
8. TX jitter with RX running (scope on DAC output) vs Phase 4 baseline.
9. **Electrical compatibility [UNKNOWN — must verify]:** the OPT101 supply rail and transimpedance gain wiring on this build are not documented in the repo. If the OPT101 is powered from 5 V, its output can exceed the STM32 ADC's 3.3 V input range — verify the supply is 3.3 V or that the output is divided/limited before A0/A2. I am not sure based on the currently available evidence.

## 10. Optical crosstalk (analysis only — no results invented)

Both OPT101s share the optical cavity with both LEDs, and the TX design drives IR and Red **simultaneously** (continuous-wave, not time-division multiplexed). Therefore each photodiode sees a mixture: A0 = IR signal + Red leakage, A2 = Red signal + IR leakage. The OPT101 has no optical filter; channel separation currently depends only on geometry/optical isolation of the physical build, which is **UNKNOWN** from the repo. Consequences: measured per-channel AC/DC (Phase 6) may be mixed, biasing R and SpO2. Mitigations to evaluate in Phase 6+ (decision deferred, not implemented here): physical baffling, or TDM LED drive with synchronized sampling — the latter would change the TX architecture and is explicitly out of Phase 5 scope. No crosstalk magnitude is claimed; it must be measured (validation item: drive one LED at a time and record both channels).

## 11. Acceptance checklist (Phase 5 spec)

- [x] Dual-channel receiver abstraction — IR A0 + Red A2, raw code, timestamp, per-channel status
- [x] Verified grove.adc API only — `ADC(address=0x04)`, `read_raw(channel)`; nothing invented (audit §3; on-Pi confirmation BLOCKED, §1)
- [x] Dedicated RX owner thread; no long blocking work on the UI thread (RX begin probe is one register read at startup)
- [x] Timestamps (monotonic) + bounded buffers (1024/channel)
- [x] ADC errors, saturation, disconnects, invalid samples handled; `SystemExit` containment for grove's `sys.exit(2)`
- [x] Stale-data detection hook (`is_stale`)
- [x] Dry-run explicitly labeled; **no fabricated values anywhere** (unit-tested)
- [x] **No DAC writes in RX code** (AST-guard-tested); TX mappings 0x60/0x61 untouched
- [x] No measured SpO2 / AC-DC / R computation (Phase 6)
- [x] All 82 existing tests preserved; suite now 114/114 OK
- [x] Shared-bus ownership and scheduling documented (§5); crosstalk and electrical unknowns stated honestly (§9–10)

## 12. DO-NOT-REDO handoff for Phase 6

1. **Do not re-implement acquisition.** Consume `OPT101Receiver.get_instance()` — `get_samples(config.ADC_CHANNEL_IR / ADC_CHANNEL_RED)` returns timestamped raw codes; check `channel_status`/`is_stale` before computing anything, and compute nothing when a channel is not `ok`/`saturated`-with-care (never on fabricated data — there is none).
2. **Do not change the mapping constants** `ADC_CHANNEL_IR=0` / `ADC_CHANNEL_RED=2` (test-locked, user-verified) or reuse `GROVE_ADC_CHANNEL` (legacy potentiometer only).
3. **Do not add a second Grove-ADC reader** — the RX thread is the single owner; add consumers, not readers. Raising `RX_SAMPLE_RATE_HZ` above ~200 Hz requires the bus-clock verification of §9.3 first.
4. Measured AC/DC → PI → R → SpO2 on RX buffers is Phase 6's job; UI display of RX waveforms/status is Phase 7's. Crosstalk mitigation (§10) needs a measurement-driven decision, not code-first.
5. Legacy dead code (`hw/adc_reader.py`, `ppg_model.ppg_sample_to_dac_value`, `ac_value_to_dac_12bit`) remains inert and flagged — still not Phase 6's job.

---

**Phase 5 complete. Stopping here — Phase 6 not started, per instructions.**
