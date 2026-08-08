# 01 — Current System Audit

**Project:** PPG Signal Simulator (Raspberry Pi 4 + Grove Base HAT)
**Repository:** `/home/huynn/final_project/PPG_simulator_raspi`
**Branch:** `huynn` — HEAD `7b29689`
**Date:** 2026-07-29
**Authority:** `docs/superpowers/ppg_design_audit/00_BASE_CONTEXT.md` (read first; it wins over every
source file, phase document, completion report and prior Claude-generated document cited below)

---

## 0. Scope, method and constraints

### 0.1 What this document is

A read-only audit of the **current** state of the system: what really exists in source code, what
exists only as prose, what runs but has never touched hardware, what is partial, and what is
obsolete or self-contradictory.

### 0.2 Constraints honoured

- **No implementation file was modified.** No source, test, phase document, schematic, PCB file,
  configuration file or historical report was edited, created, deleted, staged, reverted or
  committed by this audit.
- **No circuit values are proposed here.** That is deferred to a later prompt.
- **The uncommitted / untracked working tree was left exactly as found.**
- **The test-discovery failure was not fixed** (see §4.6) — it is recorded as a finding only.

### 0.3 Evidence labels used

Per `00_BASE_CONTEXT.md` §6: `[VERIFIED-USER]`, `[VERIFIED-DATASHEET]`, `[VERIFIED-SCHEMATIC]`,
`[VERIFIED-CODE]`, `[CALCULATED]`, `[ENGINEERING-INFERENCE]`, `[RECOMMENDED STARTING VALUE]`,
`[MEASUREMENT-REQUIRED]`, `[UNKNOWN]`.

One **non-approved** label was found in the codebase and is reported as a defect: `[VERIFIED-PDF]`
(`calibration.py:13`, and pervasively in `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md`).

### 0.4 Material inspected

| Area | Items |
|---|---|
| Base context | `docs/superpowers/ppg_design_audit/00_BASE_CONTEXT.md` |
| Entry point | `main.py` |
| Configuration | `config.py`, `config_store.py`, `requirements.txt` |
| Calibration SSOT | `calibration.py` |
| Model | `models/ppg_model.py` |
| Core | `core/signal_engine.py`, `core/state_machine.py`, `core/digital_filters.py`, `core/param_controller.py`, `core/csv_logger.py` |
| Hardware | `hw/dac_manager.py`, `hw/opt101_rx.py`, `hw/adc_reader.py`, `hw/button_handler.py` |
| UI | `ui/ctk_app.py`, `ui/frames/pathology_frame.py`, `ui/frames/calibration_frame.py`, `ui/frames/playback_frame.py`, `ui/sliders.py` |
| Comms | `comm/ble_server.py`, `comm/logger.py` |
| Scripts | `scripts/install_rpi_system_packages.sh`, `scripts/setup_rpi_venv.sh` |
| Tests | `tests/test_calibration.py`, `tests/test_phase3_acdc.py`, `tests/test_phase4_dac.py`, `tests/test_phase5_rx.py`, `test_i2c_speed.py` |
| Docs | `docs/architecture/`, `docs/claude_phases/`, `docs/phase_reports/` |
| VCS | `git status`, `git diff`, `git diff --stat` |

Excluded per `00_BASE_CONTEXT.md` §5.8: `.venv/`, `venv/`, `__pycache__/`, `.codegraph/`.
`.pio/` inspected only to classify it (§5.9).

---

## 1. Implemented in real source code

Everything in this section is `[VERIFIED-CODE]` — read directly from the working tree.

### 1.1 TX signal generation (Phases 1–4)

- **`models/ppg_model.py`** (811 lines) — full dual-channel PPG synthesis: three-component Gaussian
  sum beat model, six clinical conditions, respiratory modulation (baseline wander, amplitude
  modulation, FM/RSA), beat-to-beat HR and perfusion variability, per-channel AC/DC composition.
  `generate_both_samples()` (lines 548–691) returns `(signal_ir, signal_red, display_ir, display_red)`
  **in Volts**, clamped at lines 679–680 to `[0.0, DAC_FULLSCALE_V]`.
- **`core/signal_engine.py`** (304 lines) — singleton engine, 100 Hz model tick, 10× linear
  interpolation to 1 kHz, 1024-sample ring buffer, DAC write thread, start/stop/shutdown lifecycle.
- **`hw/dac_manager.py`** (130 lines) — dual MCP4725 driver via `adafruit_mcp4725` over Blinka
  `busio`. Docstring lines 7–9 lock `0x60 = IR`, `0x61 = Red`. Uses `_write_lock` because the
  Adafruit driver shares a class-level payload buffer across instances. `set_values()` clamps,
  writes IR then Red, isolates each channel in `try/except`, rate-limits error logging.
  `shutdown()` parks both DACs at `DAC_IDLE_VALUE = 0`.
- **`config.py`** (239 lines) — the hardware contract: `DAC_ADDR_IR = 0x60` (43),
  `DAC_ADDR_RED = 0x61` (44), `GROVE_ADC_ADDR = 0x04` (57), `ADC_CHANNEL_IR = 0` (58),
  `ADC_CHANNEL_RED = 2` (59), with an explicit `[VERIFIED-USER 2026-07-12, fixed — never swap]`
  note at 51–55 and a supersession note that "Earlier phase docs stated A1 = Red; that mapping is
  stale and superseded."

### 1.2 Calibration mathematics (Phases 2–3)

- **`calibration.py`** (276 lines, **untracked — never committed**) — single source of truth for:
  `dac_voltage_to_code()`, `perfusion_index_from_ac_dc()`, `ratio_of_ratios()`,
  `ac_red_from_target()`, `r_target_from_spo2()`, `validate_coefficients()`, `validate_ac_dc()`.
  Constants: `R_CLAMP_MIN = 0.4`, `R_CLAMP_MAX = 1.6`, `SPO2_COEFF_A_DEFAULT = 110.0`,
  `SPO2_COEFF_B_DEFAULT = 25.0`.
- The AC/DC-as-master model is fully implemented: `PI = AC/DC × 100`;
  `R = (AC_red/DC_red)/(AC_ir/DC_ir)`; `AC_red = R_target · AC_ir · (DC_red/DC_ir)`;
  `SpO2 = A − B·R`.

### 1.3 Persistent configuration

- **`config_store.py`** (182 lines) — JSON load/save with `_DEFAULTS` merge; Phase 2 keys
  (`spo2_coeff_a`, `spo2_coeff_b`) and Phase 3 keys (`dc_ir_mv`, `dc_red_mv`, `ac_polarity`).
  `apply_config_to_params()` validates every loaded value through `calibration.validate_*` and
  falls back to defaults with a `log.warning` on corruption. Backward-compatible with older
  `config.json` files that lack the newer keys.

### 1.4 RX acquisition (Phase 5)

- **`hw/opt101_rx.py`** (366 lines, **untracked**) — dedicated daemon thread sampling both Grove ADC
  channels at 100 Hz through `grove.adc.ADC.read_raw()`, bounded `deque` buffers, per-channel status
  state machine (`init` / `ok` / `saturated` / `invalid` / `error` / `disconnected` / `dry-run`).
  Catches grove.py's `sys.exit(2)` as `SystemExit` rather than letting it kill the process.
  Docstring lines 4–7 state `A0 = OPT101 IR; A2 = OPT101 Red; A1 is NOT used for OPT101.`
  Line 25: "RX NEVER writes to the DACs."

### 1.5 Application and UI

- **`main.py`** (76 lines) — starts the engine, starts RX (degrading to TX-only on failure, lines
  39–45), loads config, runs the CustomTkinter mainloop, saves config and calls `rx.shutdown()` /
  `engine.shutdown()` in `finally`.
- **`ui/ctk_app.py`** — CustomTkinter shell; imports `signal_engine`, `state_machine`, `csv_logger`,
  `PathologyFrame`, `CalibrationFrame`, `PlaybackFrame`.
- **`ui/frames/pathology_frame.py`** — condition selection, HR/RR/SpO₂/PI controls, amplitude readout.
- **`ui/frames/calibration_frame.py`** — A/B coefficient and DC-level controls; converts mV → DAC code
  via `dac_voltage_to_code(val_mv / 1000.0)` (lines 96–99).
- **`core/state_machine.py`**, **`core/csv_logger.py`**, **`ui/frames/playback_frame.py`** — active.

### 1.6 Anti-fabrication discipline in the acquisition layer

`hw/opt101_rx.py:27-30` is explicit: *"a failed, invalid, or unavailable read appends NOTHING to the
buffers — values are never fabricated. Dry-run mode is a clearly labeled simulation state that
produces no samples at all."* This is verified behaviour, not just prose — dry-run produces zero
samples and `test_phase5_rx.py` asserts it. **The RX path does not fake data.**

### 1.7 Provisioning scripts

`scripts/install_rpi_system_packages.sh` (6.5 K) and `scripts/setup_rpi_venv.sh` (10.1 K) exist and
are executable. Neither has been executed on the target Pi within any recorded evidence.

---

## 2. Documentation-only (exists in prose, not in code)

| Item | Where described | Code evidence |
|---|---|---|
| Phase 6 — measured AC/DC extraction from RX buffers | `docs/claude_phases/06_*.md`, `docs/claude_phases/00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md:61-73` | None. No module consumes `OPT101Receiver` output. |
| Measured SpO₂ (`SpO2 = A − B·R` from **measured** R) | Same | None. Only *target*-driven SpO₂ exists (TX side). |
| Measured PI per channel from real ADC samples | Same | None. `ppg_model.get_measured_pi()` (806–811) measures the model's **own** generated peak/valley. |
| RX waveform display in the UI (Phase 7) | `docs/claude_phases/07_*.md` | None. `ui/ctk_app.py` never imports `hw.opt101_rx`. |
| Optical crosstalk mitigation, physical baffling, TDM LED drive | `docs/phase_reports/PHASE_05_COMPLETION_REPORT.md:108`, `docs/architecture/PHASE_1_...md:372,488,503` | None — and per `00_BASE_CONTEXT.md` N-02/N-03/N-05 the premise itself is wrong (see §5.1). |
| Tissue / diffuser in the optical path | `docs/architecture/PHASE_1_...md:366` (`LEDopt -.->\|"tissue/diffuser (TBD)"\| PD`) | None — contradicted by N-04. |
| Phases 8–10 (logging/export, validation, packaging) | `docs/claude_phases/08_*.md`, `09_*.md`, `10_*.md` | Partial only via `core/csv_logger.py`. |

---

## 3. Software-complete but hardware-unverified

**No line of this project has ever been proven to run on the Raspberry Pi 4.** This is the single
most important qualifier on every "COMPLETE" claim below.

Evidence: `docs/phase_reports/PRE_PHASE_06_ENVIRONMENT_SETUP_REPORT.md` §0 records that it was
executed on the development laptop `huynn-lap` (x86_64, Ubuntu 24.04) — **not** on the Pi — and §9
records steps 10–16 (all hardware steps) as **NOT RUN / BLOCKED**. That report explicitly states
"No hardware-validation result is fabricated anywhere", which is correct and commendable.

Consequently, all of the following are `SOFTWARE COMPLETE / HARDWARE NOT VERIFIED`:

- Every I²C write to MCP4725 `0x60` / `0x61` — **never executed on real hardware** `[MEASUREMENT-REQUIRED]`.
- The actual DAC output voltage on the wire — **never measured in this project's records**
  `[MEASUREMENT-REQUIRED]`. See §5.2: the 3.2 V constant in code is attributed to a measurement, but
  the authoritative value is now 3.28 V and no repeat measurement exists.
- Every Grove ADC read on A0 / A2 — **never executed on real hardware** `[MEASUREMENT-REQUIRED]`.
- LED drive current, OPT101 output range, LM358 behaviour — `[MEASUREMENT-REQUIRED]`.
- Timing: 1 kHz DAC write cadence and 100 Hz/channel ADC cadence on the real I²C bus —
  `[MEASUREMENT-REQUIRED]`. `test_i2c_speed.py` was evidently intended to measure this and is empty
  (§5.7).
- End-to-end TX → optical → RX loop-back — never performed.

---

## 4. Partial and missing

### 4.1 RX is acquired but never consumed — the central functional gap

`main.py:41-45` starts `OPT101Receiver`; `main.py:71` shuts it down. **Between those two points no
code reads its buffers.** Grep confirms no importer of `hw.opt101_rx` other than `main.py` and
`tests/test_phase5_rx.py`. The receiver is a working data sink with no consumer. → Phase 6 is
`DESIGN ONLY / NOT IMPLEMENTED`.

### 4.2 The UI displays generated TX values, not measured RX

`ui/frames/pathology_frame.py:239` computes and labels an amplitude:

```python
ac_ir_v = self.engine.ppg_model.measured_peak - self.engine.ppg_model.measured_valley
...
ac_red_v = ac_red_from_target(r_val, ac_ir_v, m.dc_red, m.dc_ir)
self.amp_label.configure(text=f"IR: {ac_ir_v*1000:.1f} mV | RED: {ac_red_v*1000:.1f} mV")
```

- `ac_ir_v` is the **model's self-measurement** of its own generated waveform, not an ADC reading.
- `ac_red_v` is a **pure formula output** — it is never measured at all.
- The attribute names `measured_peak` / `measured_valley` and the label word "mV" read as measurement.

This is **not** the acquisition layer faking data (§1.6 shows it does not). It is a
**naming and presentation risk**: nothing in the UI tells the operator these are synthesised
transmit-side values. Under the project's own anti-fabrication rules this must be relabelled before
any measured-SpO₂ feature lands beside it.

### 4.3 Missing: measured-signal processing chain

No filtering, no peak/valley detection, no AC/DC extraction, no R computation, no SpO₂ estimation
operating on RX data. All of Phase 6.

### 4.4 Missing: RX visualisation

No RX plot, no per-channel status indicator, no saturation/disconnect annunciation in the GUI, even
though `opt101_rx.py` maintains exactly that state.

### 4.5 `requirements.txt` is stale in both directions

Read in full. It lists `pygame>=2.5.0`, `RPi.GPIO>=0.7.0`, `bless>=0.2.6`, `numpy>=1.24.0`,
`adafruit-circuitpython-mcp4725>=1.4.0`, `adafruit-blinka>=8.0.0`; `grove.py` appears only as a
comment.

- **Missing** — `customtkinter` (the actual GUI framework, imported by `ui/ctk_app.py`) and
  `smbus2` (used by grove.py 0.6).
- **Present but unused** — `pygame` (only `ui/sliders.py`, which is outside the import path),
  `bless` (only `comm/ble_server.py`, outside the import path), `numpy`
  (confirmed unused by `PRE_PHASE_06_ENVIRONMENT_SETUP_REPORT.md` §2), `RPi.GPIO` (only
  `hw/button_handler.py`, outside the import path).

A fresh clone installed from this file **cannot start the application**.

### 4.6 Test discovery is broken (infrastructure, not test logic)

```
$ python -m unittest discover -s tests -t .
ImportError: Start directory is not importable:
'/home/huynn/final_project/PPG_simulator_raspi/tests'
```

Cause: `tests/` contains no `__init__.py`. Classification: **test-discovery / infrastructure issue**,
not a test failure and not a product defect.

**Deliberately not fixed during this audit** (no `__init__.py` was added, no test file touched), per
the audit constraints.

Workaround used to obtain real evidence — each file executed directly:

| Test file | Result |
|---|---|
| `tests/test_calibration.py` | **26 PASS** |
| `tests/test_phase3_acdc.py` | **25 PASS** |
| `tests/test_phase4_dac.py` | **31 PASS** |
| `tests/test_phase5_rx.py` | **32 PASS** |
| **Total** | **114 PASS, 0 fail** |

Command form: `PPG_DRY_RUN=1 .venv/bin/python tests/<file>.py`.
All 114 passes are **dry-run / host** passes. None involved hardware.

### 4.7 `calibration.py` and `hw/opt101_rx.py` are untracked

Two of the most load-bearing modules in the project — the calibration SSOT and the entire RX layer —
have **never been committed to git**. They exist only in the working tree. This is a data-loss risk,
not a design defect.

---

## 5. Obsolete or contradictory evidence

### 5.1 Optical architecture: shared cavity / crosstalk / TDM (highest-severity doc contradiction)

`00_BASE_CONTEXT.md` §4 defines the real hardware: a **dark chamber with two fully isolated
compartments** — IR LED → dedicated IR OPT101 → A0, and Red LED → dedicated Red OPT101 → A2 — with
negative facts N-01 (no WhaleTeq optical fixture), N-02 (no shared detector), N-03 (no common
optical cavity), N-04 (no tissue phantom), N-05 (no intentional Red/IR optical mixing).

Multiple documents assert the opposite. Consequences if left uncorrected: Phase 6+ would implement
crosstalk compensation and time-division LED multiplexing that solve a problem this hardware does
not have, at the cost of real effective sample rate.

### 5.2 DAC full-scale: 3.28 V vs 3.2 V vs 3.3 V

Three distinct numbers are in play and must not be conflated:

| Value | Meaning | Status |
|---|---|---|
| **3.28 V** | MCP4725 supply **and** full-scale, and OPT101 supply | **Authoritative current truth** `[VERIFIED-USER]` — `00_BASE_CONTEXT.md` F-08/F-09/F-10 |
| **3.2 V** | The value hard-coded throughout code, docs and tests | **Existing behaviour** — `[VERIFIED-CODE]`, superseded as a fact |
| **3.3 V** | Grove Base HAT **ADC reference** | **Separate quantity** — must stay 3.3 V, must not be changed as a side-effect of fixing the DAC value |

A repository-wide grep found **zero occurrences of `3.28` anywhere in code, tests or documentation**.
The 3.28 V fact currently lives only in `00_BASE_CONTEXT.md`.

`config.py:107-115` additionally **misattributes** the 3.2 V value:

```python
# The measured full-scale on this hardware is 3.2 V [VERIFIED-USER], which is
# below the nominal 3.3 V VDD. ...
DAC_FULLSCALE_V = 3.2
```

The `[VERIFIED-USER]` label on 3.2 is now false. Whether 3.2 V was ever measured on this hardware, or
was inherited from an earlier assumption, is `[UNKNOWN]` from current evidence — and **no repeat
measurement has been performed** `[MEASUREMENT-REQUIRED]`.

The 3.2 V value propagates into: `calibration.py:15-17`, `calibration.dac_voltage_to_code()`,
`calibration.validate_ac_dc()`, `models/ppg_model.py:679-680`, `core/signal_engine.py:157-162`,
`ui/frames/calibration_frame.py:98`, and is **hard-locked by assertions** in
`tests/test_phase4_dac.py:107` and `tests/test_calibration.py:137,149`.

**Any correction to 3.28 V is therefore a coordinated change across code + tests + ~30 doc sites, and
is out of scope for this audit.**

Positive finding: the ADC reference **is** correctly kept separate today —
`config.py:149` (`ADC_VOLTAGE_REF = 3.3  # Volts — Grove ADC reference; NOT the DAC 3.2 V`),
`hw/opt101_rx.py:81-87` ("Do NOT confuse with the DAC 3.2 V full-scale"), and this separation is
test-guarded by `tests/test_phase4_dac.py:113` (`assertNotEqual(DAC_FULLSCALE_V, ADC_VOLTAGE_REF)`).
That guard must survive any future 3.2 → 3.28 change.

### 5.3 ADC channel mapping: A0/A2 (correct) vs A0/A1 (stale)

**Authoritative:** A0 = OPT101 IR, A2 = OPT101 Red, **A1 unused for OPT101**
(`00_BASE_CONTEXT.md` F-06/F-07; `[VERIFIED-USER 2026-07-12]`).

**Correct today** — `config.py:57-59` + note 51–55; `hw/opt101_rx.py:4-7`;
`tests/test_phase5_rx.py` (locks A0/A2 and raises `ValueError` on A1);
`docs/claude_phases/00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md:14-16`;
`docs/phase_reports/PHASE_05_COMPLETION_REPORT.md`.

**Still stale (state A1 = Red)** — approximately 13 documents, including
`docs/architecture/PHASE_4_DUAL_DAC_TX_AND_LED_DRIVER.md:26` ("OPT101 IR → A0, OPT101 Red → A1,
A2 obsolete"), `docs/phase_reports/PHASE_04_COMPLETION_REPORT.md:20,111`,
`docs/claude_phases/04`, `05`, `06`, `07`, `08`, `09`, `10`,
`docs/claude_phases/00_README_ALL_PHASES.md`, `00_README_FROM_PHASE_4.md`, `RUN_PHASE_4_PROMPT.md`.

**Most dangerous instance:** `docs/claude_phases/06_*.md` lines 14, 26, 85, 105 — the Phase 6
specification, i.e. the *next work to be done*, still says A1 = Red. Implementing Phase 6 from that
document as written would read the wrong ADC channel.

### 5.4 Red / IR channel assignment

Audited specifically. **No error found.** `0x60 = IR` and `0x61 = Red` are consistent across
`config.py:43-44`, `hw/dac_manager.py:7-9`, `00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md:11-12`
and `00_BASE_CONTEXT.md` F-03/F-04, and are locked by `tests/test_phase4_dac.py:92,95`. No swapped
assignment exists anywhere in the active source.

### 5.5 WhaleTeq provenance leaking into code

`00_BASE_CONTEXT.md` N-01 states there is no WhaleTeq optical fixture. WhaleTeq is a **functional /
behavioural reference only** — the source of the default `A = 110, B = 25` linear SpO₂ relation — and
is **not** part of this project's physical optical architecture.

Occurrences that read as physical provenance: `calibration.py:10-13,31,146`
("reproduce the WhaleTeq AECG100 default", "(Phase 1 §17/§18, WhaleTeq AECG100)"),
`models/ppg_model.py:58` (AECG100 polarity reference), `tests/test_calibration.py:43`.

### 5.6 Obsolete and orphaned code

| File | Evidence | Classification |
|---|---|---|
| `hw/adc_reader.py` | Line 2: `"""DEPRECATED: This module is no longer used. UI sliders now control parameters.` | `OBSOLETE / SUPERSEDED` |
| `core/digital_filters.py` | Header "Port of digital_filters.cpp"; grep → **zero importers** | `OBSOLETE / SUPERSEDED` |
| `core/param_controller.py` | Header "Port of param_controller.cpp"; grep → **zero importers** | `OBSOLETE / SUPERSEDED` |
| `ui/sliders.py` | pygame-based; outside the CustomTkinter import path | `OBSOLETE / SUPERSEDED` |
| `hw/button_handler.py` | RPi.GPIO physical-button UI; outside the import path | `OBSOLETE / SUPERSEDED` |
| `comm/ble_server.py` | `bless` BLE server; outside the import path | `OBSOLETE / SUPERSEDED` |
| `config.py:118-239` | pygame-era DISPLAY/COLOR/FONT constants + `compute_layout()`; dead under CustomTkinter | `OBSOLETE / SUPERSEDED` |

Note: `core/state_machine.py` is also an ESP32 port ("Port of state_machine.cpp") but **is** actively
imported by `ui/ctk_app.py` — it is **not** obsolete.

### 5.7 `test_i2c_speed.py` is empty

`./test_i2c_speed.py` — **0 bytes**, at the repository root (not in `tests/`). It is not a failing
test; it is an unwritten one. Its name implies it was meant to characterise real I²C throughput —
exactly the `[MEASUREMENT-REQUIRED]` item in §3.

### 5.8 ESP32-S3 lineage still visible

`config.py:7` — "Port of the ESP32-S3 config.h to Python".
`README.md:18` — "Python port of the ESP32-S3 PPG Signal Simulator firmware".
Neither is wrong historically, but both invite the reader to look for a microcontroller that is not
part of the authoritative single-Pi architecture.

### 5.9 The `.pio/` tree

`.pio/` contains only `libdeps/` — PlatformIO library dependencies from the original ESP32-S3
firmware project. It is **tracked in git** (last touched in commit `b88df16`) and is **not** in
`.gitignore`.

Classification: **historical / unrelated to the authoritative one-Pi architecture.** Whether any file
under it is still referenced by anything is `UNKNOWN` from current evidence — it was excluded from
detailed inspection per `00_BASE_CONTEXT.md` §5.8. No active Python module imports from it.

### 5.10 Non-approved evidence label in code

`calibration.py:13` uses `[VERIFIED-PDF]`, which is **not** one of the nine labels defined in
`00_BASE_CONTEXT.md` §6. The same label is used pervasively throughout
`docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md`.

### 5.11 Minor code-level inconsistencies

- `core/signal_engine.py:190` — `ir_mv, red_mv, disp_ir, disp_red = ...generate_both_samples(...)`.
  The names say "mv" but the model returns **Volts**. `_v_to_dac()` expects Volts, so **behaviour is
  correct**; only the naming is misleading.
- `core/signal_engine.py:192` — `dc = self.ppg_model.dc_baseline` is dead (assigned, never used).
- `core/signal_engine.py:208-209` — hard-codes `max(0, min(4095, ...))` instead of using
  `DAC_MAX_VALUE`.
- Ring-buffer and interpolation state initialise to `DAC_CENTER_VALUE` (2048), which contradicts
  `config.py`'s own warning never to park the DAC at mid-scale (`DAC_IDLE_VALUE = 0`).
- `models/ppg_model.py` retains unused legacy converters `ac_value_to_dac_12bit()` and
  `ppg_sample_to_dac_value()` that hard-code 0.45 / 4095 / 2048.

### 5.12 Working tree state (recorded, not acted upon)

Extensive uncommitted and untracked work exists and was **left untouched**:

- **Modified:** `CLAUDE.md`, `config.py`, `config_store.py`, `core/signal_engine.py`,
  `hw/dac_manager.py`, `main.py`, `models/ppg_model.py`, `ui/frames/calibration_frame.py`,
  `ui/frames/pathology_frame.py` (plus a large volume of `.venv/` `.pyc` churn).
- **Deleted:** `MedicalSimulator` submodule, `docs/user_manual.pdf`,
  `docs/version_sdk_app_whale.pdf`, `docs/whale_device.pdf`.
- **Untracked:** `calibration.py`, `hw/opt101_rx.py`, `tests/`, `scripts/`, `.codegraph/`,
  `docs/architecture/`, `docs/claude_phases/`, `docs/phase_reports/`, `docs/ds_linhkien/`,
  `docs/skill/`, `docs/superpowers/`, `docs/whale_device/`.

**Nothing was reverted, cleaned, staged or committed.**

---

## 6. Completed work that must NOT be redone

Rewriting any of the following would destroy verified, working, test-covered engineering:

1. **`models/ppg_model.py`** — the entire PPG synthesis model (Gaussian beat model, six conditions,
   respiratory modulation, HR/PI variability). Largest and most mature component.
2. **`calibration.py`** — the AC/DC-as-master calibration SSOT. Covered by 26 passing tests.
   Only the 3.2 → 3.28 V constant is in question; **the mathematics is correct and must be kept.**
3. **`hw/dac_manager.py`** — dual-MCP4725 driver including the `_write_lock` fix for the Adafruit
   shared class-level buffer and the park-at-zero shutdown. Covered by 31 passing tests.
4. **`hw/opt101_rx.py`** — the complete RX acquisition layer including the `SystemExit` handling of
   grove.py's `sys.exit(2)`, the per-channel status state machine, and the never-fabricate
   guarantee. Covered by 32 passing tests. **Phase 5 is done; do not rewrite it.**
5. **`core/signal_engine.py`** — the 100 Hz → 10× interpolation → 1 kHz TX pipeline and its
   threading/lifecycle model.
6. **`config_store.py`** — validated, backward-compatible persistence.
7. **The A0 = IR / A2 = Red mapping already correct in code**, and the test assertions that lock it.
8. **The `0x60` = IR / `0x61` = Red mapping**, and the tests that lock it.
9. **The DAC-full-scale vs ADC-reference separation** (`config.py:149`, `opt101_rx.py:81-87`,
   `test_phase4_dac.py:113`) — this guard must survive the 3.28 V correction.
10. **All 114 passing tests.** They are the only regression net this project has.
11. **`docs/phase_reports/PRE_PHASE_06_ENVIRONMENT_SETUP_REPORT.md`** — an honest, well-scoped
    environment report that correctly refuses to claim hardware results. Preserve it.
12. **`scripts/setup_rpi_venv.sh` / `install_rpi_system_packages.sh`** — provisioning already written.

---

## 7. Targeted searches (required by the prompt)

| # | Search target | Finding |
|---|---|---|
| 1 | **A0/A1 vs A0/A2 mapping** | Code, `config.py`, `opt101_rx.py` and `test_phase5_rx.py` are **correct (A0/A2)**. ~13 phase/architecture documents still say **A1 = Red**, including the Phase 6 spec itself. See §5.3. |
| 2 | **DAC full-scale 3.2 / 3.28 / 3.3 V** | Code + tests + ~30 doc sites all say **3.2 V**. Authoritative value is **3.28 V**. **Zero occurrences of `3.28` exist outside `00_BASE_CONTEXT.md`.** `config.py:112` falsely labels 3.2 as `[VERIFIED-USER]`. See §5.2. |
| 3 | **ADC reference confused with DAC full-scale** | **Not confused.** Correctly separated in `config.py:149` and `opt101_rx.py:81-87`, and test-guarded at `test_phase4_dac.py:113`. `ADC_VOLTAGE_REF = 3.3` must remain 3.3 V. |
| 4 | **Incorrect Red / IR assignments** | **None found.** Consistent and test-locked everywhere. See §5.4. |
| 5 | **Generated TX data used as fake RX measurement** | **Not in the acquisition layer** — `opt101_rx.py` refuses to fabricate and yields zero samples in dry-run. **But** `ui/frames/pathology_frame.py:239` presents model self-measured `measured_peak − measured_valley` and a purely computed `ac_red_v` as "mV" amplitudes with no TX/RX label. A **naming/presentation** fabrication risk. See §4.2. |
| 6 | **Old one-channel or multiple-controller assumptions** | Active source assumes exactly one Pi, one Grove HAT, two DACs, two ADC channels — **correct**. Residue: `config.py:62` `GROVE_ADC_CHANNEL = 0` (flagged legacy-only in-file), `hw/adc_reader.py` (single-channel, DEPRECATED), the ESP32-S3 lineage in `config.py:7` / `README.md:18`, and the tracked `.pio/libdeps/` tree. No second-controller assumption survives in active code. |

---

## 8. Subsystem matrix

| Subsystem | Intended design | Current evidence | Status | Missing work | Risk |
|---|---|---|---|---|---|
| PPG waveform model | Dual-channel physiological synthesis with conditions + respiratory modulation | `models/ppg_model.py` (811 lines), `generate_both_samples()` returns Volts, clamped to full-scale | COMPLETE | Retire unused legacy converters | LOW |
| Calibration mathematics | PI, R, AC_red-from-target, SpO₂ = A − B·R, single source of truth | `calibration.py` (276 lines); 26 tests PASS | COMPLETE | Correct full-scale constant 3.2 → 3.28 V; drop `[VERIFIED-PDF]`; reword WhaleTeq provenance | HIGH — every voltage→code conversion is scaled by the wrong constant |
| Config constants | Authoritative hardware contract | `config.py`: 0x60/0x61, A0/A2, 0x04 all correct; `DAC_FULLSCALE_V = 3.2`; `ADC_VOLTAGE_REF = 3.3` correct | PARTIAL | Correct 3.2 → 3.28 V and its false `[VERIFIED-USER]` label; delete pygame block 118–239 | HIGH |
| Config persistence | Validated, backward-compatible JSON store | `config_store.py` (182 lines), validation + default fallback | COMPLETE | None | LOW |
| TX pipeline (100 Hz → 1 kHz) | Model tick, 10× interpolation, ring buffer, DAC thread | `core/signal_engine.py` (304 lines) | SOFTWARE COMPLETE / HARDWARE NOT VERIFIED | Fix `ir_mv`/`red_mv` naming, dead `dc`, hardcoded 4095, mid-scale init | MEDIUM |
| Dual MCP4725 DAC driver | 0x60 = IR, 0x61 = Red, locked write, park at 0 | `hw/dac_manager.py` (130 lines); 31 tests PASS | SOFTWARE COMPLETE / HARDWARE NOT VERIFIED | Execute on the Pi; measure real output voltage | HIGH — full-scale unmeasured |
| DAC output voltage on the wire | Full-scale = 3.28 V | No measurement in any project record; code says 3.2 V | UNKNOWN | Measure with a DMM on the Pi `[MEASUREMENT-REQUIRED]` | HIGH |
| LED drive (2SC1815) + LM358 @ 5.00 V | Drive IR and Red LEDs from DAC voltage | Documented only; no schematic verified in this audit | UNKNOWN | Verify against schematic; measure | MEDIUM |
| Optical path | Dark chamber, **two isolated compartments**, no tissue, no shared cavity | `00_BASE_CONTEXT.md` §4 (authoritative); several docs assert the opposite | COMPLETE (hardware) / OBSOLETE / SUPERSEDED (documentation) | Supersede shared-cavity, crosstalk and TDM text | HIGH — would drive unnecessary TDM work |
| RX acquisition (Phase 5) | 100 Hz/channel on A0 + A2, bounded buffers, status FSM, never fabricate | `hw/opt101_rx.py` (366 lines); 32 tests PASS | SOFTWARE COMPLETE / HARDWARE NOT VERIFIED | Execute on the Pi; verify grove.py 0.6 behaviour | HIGH — untracked in git |
| RX data consumption | Filter → AC/DC → PI → R → measured SpO₂ | **No consumer of RX buffers exists anywhere** | DESIGN ONLY / NOT IMPLEMENTED | All of Phase 6 | HIGH |
| Measured SpO₂ | SpO₂ from **measured** R | Only target-driven TX-side SpO₂ exists | DESIGN ONLY / NOT IMPLEMENTED | All of Phase 6 | HIGH |
| GUI shell | CustomTkinter app with pathology / calibration / playback frames | `ui/ctk_app.py` + three frames | COMPLETE | None | LOW |
| GUI amplitude readout | Show real signal amplitudes | `pathology_frame.py:239` shows model self-measurement + a pure formula, labelled "mV" | PARTIAL | Label clearly as TX/generated; separate from any future measured value | HIGH — reads as measurement |
| RX visualisation (Phase 7) | Display RX waveforms and channel status | No RX import in the UI at all | DESIGN ONLY / NOT IMPLEMENTED | All of Phase 7 | MEDIUM |
| CSV logging / export | Session logging | `core/csv_logger.py` active | PARTIAL | Phase 8 scope not assessed | LOW |
| Test suite | Regression net across Phases 2–5 | 114 tests, **all PASS** in dry-run on host | COMPLETE (dry-run) / HARDWARE NOT VERIFIED | Hardware-in-the-loop tests | MEDIUM |
| Test discovery | `python -m unittest discover` | Fails: `tests/` not importable (no `__init__.py`) | PARTIAL | Add a runner entry point (**not in this audit**) | LOW |
| `test_i2c_speed.py` | Characterise real I²C throughput | 0 bytes | DESIGN ONLY / NOT IMPLEMENTED | Write it, run it on the Pi | MEDIUM |
| Dependency manifest | Reproducible install | `requirements.txt` missing `customtkinter` + `smbus2`; lists unused pygame / bless / numpy / RPi.GPIO | PARTIAL | Rewrite to match the real import graph | MEDIUM — fresh clone will not start |
| Provisioning scripts | Pi venv + system packages | `scripts/*.sh` present, executable | SOFTWARE COMPLETE / HARDWARE NOT VERIFIED | Execute on the Pi | LOW |
| `hw/adc_reader.py` | Legacy single-channel ADC | Self-declared DEPRECATED at line 2 | OBSOLETE / SUPERSEDED | Remove or archive | LOW |
| `core/digital_filters.py` | ESP32 filter port | Zero importers | OBSOLETE / SUPERSEDED | Remove, or retain deliberately for Phase 6 | LOW |
| `core/param_controller.py` | ESP32 param controller port | Zero importers | OBSOLETE / SUPERSEDED | Remove or archive | LOW |
| `ui/sliders.py` | pygame slider UI | Outside the import path | OBSOLETE / SUPERSEDED | Remove or archive | LOW |
| `hw/button_handler.py` | Physical-button UI | Outside the import path | OBSOLETE / SUPERSEDED | Remove or archive | LOW |
| `comm/ble_server.py` | BLE parameter control | Outside the import path | OBSOLETE / SUPERSEDED | Decide: revive or archive | LOW |
| `.pio/` ESP32-S3 tree | — | `libdeps/` only; tracked in git; no active importer | OBSOLETE / SUPERSEDED (historical; contents UNKNOWN) | Decide: archive or gitignore | LOW |
| Hardware validation overall | Real Pi + HAT + DACs + OPT101s | `PRE_PHASE_06_...REPORT.md` §0 ran on a laptop; §9 steps 10–16 NOT RUN / BLOCKED | BLOCKED | Physical access to the Pi and the dark chamber | HIGH — blocks every remaining phase |
| Phase-document consistency | Docs match verified hardware | ~13 docs say A1 = Red; ~30 say 3.2 V; several assert a shared optical cavity | OBSOLETE / SUPERSEDED | Correct forward-looking docs; annotate historical reports | HIGH — Phase 6 spec is itself wrong |

---

## 9. Contradiction register

Format per the prompt: exact file path → conflicting statement → authoritative replacement →
recommended action.

### C-01 — DAC full-scale constant

- **File:** `config.py:107-115`
- **Conflicting:** `DAC_FULLSCALE_V = 3.2`, with the comment "The measured full-scale on this
  hardware is 3.2 V `[VERIFIED-USER]`".
- **Authoritative:** `00_BASE_CONTEXT.md` F-10 — **MCP4725 full-scale = 3.28 V** `[VERIFIED-USER]`.
  The `[VERIFIED-USER]` attribution on 3.2 is false.
- **Action:** **CORRECT** — after explicit approval, and only as a coordinated change across
  `config.py`, `calibration.py`, `models/ppg_model.py`, `core/signal_engine.py`,
  `ui/frames/calibration_frame.py` **and** the locking assertions in `tests/test_phase4_dac.py:107`
  and `tests/test_calibration.py:137,149`. Re-measure on hardware first `[MEASUREMENT-REQUIRED]`.
  **`ADC_VOLTAGE_REF = 3.3` must not be touched.**

### C-02 — Full-scale propagated into the calibration SSOT

- **File:** `calibration.py:15-17` (and `dac_voltage_to_code()`, `validate_ac_dc()` defaults)
- **Conflicting:** 3.2 V full-scale used as the default conversion basis.
- **Authoritative:** 3.28 V.
- **Action:** **CORRECT** (with C-01, same change set).

### C-03 — Full-scale hard-locked by tests

- **Files:** `tests/test_phase4_dac.py:107` (`assertEqual(config.DAC_FULLSCALE_V, 3.2)`);
  `tests/test_calibration.py:137` (`assertEqual(DAC_FULLSCALE_MV, 3200.0)`), `:149`
  (`int((0.625/3.2)*4095)`)
- **Conflicting:** 3.2 / 3200.0 asserted as ground truth.
- **Authoritative:** 3.28 V / 3280.0 mV.
- **Action:** **CORRECT** — but only in the same approved change set as C-01. Changing tests alone,
  or code alone, produces a red suite. `assertNotEqual(DAC_FULLSCALE_V, ADC_VOLTAGE_REF)` at
  `test_phase4_dac.py:113` must be retained.

### C-04 — Full-scale in the architecture source of truth

- **File:** `docs/claude_phases/00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md:13`
- **Conflicting:** "**Measured DAC full-scale = 3.2 V.**"
- **Authoritative:** 3.28 V.
- **Action:** **SUPERSEDE** — this is a forward-looking authority document; it must be updated to
  3.28 V with a note that 3.2 V was the earlier assumed value.

### C-05 — Full-scale in the Phase 1 master design

- **File:** `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md:130`
- **Conflicting:** "Measured DAC full-scale = 3.2 V (user-confirmed)".
- **Authoritative:** 3.28 V.
- **Action:** **ANNOTATE** — this is a historical design record; add a superseded-by note rather than
  rewriting history.

### C-06 — Shared optical cavity and Red↔IR crosstalk

- **File:** `docs/phase_reports/PHASE_05_COMPLETION_REPORT.md:108`
- **Conflicting:** "Both OPT101s share the optical cavity with both LEDs, and the TX design drives IR
  and Red **simultaneously** … A0 = IR signal + Red leakage, A2 = Red signal + IR leakage …
  Mitigations to evaluate in Phase 6+: physical baffling, or TDM LED drive."
- **Authoritative:** `00_BASE_CONTEXT.md` §4 + N-02 / N-03 / N-05 — two **fully isolated**
  compartments; no shared detector, no common cavity, no intentional Red/IR mixing.
- **Action:** **ANNOTATE** (preserve the report as history) **and SUPERSEDE** the Phase 6+ mitigation
  recommendation. **No crosstalk compensation and no TDM LED drive shall be implemented on this
  basis.**

### C-07 — Merged optical path in the architecture diagram

- **File:** `docs/claude_phases/00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md:45-52`
- **Conflicting:** the ASCII diagram merges both LEDs into a single `+--- optical ---+` node, then
  fans out to both OPT101s — i.e. it depicts a shared cavity.
- **Authoritative:** two independent, isolated optical paths.
- **Action:** **CORRECT** — this is a live authority document; the diagram must show two parallel,
  non-interacting chains.

### C-08 — Tissue / diffuser in the optical path

- **File:** `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md:366`
- **Conflicting:** `LEDopt -.->|"tissue/diffuser (TBD)"| PD`
- **Authoritative:** N-04 — **no tissue phantom.**
- **Action:** **ANNOTATE** (historical design exploration; mark as not-adopted).

### C-09 — Crosstalk / TDM / optical-fixture mitigations in Phase 1

- **File:** `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md:372, 488, 503`
- **Conflicting:** crosstalk mitigation, TDM LED drive and an optical fixture presented as design
  options.
- **Authoritative:** N-01 / N-02 / N-03 / N-05.
- **Action:** **ANNOTATE** as superseded by the verified two-compartment dark chamber.

### C-10 — Stale A1 = Red mapping in the Phase 4 architecture

- **File:** `docs/architecture/PHASE_4_DUAL_DAC_TX_AND_LED_DRIVER.md:26`
- **Conflicting:** "OPT101 IR → A0, OPT101 Red → A1, A2 obsolete".
- **Authoritative:** F-06 / F-07 — A0 = IR, **A2 = Red**, A1 unused.
- **Action:** **ANNOTATE** (historical) — the exact inversion of the truth; the annotation must be
  unmissable.

### C-11 — Stale A1 = Red mapping in the Phase 6 specification (highest operational risk)

- **File:** `docs/claude_phases/06_*.md:14, 26, 85, 105`
- **Conflicting:** A1 = Red.
- **Authoritative:** A2 = Red; A1 unused for OPT101.
- **Action:** **CORRECT** — this is the *next work to be executed*. Implementing Phase 6 from this
  document as written would read the wrong ADC channel and produce silently wrong data.

### C-12 — Stale A1 = Red mapping across remaining phase documents

- **Files:** `docs/claude_phases/04_*.md`, `05_*.md`, `07_*.md`, `08_*.md`, `09_*.md`, `10_*.md`,
  `00_README_ALL_PHASES.md`, `00_README_FROM_PHASE_4.md`, `RUN_PHASE_4_PROMPT.md`,
  `docs/phase_reports/PHASE_04_COMPLETION_REPORT.md:20,111`
- **Conflicting:** A1 = Red.
- **Authoritative:** A2 = Red.
- **Action:** **CORRECT** forward-looking phase prompts (07–10); **ANNOTATE** completed reports
  (04, 05) and preserve them historically.

### C-13 — WhaleTeq treated as physical provenance

- **Files:** `calibration.py:10-13, 31, 146`; `models/ppg_model.py:58`; `tests/test_calibration.py:43`
- **Conflicting:** "reproduce the WhaleTeq AECG100 default", "(Phase 1 §17/§18, WhaleTeq AECG100)"
- **Authoritative:** N-01 — no WhaleTeq optical fixture exists. WhaleTeq is a **functional
  behavioural reference only** (source of the A = 110 / B = 25 linear relation).
- **Action:** **ANNOTATE** — keep the citation (the coefficients genuinely come from there), reword
  so it cannot be read as describing this project's physical optics.

### C-14 — Non-approved evidence label

- **Files:** `calibration.py:13`; `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md`
  (pervasive)
- **Conflicting:** `[VERIFIED-PDF]`
- **Authoritative:** `00_BASE_CONTEXT.md` §6 defines nine labels; this is not one of them. The
  correct substitute is `[VERIFIED-DATASHEET]` for component data, or an explicit literature
  citation otherwise.
- **Action:** **CORRECT** in `calibration.py`; **ANNOTATE** the historical Phase 1 document.

### C-15 — Generated TX values presented as measurements

- **File:** `ui/frames/pathology_frame.py:239`
- **Conflicting:** `ac_ir_v = ...measured_peak - ...measured_valley` and a formula-derived `ac_red_v`
  are displayed as `IR: … mV | RED: … mV` with no indication that both are transmit-side synthesis.
- **Authoritative:** the project's own anti-fabrication rule (`CLAUDE.md`; `opt101_rx.py:27-30`) —
  raw sensor data, synthesised waveforms and estimated parameters must be clearly distinguished.
- **Action:** **CORRECT** — relabel as generated/TX and rename the `measured_*` model attributes.
  Mandatory **before** any measured-SpO₂ readout appears in the same UI.

### C-16 — `requirements.txt` does not match the real import graph

- **File:** `requirements.txt`
- **Conflicting:** lists `pygame>=2.5.0` (and `bless`, `numpy`, `RPi.GPIO`), omits `customtkinter`
  and `smbus2`.
- **Authoritative:** the active import graph — `ui/ctk_app.py` imports **customtkinter**; grove.py 0.6
  requires **smbus2**. Confirmed by `PRE_PHASE_06_ENVIRONMENT_SETUP_REPORT.md` §2 and §7.
- **Action:** **CORRECT** — regenerate from the real graph; a fresh clone currently cannot start.

### C-17 — Deprecated module still present

- **File:** `hw/adc_reader.py:2`
- **Conflicting:** the module exists while declaring itself unused.
- **Authoritative:** superseded by `hw/opt101_rx.py`.
- **Action:** **SUPERSEDE** — remove or move to an archive directory.

### C-18 — Orphaned ESP32 ports

- **Files:** `core/digital_filters.py`, `core/param_controller.py`
- **Conflicting:** present in the active package tree with **zero importers**.
- **Authoritative:** not part of the current architecture.
- **Action:** **SUPERSEDE** — archive, or make a deliberate decision to reuse `digital_filters.py`
  in Phase 6 rather than leaving it ambiguous.

### C-19 — Empty test file

- **File:** `test_i2c_speed.py` (repository root, 0 bytes)
- **Conflicting:** its name asserts a capability that does not exist.
- **Authoritative:** no I²C timing has been characterised `[MEASUREMENT-REQUIRED]`.
- **Action:** **CORRECT** later — write it and run it on the Pi, or remove the placeholder.
  **Not touched by this audit.**

### C-20 — ESP32-S3 lineage in current-architecture files

- **Files:** `config.py:7`; `README.md:18`
- **Conflicting:** "Port of the ESP32-S3 config.h to Python" / "Python port of the ESP32-S3 PPG
  Signal Simulator firmware".
- **Authoritative:** F-01 / F-02 — exactly one Raspberry Pi 4 and one Grove Base HAT; no MCU.
- **Action:** **ANNOTATE** — the provenance is true and worth keeping; add "historical origin;
  the current target is a single Raspberry Pi 4."

### C-21 — `.pio/` ESP32-S3 tree tracked in the repository

- **Path:** `.pio/libdeps/` (tracked; last touched in `b88df16`; absent from `.gitignore`)
- **Conflicting:** an ESP32-S3 PlatformIO dependency tree inside a single-Pi Python project.
- **Authoritative:** outside the authoritative architecture. Contents are `UNKNOWN` from current
  evidence (excluded from inspection); no active Python module imports from it.
- **Action:** **PRESERVE HISTORICALLY** — do not delete during the audit. A later decision may
  archive it or add it to `.gitignore`.

### C-22 — Legacy single-channel ADC constant

- **File:** `config.py:62` — `GROVE_ADC_CHANNEL = 0`
- **Conflicting:** implies a single ADC channel; the system uses two.
- **Authoritative:** `ADC_CHANNEL_IR = 0`, `ADC_CHANNEL_RED = 2`.
- **Action:** **ANNOTATE** — the file already flags it as legacy-only; make removal conditional on
  confirming no consumer remains.

---

## 10. Open unknowns and required measurements

| ID | Item | Label |
|---|---|---|
| U-01 | Actual MCP4725 output full-scale on this hardware (3.2 V vs 3.28 V) — never re-measured | `[MEASUREMENT-REQUIRED]` |
| U-02 | Provenance of the original 3.2 V figure | `[UNKNOWN]` |
| U-03 | Real Grove ADC LSB/scaling behaviour under grove.py 0.6 on the target Pi | `[MEASUREMENT-REQUIRED]` |
| U-04 | Achievable I²C throughput and jitter at 1 kHz dual-DAC write cadence | `[MEASUREMENT-REQUIRED]` |
| U-05 | OPT101 output range and DC operating point at 3.28 V supply, inside the dark chamber | `[MEASUREMENT-REQUIRED]` |
| U-06 | LED drive circuit values and LM358 stage behaviour at 5.00 V | `[MEASUREMENT-REQUIRED]` — deliberately **not** proposed in this audit |
| U-07 | Whether any file under `.pio/libdeps/` is still referenced anywhere | `[UNKNOWN]` |
| U-08 | Residual optical isolation between the two chamber compartments (expected excellent; unmeasured) | `[MEASUREMENT-REQUIRED]` |

---

## 11. Interpretation guard

Per `00_BASE_CONTEXT.md` §4.3 `[ENGINEERING-INFERENCE]`, restated because it constrains everything
downstream:

- This system is a **loop-back electro-optical channel**, not a physiological measurement. There is
  no tissue and no blood.
- Any "SpO₂" produced by the future measured path is a **signal-path reproduction metric**, not a
  physiological oxygen saturation.
- Any measured **R** characterises **electro-optical channel transfer**, not haemoglobin absorption.
- Nothing in this project is clinical-grade, and no output may be described as such.

---

## 12. Stop

The audit is complete. As instructed:

- No circuit values have been proposed.
- No implementation source, test, phase document, schematic, PCB file, configuration file or
  historical report has been modified.
- No git state was altered.
- Prompt 02 has **not** been started.

**STOP.**

---

## 13. Post-audit addendum — change set C-01…C-04 executed 2026-07-29

This audit was written as a read-only, point-in-time record and its body is left
unmodified. This addendum records that the coordinated change set it specified
has since been applied, and where its recommendations were superseded.

### 13.1 What changed

`C-01`, `C-02`, `C-03` and `C-04` were executed under TDD. The three-way
3.28 / 3.2 / 3.3 V split documented in §5.2 is resolved: `config.py` now holds
`DAC_FULLSCALE_V = 3.28`, `DAC_FULLSCALE_MV = 3280.0`, `ADC_VOLTAGE_REF = 3.28`,
`GROVE_ADC_ADDR = 0x08`. Full detail — including the corrected supporting text,
the recomputed `signal_engine` code examples, and before/after test counts — is
in `00_BASE_CONTEXT.md` §9.

§5.2's observation that *"a repository-wide grep found zero occurrences of 3.28
anywhere in code, tests or documentation"* is now obsolete.

### 13.2 Where this audit was superseded

§5.2, §6 item 9, C-01 and C-03 required that
`assertNotEqual(DAC_FULLSCALE_V, ADC_VOLTAGE_REF)` survive the correction and
that `ADC_VOLTAGE_REF = 3.3` "must not be touched." That recommendation was made
before the user confirmed **F-15: Grove ADC full-scale/reference = 3.28 V**.

Under `00_BASE_CONTEXT.md` §3, user-confirmed facts supersede code, documents
and prior audit conclusions, so F-15 overrides this audit on that point. The two
constants are now numerically equal and the inequality assertion is
unsatisfiable. The guard's *intent* — that the TX full-scale and the RX
reference must never be merged — is preserved by two structural tests described
in `00_BASE_CONTEXT.md` §9.3.

### 13.3 What remains true

§4.6 (test discovery is broken — `tests/` has no `__init__.py`; the working
invocation is `PPG_DRY_RUN=1 .venv/bin/python tests/<file>.py`) and §6's list of
completed work that must not be redone remain accurate, except for item 9 as
qualified in §13.2 above.
