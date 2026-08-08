# 00 — BASE CONTEXT (Authoritative Ground Truth)

**Document status:** Base context only. **No audit has been performed in this document.**
**Created:** 2026-07-29
**Repository:** `/home/huynn/final_project/PPG_simulator_raspi`
**Branch at creation:** `huynn` (HEAD `7b29689`)

---

## 1. Purpose and Scope

This document freezes the **authoritative, user-confirmed hardware and optical
facts** for the PPG simulator project, and defines the **evidence labelling
system** that every later document in `docs/superpowers/ppg_design_audit/` must
use.

This document is the **single source of truth for hardware facts**. Where any
source file, phase document, completion report, schematic note, datasheet
extract, or prior Claude-generated document contradicts Section 3 or Section 4
of this file, **this file wins** and the contradiction must be recorded as a
finding in the later audit — not silently reconciled.

### Explicit non-goals of this document

- No audit, no gap analysis, no defect list.
- No design specification, no recommended architecture.
- No changes to implementation source code, schematics, PCB files, or phase
  documents. Those remain frozen until the user explicitly approves a final
  design specification.

---

## 2. Working Constraints (process)

1. Work is confined to `/home/huynn/final_project/PPG_simulator_raspi`.
2. Implementation source code, schematics, PCB files, and phase documents are
   **read-only** until the user explicitly approves the final design
   specification.
3. New artefacts are written only under
   `docs/superpowers/ppg_design_audit/`.
4. Every technical claim in later documents carries exactly one evidence label
   from Section 6.

---

## 3. Authoritative User-Confirmed Facts

All facts in this section are `[VERIFIED-USER]`. They were stated directly by
the user and are treated as ground truth. They are **not** derived from code,
schematics, or datasheets, and must not be "corrected" by them.

### 3.1 Compute and expansion

| # | Fact | Label |
|---|------|-------|
| F-01 | Exactly **one Raspberry Pi 4**. | `[VERIFIED-USER]` |
| F-02 | Exactly **one Grove Base HAT**. | `[VERIFIED-USER]` |

### 3.2 Transmit path (DAC → LED drive)

| # | Fact | Label |
|---|------|-------|
| F-03 | **MCP4725 @ I²C address 0x60 = IR TX** (drives the IR channel). | `[VERIFIED-USER]` |
| F-04 | **MCP4725 @ I²C address 0x61 = Red TX** (drives the Red channel). | `[VERIFIED-USER]` |

### 3.3 Receive path (photodiode → Grove ADC)

| # | Fact | Label |
|---|------|-------|
| F-05 | **OPT101 IR → Grove ADC channel A0.** | `[VERIFIED-USER]` |
| F-06 | **OPT101 Red → Grove ADC channel A2.** | `[VERIFIED-USER]` |
| F-07 | **A1 is NOT used for OPT101.** Any code, doc, or diagram that reads OPT101 on A1 is wrong. | `[VERIFIED-USER]` |
| F-13 | **Grove Base HAT MCU = MM32** (not the STM32 revision of the same board). | `[VERIFIED-USER]` |
| F-14 | **Grove Base HAT ADC I²C address = 0x08.** Corroborated by `grove_base_hat.pdf` p.3: *"the IIC address of MM32 is 0x08, while the STM32 is 0x04."* | `[VERIFIED-USER]` + `[VERIFIED-DATASHEET]` |

### 3.4 Supplies and full-scale references

| # | Fact | Value | Label |
|---|------|-------|-------|
| F-08 | OPT101 supply | **3.28 V** | `[VERIFIED-USER]` |
| F-09 | MCP4725 supply | **3.28 V** | `[VERIFIED-USER]` |
| F-10 | MCP4725 full-scale output (V<sub>FS</sub> = V<sub>DD</sub>) | **3.28 V** | `[VERIFIED-USER]` |
| F-11 | LM358 supply | **5.00 V** | `[VERIFIED-USER]` |
| F-12 | Grounding | **All modules share a common ground.** | `[VERIFIED-USER]` |
| F-15 | Grove ADC full-scale / reference used by this project | **3.28 V** | `[VERIFIED-USER]` |
| F-16 | Grove ADC resolution | **12 bits** (0…4095) | `[VERIFIED-USER]` + `[VERIFIED-DATASHEET]` |
| F-17 | LM358 installed device | **LM358P — standard/classic variant, PDIP package.** Use the classic LM358 specification table only; do **not** apply LM358B / LM358BA offset, output-swing, GBW or slew-rate numbers to this part. | `[VERIFIED-USER]` |

> **F-10 vs F-15 — numeric coincidence, not identity.** The MCP4725 TX
> full-scale (F-10) and the Grove ADC RX reference (F-15) both hold 3.28 V on
> this build, but they are independent physical quantities set by different
> devices. Code must keep them as two separate named constants
> (`config.DAC_FULLSCALE_V` and `config.ADC_VOLTAGE_REF`); neither may be
> defined in terms of the other, so that a future measurement can move one
> without silently moving the other. Enforced by
> `tests/test_phase4_dac.py::test_dac_and_adc_constants_stay_independent_symbols`
> and `tests/test_phase5_rx.py::test_raw_to_millivolts_tracks_adc_reference_not_dac_fullscale`.

> Note for later phases: F-08/F-10 vs F-11 means the OPT101/MCP4725 domain
> (3.28 V) and the LM358 domain (5.00 V) are **different rails**. Any
> level/headroom/clipping reasoning in the later audit must respect this and
> must be labelled `[CALCULATED]` or `[ENGINEERING-INFERENCE]`, never
> `[VERIFIED-USER]`.

---

## 4. Real Optical Architecture (Authoritative)

`[VERIFIED-USER]`

The optical front end is a **dark chamber containing two fully isolated
compartments**. Each compartment is an independent, single-wavelength optical
path with its own dedicated emitter and its own dedicated detector.

```
                    ┌──────────────── DARK CHAMBER ────────────────┐
                    │                                              │
  MCP4725 0x60 ───► │  ┌── IR COMPARTMENT (optically isolated) ──┐ │
  (IR TX)           │  │   IR LED  ──► dedicated IR OPT101       │ │ ──► Grove ADC A0
                    │  └─────────────────────────────────────────┘ │
                    │                                              │
  MCP4725 0x61 ───► │  ┌── RED COMPARTMENT (optically isolated) ─┐ │
  (Red TX)          │  │   Red LED ──► dedicated Red OPT101      │ │ ──► Grove ADC A2
                    │  └─────────────────────────────────────────┘ │
                    │                                              │
                    └──────────────────────────────────────────────┘
```

### 4.1 Per-channel chain

- **IR chain:** MCP4725 @ 0x60 → (LED drive stage) → IR LED → IR compartment →
  **dedicated IR OPT101** → Grove ADC **A0**.
- **Red chain:** MCP4725 @ 0x61 → (LED drive stage) → Red LED → Red compartment
  → **dedicated Red OPT101** → Grove ADC **A2**.

The LED drive stage (LM358 @ 5.00 V, 2SC1815 transistor, sense resistors) is
present in the parts list but its exact topology per channel is **not** asserted
here — see Section 5.4 and label `[UNKNOWN]` / `[VERIFIED-SCHEMATIC]` in later
phases.

### 4.2 What explicitly does NOT exist

These are authoritative negative facts. Later documents must not assume,
reintroduce, or "restore" any of them:

| # | Does NOT exist | Label |
|---|----------------|-------|
| N-01 | **No WhaleTeq optical fixture** in the signal path. | `[VERIFIED-USER]` |
| N-02 | **No shared detector.** Each wavelength has its own dedicated OPT101. | `[VERIFIED-USER]` |
| N-03 | **No common optical cavity.** The two compartments are fully isolated. | `[VERIFIED-USER]` |
| N-04 | **No tissue phantom.** | `[VERIFIED-USER]` |
| N-05 | **No intentional Red/IR optical mixing / crosstalk by design.** | `[VERIFIED-USER]` |

### 4.3 Direct consequences to carry into every later phase

These are `[ENGINEERING-INFERENCE]` drawn strictly from Section 4, recorded here
so later phases do not silently re-derive them differently:

- Red and IR are **two independent single-wavelength optical links**, not a
  two-wavelength measurement through a shared medium.
- Time-division multiplexing of the LEDs is **not required for optical
  separation** (it may still be desirable for other reasons — power, EMI,
  ADC scheduling — but that is a separate argument that must be made
  explicitly).
- Any measured "SpO₂" recovered from this rig is a **loop-back / signal-path
  reproduction metric**, not a physiological or clinical measurement. There is
  no tissue, no scattering medium, and no absorber whose oxygenation is being
  probed. `[ENGINEERING-INFERENCE]`
- Any R-ratio computed on this rig characterises **electro-optical channel
  transfer**, not haemoglobin absorption. `[ENGINEERING-INFERENCE]`

> The presence of WhaleTeq documents in `docs/whale_device/` is a
> **documentation artefact only** (reference material). It is *not* evidence of
> a WhaleTeq fixture in the signal path. Later phases must treat any code or doc
> that models a WhaleTeq fixture, shared cavity, or phantom as a **finding**.

---

## 5. Inspection Map — What Later Prompts Must Read

Paths are repo-relative. `.venv/`, `venv/`, `.pio/`, `__pycache__/`, and
`.codegraph/` are **excluded** from audit scope (build/dependency artefacts).

### 5.1 Top-level Python (highest priority — hardware contract lives here)

| File | Lines | Why it matters |
|------|------:|----------------|
| `config.py` | 239 | Expected home of I²C addresses, ADC channel map, voltage constants, sample rates. Primary place to check F-03…F-12. |
| `config_store.py` | 181 | Runtime persistence of configuration; check whether it can override hardware constants. |
| `config.json` | — | Live runtime parameter set (HR, SpO₂, PI, resp rate, noise, amplification, dicrotic notch, condition). |
| `calibration.py` | 276 | R-ratio / SpO₂ calibration model. Must be checked against Section 4.3 (no tissue → calibration semantics). |
| `main.py` | 76 | Application entry point, wiring of TX/RX/UI/state machine. |

### 5.2 Hardware abstraction layer — `hw/`

| File | Lines | Why it matters |
|------|------:|----------------|
| `hw/dac_manager.py` | 130 | MCP4725 driver/manager. **Verify 0x60=IR, 0x61=Red (F-03, F-04) and full-scale 3.28 V (F-10).** |
| `hw/adc_reader.py` | 86 | Grove Base HAT ADC access. **Verify A0=IR, A2=Red, A1 unused (F-05, F-06, F-07).** |
| `hw/opt101_rx.py` | 366 | OPT101 receive path: sampling, timing, AC/DC extraction, buffering. Largest HW file; central to RX audit. |
| `hw/button_handler.py` | 123 | GPIO input handling; check for pin conflicts with Grove HAT. |

### 5.3 Signal chain and model — `core/`, `models/`

| File | Lines | Why it matters |
|------|------:|----------------|
| `models/ppg_model.py` | 811 | Largest file in the project. PPG waveform synthesis, AC/DC, PI, Red/IR relationship. Primary TX-side model. |
| `core/signal_engine.py` | 304 | Sample generation / streaming engine; timing and rate feasibility. |
| `core/digital_filters.py` | 139 | Filter definitions; bandwidth vs sample rate must be checked. |
| `core/param_controller.py` | 79 | Parameter application path from UI/config to model. |
| `core/state_machine.py` | 113 | Run/idle/record/playback states; peripheral ownership. |
| `core/csv_logger.py` | 84 | Data logging format and timestamp integrity. |

### 5.4 Hardware reference documents — `docs/ds_linhkien/`

| File | Why it matters |
|------|----------------|
| `opt101.pdf` | OPT101 responsivity, internal 1 MΩ feedback, bandwidth, supply/output swing limits at 3.28 V. Source for `[VERIFIED-DATASHEET]`. |
| `grove_base_hat.pdf` | Grove Base HAT ADC (STM32-based), channel mapping, I²C address, ADC reference and resolution. |
| `lm358ba.pdf` | LM358 at 5.00 V: output swing, input common-mode range, GBW. |
| `2SC1815L-GR.PDF` | LED drive transistor characteristics. |
| `IR_led_3.3mm_datasheet.pdf` | IR LED wavelength, If/Vf, radiant intensity. |
| `red_led_3.3mm_datasheet.pdf` | Red LED wavelength, If/Vf, luminous/radiant intensity. |
| `MCP4725_schematic.png` | **Only schematic-class artefact currently located in the repo.** Source for `[VERIFIED-SCHEMATIC]`. Coverage of the LED driver and OPT101 front end is *not yet confirmed*. |
| `raspberry-pi-4-datasheet.pdf` | Pi 4 I²C/GPIO electrical limits. |

> Gap flagged now, not audited now: no schematic file for the **LED driver
> stage** or the **OPT101 front end** has been located in the repository. Unless
> one is supplied, statements about those stages can be at most
> `[ENGINEERING-INFERENCE]` or `[MEASUREMENT-REQUIRED]`. `[UNKNOWN]`

### 5.5 Prior design/phase documentation (read for contradictions — do not edit)

| Path | Why it matters |
|------|----------------|
| `docs/claude_phases/00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md` | Prior "source of truth" claim. **Must be diffed against Sections 3–4 of this file.** |
| `docs/claude_phases/00_README_ALL_PHASES.md`, `00_README_FROM_PHASE_4.md`, `00_README_PHASE_INDEX.md` | Phase indices and scope. |
| `docs/claude_phases/01…10_PHASE_*.md` | Ten phase specifications. Phases 02, 03, 04, 05, 06, 10 are the highest-risk for optical/calibration assumptions. |
| `docs/claude_phases/RUN_PHASE_4_PROMPT.md` | Prompt used to drive Phase 4. |
| `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md` | Earlier master design. |
| `docs/architecture/PHASE_4_DUAL_DAC_TX_AND_LED_DRIVER.md` | Dual-DAC TX + LED driver design; directly touches F-03/F-04. |
| `docs/phase_reports/PHASE_01…05_COMPLETION_REPORT.md` | Claimed-complete work. Check whether claims are evidence-backed or asserted. |
| `docs/phase_reports/PRE_PHASE_06_ENVIRONMENT_SETUP_REPORT.md` | Environment state before Phase 6. |
| `docs/whale_device/*.pdf` | **Reference material only.** Per N-01, no WhaleTeq fixture exists in the signal path. Any dependency on these in code/design is a finding. |
| `CLAUDE.md`, `README.md` | Project instructions and stated architecture. |

### 5.6 Tests

| File | Why it matters |
|------|----------------|
| `tests/test_calibration.py` | Encodes calibration assumptions. |
| `tests/test_phase3_acdc.py` | AC/DC/PI assumptions. |
| `tests/test_phase4_dac.py` | **Likely encodes the 0x60/0x61 mapping — direct check of F-03/F-04.** |
| `tests/test_phase5_rx.py` | **Likely encodes the ADC channel mapping — direct check of F-05/F-06/F-07.** |
| `test_sin_dac.py` (repo root) | Ad-hoc DAC test outside `tests/`. |
| `test_i2c_speed.py` (repo root) | **Empty (0 bytes).** |

### 5.7 UI, comms, tooling (lower priority, still in scope)

| Path | Why it matters |
|------|----------------|
| `ui/ctk_app.py`, `ui/sliders.py`, `ui/frames/*.py` | Parameter entry ranges and units; source of invalid-input risk. `ui/frames/pathology_frame.py` touches channel/parameter naming. |
| `comm/ble_server.py`, `comm/logger.py` | BLE service/characteristic definitions; per project rules these must be real, not invented. |
| `scripts/setup_rpi_venv.sh`, `scripts/install_rpi_system_packages.sh` | Deployment/runtime environment on the Pi. |
| `requirements.txt` | Dependency set (must be checkable against Pi 4 / Python 3.12). |
| `dataset/data_1.csv`, `dataset/data_2.csv`, `data.csv` (0 bytes), `plot_ppg_from_data.py` | Captured/plotted data; possible measurement evidence source. |
| `ppg_parameter_analysis_v1_2_0.html` | Prior analysis output. |

### 5.8 Excluded from audit scope

`.venv/`, `venv/`, `.pio/` (ESP32-S3 PlatformIO build tree and vendored
libraries), `**/__pycache__/`, `.codegraph/`, `.vscode/`.

> Note: the `.pio/` tree targets an **ESP32-S3**, which is not part of the
> hardware set confirmed in Section 3 (one Pi 4 + one Grove Base HAT). Whether
> this is dead history or a live second target is **not asserted here** and
> must be resolved in the audit. `[UNKNOWN]`

---

## 6. Evidence Labels (mandatory in all later documents)

Every technical claim in `docs/superpowers/ppg_design_audit/` must carry exactly
one of these labels. Labels do not compose; if a claim mixes sources, split it
into separate claims.

| Label | Meaning | Required backing |
|-------|---------|------------------|
| `[VERIFIED-USER]` | Stated directly by the user and accepted as ground truth. | Quote or reference to the user statement (Sections 3–4 of this file). |
| `[VERIFIED-DATASHEET]` | Taken from an official component datasheet. | Filename **and** page/section/parameter name. |
| `[VERIFIED-SCHEMATIC]` | Taken from an actual schematic or PCB artefact in the repository. | Filename **and** the specific net/designator. |
| `[VERIFIED-CODE]` | Read directly from source in this repository. | `path/file.py:line` and the relevant symbol. |
| `[CALCULATED]` | Numerically derived from labelled inputs. | The formula, every input with its own label, and the result with units. |
| `[ENGINEERING-INFERENCE]` | Reasoned conclusion that is not directly verifiable from the above. | The premises (each labelled) and the reasoning step. Must be visibly distinguished from fact. |
| `[RECOMMENDED STARTING VALUE]` | A proposed initial value to be tuned, not a validated design value. | Rationale, expected valid range, and what measurement would confirm or refute it. |
| `[MEASUREMENT-REQUIRED]` | Cannot be resolved without physical measurement on the actual hardware. | The exact instrument, test point, stimulus, and pass/fail criterion. |
| `[UNKNOWN]` | Not determinable from any currently available evidence. | What is missing and what would resolve it. |

### 6.1 Labelling rules

1. **Never upgrade a label.** An `[ENGINEERING-INFERENCE]` does not become
   `[VERIFIED-*]` because it appears in a later document or because it "seems
   right".
2. **Never fabricate.** No invented measurements, timings, accuracies, latencies,
   memory figures, build results, or hardware test outcomes. If it was not run,
   it is `[MEASUREMENT-REQUIRED]` or `[UNKNOWN]`.
3. **A `[CALCULATED]` value inherits the weakest label among its inputs.** A
   calculation fed by an `[ENGINEERING-INFERENCE]` cannot be presented as a
   verified figure.
4. **Simulation ≠ validation.** Keep these separate and never collapse them:
   simulation accuracy, signal reproduction accuracy, physiological parameter
   estimation accuracy, engineering validation, research validation, clinical
   validation.
5. **Contradictions are findings, not edits.** Where code or a prior document
   conflicts with Sections 3–4, record the conflict with both labels
   (`[VERIFIED-USER]` vs `[VERIFIED-CODE]`) — do not modify the code or the
   prior document.

---

## 7. Open Items Deliberately Not Resolved Here

Recorded so later phases pick them up rather than re-discover them. All are
`[UNKNOWN]` at this point and **none has been investigated**:

1. LED driver topology per channel (LM358 @ 5.00 V + 2SC1815): no schematic
   located.
2. OPT101 front-end topology: no schematic located; internal 1 MΩ vs external
   feedback not established.
3. ~~Grove Base HAT ADC reference voltage and effective resolution/rate~~
   **RESOLVED 2026-07-29:** reference = 3.28 V (F-15), resolution = 12 bits
   (F-16), I²C address = 0x08 / MM32 (F-13, F-14). Effective sample *rate*
   remains `[MEASUREMENT-REQUIRED]`.
4. Whether the 3.28 V (OPT101/MCP4725) and 5.00 V (LM358) rails interface
   safely at every boundary.
5. Role of the `.pio/` ESP32-S3 build tree relative to the confirmed one-Pi-4
   hardware set.
6. ~~Whether `config.py` / `config_store.py` actually encode F-03 … F-12~~
   **RESOLVED 2026-07-29:** audited in `01_CURRENT_SYSTEM_AUDIT.md`, then
   corrected under TDD — `config.py` now encodes F-03…F-17 (`DAC_FULLSCALE_V =
   3.28`, `DAC_FULLSCALE_MV = 3280.0`, `ADC_VOLTAGE_REF = 3.28`,
   `GROVE_ADC_ADDR = 0x08`). `config_store.py` holds no hardware constants.
   See §9 below.

---

## 8. Next Step

Await the next prompt in this series. **No audit, no design specification, and
no code, schematic, PCB, or phase-document modification** is to be performed
until the user explicitly approves the final design specification.

---

## 9. Stage A Constant Correction — Applied 2026-07-29

Executed under TDD (RED → GREEN) against the authoritative facts in §3.

### 9.1 Constants corrected in `config.py`

| Constant | Was | Now | Fact |
|---|---|---|---|
| `DAC_FULLSCALE_V` | `3.2` | `3.28` | F-09 / F-10 |
| `DAC_FULLSCALE_MV` | `3200.0` (derived) | `3280.0` (derived) | F-10 |
| `ADC_VOLTAGE_REF` | `3.3` | `3.28` | F-15 |
| `GROVE_ADC_ADDR` | `0x04` | `0x08` | F-13 / F-14 |

Derived values that followed automatically: `DAC_VOLTAGE_MAX = 3.28`,
`DAC_V_PER_STEP = 3.28 / 4096 = 0.00080078125 V`.

`DAC_ADDR_IR = 0x60`, `DAC_ADDR_RED = 0x61`, `ADC_CHANNEL_IR = 0`,
`ADC_CHANNEL_RED = 2`, `ADC_MAX_VALUE = 4095` were already correct and were
**not** changed.

### 9.2 Supporting text corrected (no behavioural change)

`calibration.py`, `hw/opt101_rx.py`, `core/signal_engine.py`,
`models/ppg_model.py`, `ui/frames/calibration_frame.py`, `main.py`,
`plot_ppg_from_data.py`, `test_sin_dac.py`, plus MM32/0x08 identification where
the text still said STM32/0x04. `calibration.py`'s non-approved
`[VERIFIED-PDF]` label was replaced with `[VERIFIED-DATASHEET]`.

`core/signal_engine.py` DAC-code examples were recomputed at 3.28 V full-scale:
DC 1.5 V → 1872; PI 3 % → 1816–1928; PI 10 % → 1685–2059; PI 20 % → 1498–2247.

### 9.3 Test-guard conflict and its resolution

`01_CURRENT_SYSTEM_AUDIT.md` §5.2 / §6 item 9 / C-01 / C-03 required that
`assertNotEqual(DAC_FULLSCALE_V, ADC_VOLTAGE_REF)` (`test_phase4_dac.py:113`)
survive the correction, and that `ADC_VOLTAGE_REF = 3.3` "must not be touched."
F-15 supersedes that: the Grove ADC reference is 3.28 V, so the two constants
are now numerically equal and the inequality assertion is unsatisfiable.

Per §3 (user facts supersede) and §6.1 rule 5 (contradictions are findings),
the *intent* of the guard — the two quantities must never be merged — was
preserved by re-expressing it structurally instead of numerically:

- `test_phase4_dac.py::test_dac_and_adc_constants_stay_independent_symbols`
  parses `config.py` with `ast` and asserts each constant is its own numeric
  literal and that neither references the other.
- `test_phase5_rx.py::test_raw_to_millivolts_tracks_adc_reference_not_dac_fullscale`
  perturbs `hw.opt101_rx.ADC_VOLTAGE_REF` and asserts the RX conversion follows
  it — proving the RX path reads the ADC constant, not the DAC constant.

### 9.4 Verification evidence

`PPG_DRY_RUN=1 .venv/bin/python tests/<file>.py`, run per file:

| File | Before | After |
|---|---|---|
| `tests/test_calibration.py` | 26 OK | 26 OK |
| `tests/test_phase3_acdc.py` | 25 OK | 25 OK |
| `tests/test_phase4_dac.py` | 31 OK | 32 OK |
| `tests/test_phase5_rx.py` | 32 OK | 33 OK |
| **Total** | **114 pass / 0 fail** | **116 pass / 0 fail** |

Intermediate RED state (tests updated, `config.py` not yet corrected) produced
10 failures, each for the expected reason (constant still at its old value).
