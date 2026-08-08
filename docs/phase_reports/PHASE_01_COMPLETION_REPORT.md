# Phase 1 Completion Report — Reference Audit and Master System Design

## Status

**Phase status:** COMPLETED FOR DESIGN/AUDIT SCOPE

**Source code modified:** No.

**Primary output created by Claude Code:**
`/home/huynn/final_project/PPG_simulator_raspi/docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md`

This report summarizes the evidence in the supplied Claude Code execution log. It does not claim that Phases 2–10 or any hardware validation have been completed.

## 1. Work completed

Claude Code:

- Read the Phase 1 instructions and phase index.
- Audited the active Python PPG simulator codebase while excluding unrelated trees such as `MedicalSimulator/`, `BioSignalSimulatorPro-main/`, virtual environments, and generated build artifacts from the main analysis.
- Read the three WhaleTeq AECG100 reference PDFs relevant to PPG/SpO2 behavior.
- Inspected the current runtime architecture, PPG model, signal engine, dual MCP4725 DAC path, deprecated ADC reader, CustomTkinter UI, configuration persistence, filters, state machine, CSV logger, BLE module, and requirements manifest.
- Produced a 561-line Phase 1 architecture/audit report with reference evidence, gap analysis, Mermaid diagrams, target architecture, data pipeline, TX/RX circuit concepts, risk register, BOM, test plan, and acceptance criteria.
- Stopped before Phase 2 as required.

## 2. Main verified findings from the current codebase

### 2.1 DAC full-scale mismatch

The code uses `3.3 V` in several places while the user-confirmed measured MCP4725 full-scale is `3.2 V`.

Reported locations include:

- `config.py`
- `core/signal_engine.py`
- `models/ppg_model.py`
- `ui/frames/calibration_frame.py`

This must be centralized into one source of truth in Phase 2.

### 2.2 SpO2 coefficients are hardcoded

Current code uses:

`SpO2 = 110 - 25 * R`

with `A=110` and `B=25` hardcoded in more than one location. The target architecture requires configurable A/B coefficients with default values `110.0` and `25.0`.

### 2.3 Current AC/DC/PI architecture does not match the target reference behavior

Current model behavior reported by Claude Code:

- PI is an input.
- IR AC is derived from PI using a fixed scale.
- Red AC is derived from IR AC and R.
- A single shared DC baseline is used.

Target behavior for later phases:

- AC and DC are master adjustable parameters in mV.
- PI is derived from `AC/DC`.
- Red and IR DC values can be independent.
- Full ratio-of-ratios is used:

`R = (AC_red/DC_red) / (AC_ir/DC_ir)`

### 2.4 No real OPT101 acquisition path exists yet

Verified project state at the time of Phase 1:

- Two OPT101 modules physically exist.
- Receiver channel 1 uses Grove Base Hat ADC `A0`.
- Receiver channel 2 uses Grove Base Hat ADC `A2`.
- No OPT101 acquisition implementation exists.
- Existing `hw/adc_reader.py` is deprecated and only covers a single older A0 use case.

### 2.5 UI and persistence are incomplete for the target architecture

The current project does not yet persist or expose all target values, including:

- configurable A/B,
- per-channel AC/DC in mV,
- RX configuration/status,
- measured SpO2,
- received Red/IR waveforms.

### 2.6 Current runtime timing architecture

Claude Code reported:

- PPG model generation: `100 Hz`.
- 10x interpolation.
- DAC update target: `1000 Hz`.
- GUI refresh: approximately `50 Hz`.

Actual Linux timing jitter and end-to-end hardware timing have not been measured yet.

## 3. Important reference-device findings

The Phase 1 report extracted relevant WhaleTeq AECG100 PPG/SpO2 behavior, including:

- configurable Red/IR AC and DC,
- PI derived from AC/DC,
- default linear SpO2 mapping `SpO2 = 110 - 25R`,
- adjustable intercept/slope,
- ratio-of-ratios calculation,
- respiration BM/AM/FM behavior,
- AC-above-DC / AC-below-DC,
- selectable noise behavior,
- PPG/PD sampling concepts,
- waveform display and playback,
- calibration and validation workflow.

## 4. Hardware baseline carried forward

Treat the following as user-confirmed facts:

- Raspberry Pi 4 running Ubuntu 24.04 LTS.
- Seeed Grove Base Hat for Raspberry Pi 4.
- Two MCP4725 modules at I2C addresses `0x60` and `0x61`.
- Measured MCP4725 full-scale output: `3.2 V`.
- LM358 available.
- 3 mm Red LED available.
- 3 mm IR LED available.
- Two OPT101 modules available.
- OPT101 receiver channel 1 uses `A0`.
- OPT101 receiver channel 2 uses `A2`.
- No OPT101 acquisition code existed at the start of refinement.

Still unverified:

- physical Red/IR mapping of `0x60` and `0x61`,
- physical Red/IR mapping of `A0` and `A2`,
- exact LED wavelengths and part numbers,
- exact LED forward current/voltage,
- LM358 and OPT101 actual supply rails in the assembled circuit,
- real Linux DAC timing jitter,
- real OPT101 saturation/crosstalk/ambient-light behavior.

## 5. Review notes and corrections before Phase 2

### 5.1 Phase 1 is good enough to proceed

The audit identified the correct major gaps and respected the no-code-change boundary. It is reasonable to proceed to Phase 2.

### 5.2 Do not treat the claimed 60–70% current match as a verified measurement

The Phase 1 report described the current transmit-side waveform generator as a rough `60–70%` match in waveform behavior. This is only an engineering estimate unless a formal feature weighting and validation method is applied. Do not use this number as a measured result.

### 5.3 Do not claim full PDF coverage beyond evidence

The supplied execution log shows the 93-page manual was read through the relevant sections and specification tables, but the log does not clearly demonstrate page-by-page coverage of every page through 93. This is not a blocker because the relevant PPG/SpO2 sections were covered, but later phases should avoid saying the entire manual was exhaustively read unless the actual tool history proves it.

### 5.4 Do not change ADC voltage reference to 3.2 V merely because DAC full-scale is 3.2 V

`DAC full-scale = 3.2 V` and `ADC reference/input scaling` are separate hardware facts. Phase 2 must correct DAC scaling only. ADC scaling remains subject to actual Grove Base Hat behavior and later verification.

## 6. Readiness for Phase 2

**Ready to proceed:** YES.

Phase 2 should focus only on:

1. Centralizing DAC full-scale `3.2 V`.
2. Removing duplicated `3.3 V` DAC scaling/clamping.
3. Adding configurable A/B defaults and validation.
4. Adding forward/inverse SpO2/R functions.
5. Persisting A/B with backward compatibility.
6. Fixing dependency manifest inconsistencies only if verified.
7. Adding narrow tests for Phase 2 behavior.
8. Creating `docs/phase_reports/PHASE_02_COMPLETION_REPORT.md` before stopping.

Do not start AC/DC/PI model redesign in Phase 2; that belongs to Phase 3.

## 7. Handoff rule

All later phases must read:

- `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md`
- every prior `docs/phase_reports/PHASE_XX_COMPLETION_REPORT.md`
- the current repository state

before making changes.

Do not redo completed work.
