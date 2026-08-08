# Phase 4 Completion Report — Dual-DAC TX & LED-Driver Integration

Date: 2026-07-12
Executor: Claude Code (senior embedded engineer persona)
Scope executed: `docs/claude_phases/04_PHASE_DUAL_DAC_AND_LED_DRIVER_INTEGRATION.md` — and only Phase 4.
Companion analysis: `docs/architecture/PHASE_4_DUAL_DAC_TX_AND_LED_DRIVER.md`

---

## 1. Execution environment (honest constraints)

- Development machine is **x86_64 Linux** (`uname -m` → `x86_64`), **not** the Raspberry Pi 4. No project hardware is attached.
- The active project `.venv` contains only `customtkinter`, `darkdetect`, `packaging`, `pip` — no Blinka/adafruit stack, no numpy, no pytest. The real `adafruit_mcp4725` 1.4.21 source was read from `~/.local/lib/python3.12/site-packages/` for API verification only.
- Consequence: **all hardware validation items are NOT RUN / BLOCKED** on this machine (consistent with Phases 2–3). No measurement, timing, or successful-hardware claim is made anywhere in this phase.

## 2. Exact files changed

| File | Change |
|------|--------|
| `config.py` | Added `DAC_IDLE_VALUE = 0` (safe idle/shutdown code, with rationale comment). Fixed the stale Grove-ADC comment ("potentiometer on A0") to the verified RX mapping: OPT101 IR → A0, OPT101 Red → A1, A2 obsolete; noted `GROVE_ADC_CHANNEL` is legacy-only. No functional constant altered; `DAC_ADDR_IR=0x60`, `DAC_ADDR_RED=0x61`, `DAC_FULLSCALE_V=3.2`, `ADC_VOLTAGE_REF=3.3` all unchanged. |
| `hw/dac_manager.py` | (1) All DAC writes serialized by a `threading.Lock` — the adafruit driver shares one **class-level** payload buffer across both DAC instances and its source says *"not thread-safe or re-entrant by design!"*, while two project threads (SignalGen, Tk main via CalibrationFrame) can reach the write path. (2) Per-channel exception isolation: an IR write failure no longer skips the Red write. (3) Per-channel error counters with rate-limited logging (1st failure then every 1000th — previously an unplugged DAC would log ~1000 lines/s at the 1 kHz cadence). (4) New `shutdown()`: parks both channels at `DAC_IDLE_VALUE` (0 V) and disables further writes. (5) `begin()` now parks outputs at 0 V instead of mid-scale. (6) Input values coerced to `int` before clamping (the driver bit-shifts the value). (7) Removed the dead `ppg_sample_to_dac_value()` static method — zero callers, and it carried its own duplicate `*4095` normalization contrary to the centralized-conversion rule. (8) Docstring documents the fixed 0x60=IR / 0x61=Red mapping and thread-ownership rules. |
| `core/signal_engine.py` | `begin()` and `stop_simulation()` park DACs at `DAC_IDLE_VALUE` (0 V) instead of `DAC_CENTER_VALUE` (2048 ≈ 1.6 V, which would hold LEDs at ~half drive in the driver concept). New `shutdown()` = stop + `dac_manager.shutdown()`. `DAC_CENTER_VALUE` remains for interpolation-seed use only. |
| `main.py` | Exit path (`finally:`) now calls `engine.shutdown()` instead of `engine.stop_simulation()` so the process leaves both DAC outputs at the 0 V safe state. |
| `tests/test_phase4_dac.py` | **New** — 31 hardware-free stdlib-unittest tests (see §4). |
| `docs/architecture/PHASE_4_DUAL_DAC_TX_AND_LED_DRIVER.md` | **New** — full TX-path audit, shared-bus/timing analysis, LED-driver/LM358 analysis, hardware validation plan. |

Not touched (deliberately): `calibration.py`, `models/ppg_model.py`, `config_store.py`, all Phase 2–3 primitives, all existing tests, UI frames.

## 3. Commands actually run and real results

| Command | Result |
|---------|--------|
| `python3 -m unittest tests.test_calibration tests.test_phase3_acdc` (baseline, before changes) | **PASS — Ran 51 tests, OK** |
| `python3 -m unittest tests.test_calibration tests.test_phase3_acdc tests.test_phase4_dac` (after changes) | **PASS — Ran 82 tests, OK** (51 preserved + 31 new) |
| Dry-run engine lifecycle smoke (`PPG_DRY_RUN=1`: begin → start → 0.3 s run → stop → shutdown) | **PASS** — begin parks 0/0; running writes plausible codes (last ≈ 1931/1927, i.e. the ~1.5 V DC region); stop parks 0/0; shutdown parks 0/0 and sets not-ready |
| Read of `adafruit_mcp4725.py` 1.4.21 source (API audit) | Done — findings in analysis doc §1.2 |
| `grep` audits (`ppg_sample_to_dac_value`, `ac_value_to_dac_12bit`, `set_values`/`stop_simulation` callers, `periodic_update` dispatch) | Done — see §5 |
| Any hardware/I2C command (`i2cdetect`, logic analyzer, oscilloscope) | **NOT RUN / BLOCKED** — no Pi, no HAT, no DACs on this machine |

## 4. New tests (tests/test_phase4_dac.py — 31 tests, all hardware-free)

- **Fixed channel mapping:** `DAC_ADDR_IR == 0x60`, `DAC_ADDR_RED == 0x61`, distinct.
- **3.2 V conversion boundaries:** 0 V→0, 3.2 V→4095, 3.3 V→clamped 4095, negative→0, 1.6 V→2047, 3.1999 V→4094; `DAC_FULLSCALE_V` and `ADC_VOLTAGE_REF` remain separate; `DAC_IDLE_VALUE == 0`; regression guard that the duplicate conversion method stays removed.
- **Per-channel routing:** injected fake DACs prove IR value → IR device, Red value → Red device, IR written before Red; clamping and int coercion at the write boundary; write lock held during writes.
- **Failure isolation:** simulated I2C NACK on one channel does not block the other, never raises, per-channel error counters accumulate.
- **begin() wiring:** fake `board`/`busio`/`adafruit_mcp4725` modules prove `begin()` constructs 0x60 as IR then 0x61 as Red and parks outputs at 0; forced import failure (disconnected/absent stack) → `begin()` returns False, not-ready, subsequent writes are safe no-ops.
- **Dry-run status:** begin succeeds, `is_ready` true, bookkeeping via `last_ir`/`last_red`, shutdown parks at idle and disables.
- **Engine integration (dry-run):** `SignalEngine.begin()/stop_simulation()/shutdown()` all leave both DACs at `DAC_IDLE_VALUE`.

## 5. Dual-DAC findings (audit results)

1. **Driver API [VERIFIED-CODE]:** `raw_value` → one 2-byte fast-mode I2C write per DAC per tick; device presence is probed at `MCP4725()` construction, so a missing DAC fails at `begin()`, not mid-stream.
2. **Thread-safety hazard found and fixed:** the driver's payload buffer is a class attribute shared by both DAC instances ("not thread-safe or re-entrant by design"). Project code has two potential writer threads (SignalGen; Tk main thread via `CalibrationFrame.periodic_update()` at `ui/ctk_app.py:97-98` dispatch). Overlap was excluded only by convention (`on_show()` stops the engine; join timeout 2 s). `DACManager` now serializes writes internally — this is also the declared single TX-side serialization point for Phase 5.
3. **Partial-update defect found and fixed:** previously one `try/except` wrapped both writes, so an IR exception skipped the Red write; now isolated per channel.
4. **Unsafe idle found and fixed:** init/stop/exit previously parked outputs at 2048 (≈1.6 V). Under the LED-driver concept (I_LED ∝ V_DAC) that holds both LEDs at ~half drive. All idle paths now command 0 V (`DAC_IDLE_VALUE`), unit-tested.
5. **Dead duplicate conversion removed:** `DACManager.ppg_sample_to_dac_value()` (own `*4095` window normalization, zero callers) deleted. `dac_voltage_to_code()` (3.2 V SSOT) remains the only live conversion path — `SignalEngine._v_to_dac` and `CalibrationFrame` both delegate to it [VERIFIED-CODE].
6. **Remaining legacy flagged, not touched:** `models/ppg_model.py` still defines `ppg_sample_to_dac_value()` (line ~766) and `ac_value_to_dac_12bit()` (line ~753) — both have **zero callers** and carry their own `*4095` formulas. Removing them is Phase 7-adjacent cleanup; they are inert today.
7. **Sequential-write skew:** Red always updates after IR by one transaction time within a tick — deterministic order, unmeasured magnitude.

## 6. One-Pi / one-HAT shared-resource implications

All of TX (0x60, 0x61), RX (0x04), processing, and UI run on the same Pi and the same `/dev/i2c-1`. Full analysis in the architecture doc §2; key implications:

- Kernel i2c-core serializes individual transactions per adapter, so Blinka (DAC) and grove.adc (Phase 5 ADC, separate fd) cannot corrupt each other's transactions — but nothing serializes multi-transaction *sequences* across the two libraries.
- **[INFERENCE — calculation, unmeasured]:** at the Pi's 100 kHz default I2C clock, the two DAC writes alone take ≈ 0.56 ms of each 1 ms tick; adding two Grove-ADC channel reads (≈ 0.45 ms each at 100 kHz) exceeds the tick. Phase 5 therefore must verify/raise the bus clock (400 kHz → TX ≈ 0.14 ms/tick) and/or run RX at a decoupled lower rate (100–200 Hz is ample for 0.5–10 Hz PPG bandwidth). The actual bus clock on the target Pi is UNKNOWN.
- Ownership rule going forward: SignalGen thread owns TX (through the now-locked `DACManager`); the Phase 5 acquisition thread must own RX and never call into the DAC path; UI threads write DACs only with the engine stopped.
- CPU/UI contention (Tk mainloop + 1 kHz polling thread on a non-RT kernel): jitter is unmeasured; no timing success is claimed.

## 7. LED-driver analysis (summary — full version in architecture doc §3)

- Concept documented: DAC (0–3.2 V) → op-amp control stage → transistor/MOSFET if required → R_sense → I_LED = V_DAC/R_sense. One stage per channel. 0 V command = LED off (hence the safe-idle correction).
- LM358 [DATASHEET-CLASS + INFERENCE]: on a **3.3 V rail it is not sufficient** (input common-mode and output swing end ≈ 1.8 V, below the 3.2 V command range). On a **5 V rail the control function is feasible** (CM ≈ 0–3.5 V), but headroom for V_sense up to 3.2 V + LED Vf + transistor drop does not close at full-scale command — the design needs a scaled command, a smaller sense budget, or a higher LED supply. Bandwidth/slew are not binding for PPG-rate signals.
- Whether an external transistor is required depends on the LED current rating, which is not documented anywhere in the project: **I am not sure based on the currently available evidence.**
- Final circuit values (R_sense, divider, transistor part, current targets): **I am not sure based on the currently available evidence.** No LED ratings, wavelengths, forward voltages, resistor values, part numbers, optical powers, or bench results were invented.

## 8. Hardware-validation status

**NOT RUN / BLOCKED** — no Pi, HAT, DACs, LEDs, logic analyzer, or oscilloscope on this machine. A concrete, itemized validation plan (logic analyzer: ACK at 0x60/0x61, payload format, update interval, IR→Red gap, bus clock, retries; oscilloscope: 0 V idle, DC/AC levels vs. predictions, pulse period, clipping, settling, driver saturation) is written in the architecture doc §4 for execution on the real hardware. Nothing in Phase 4 constitutes hardware validation.

## 9. Git diff summary

Working tree (uncommitted; includes earlier Phase 2–3 work): `git diff --stat` reports 462 insertions / 244 deletions across `config.py`, `config_store.py`, `core/signal_engine.py`, `hw/dac_manager.py`, `main.py`, `models/ppg_model.py`, UI frames, plus untracked `calibration.py`, `tests/`, `docs/`.

**Phase 4's own delta** is confined to: `config.py` (+2 blocks: `DAC_IDLE_VALUE`, ADC-comment fix), `hw/dac_manager.py` (rewritten, 92 → 132 lines), `core/signal_engine.py` (idle parking ×2, new `shutdown()`, import), `main.py` (1 line), plus new `tests/test_phase4_dac.py` and the two Phase 4 docs. `models/ppg_model.py`, `config_store.py`, and UI-frame diffs are Phase 2–3 work, untouched by Phase 4.

## 10. Acceptance checklist

- [x] Actual I2C init path, MCP4725 API, per-address init, call order, thread ownership, rate mechanism, dry-run, shutdown, and exception handling audited from real source (project + installed library)
- [x] Channel mapping 0x60=IR / 0x61=Red preserved, comment-consistent, and locked by tests
- [x] DAC conversion stays centralized on `dac_voltage_to_code` / `DAC_FULLSCALE_V=3.2`; no `/3.3`, `3300`, or new `*4095` formulas introduced; one dead duplicate removed
- [x] `ADC_VOLTAGE_REF=3.3` untouched and kept separate (test-guarded)
- [x] Shared-bus contention, write cadence, sequential-write behavior, serialization owner, and unmeasured-jitter caveats documented
- [x] LED-driver concept + LM358 analysis documented from evidence only; unknowns answered with the required exact sentence
- [x] Hardware validation plan written; zero fabricated measurements; status NOT RUN/BLOCKED
- [x] All 51 pre-existing tests preserved and passing; 31 new Phase 4 tests passing (82 total, `python3 -m unittest`)
- [x] No OPT101 acquisition, no measured SpO2, no UI redesign (out of scope respected)

## 11. DO-NOT-REDO handoff for Phase 5

Phase 5 (OPT101/Grove-ADC acquisition) must **not** re-implement or alter:

1. `DACManager` write path: locking, per-channel error isolation, rate-limited logging, `shutdown()`, 0 V safe idle — done and tested. Phase 5 must not add DAC writes anywhere; TX stays owned by the SignalGen thread.
2. `DAC_IDLE_VALUE=0` semantics in `config.py`, `SignalEngine.begin/stop_simulation/shutdown`, `main.py` exit path.
3. The 3.2 V SSOT conversion (`calibration.dac_voltage_to_code`) and the 0x60/0x61 mapping — both test-locked; changing them must fail `tests/test_phase4_dac.py`.
4. The 82-test suite — keep green; add Phase 5 tests in a new file.

Phase 5 open items prepared by this phase:
- Verify the actual I2C bus clock on the Pi; if 100 kHz, either raise to 400 kHz or keep ADC sampling ≤ ~200 Hz (analysis doc §2.2) — then **measure**, don't assume.
- Read the installed `grove.adc` source on the Pi to confirm its transaction shape and fd usage before finalizing the RX loop design.
- Give RX its own single-owner thread; never share the DAC objects or the Blinka bus object with it.
- `GROVE_ADC_CHANNEL` in `config.py` is legacy (deprecated `hw/adc_reader.py` only); introduce explicit `A0=IR / A1=Red` channel constants in Phase 5.
- Legacy dead code flagged for later cleanup (not Phase 5's job): `ppg_sample_to_dac_value()` and `ac_value_to_dac_12bit()` in `models/ppg_model.py`.

**Phase 4 is complete. Stopping here — Phase 5 not started.**
