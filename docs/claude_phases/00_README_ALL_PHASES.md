# PPG Simulator Claude Phase Bundle — Full Project-Ready Package

This bundle contains the historical completed Phase 1–3 instructions and reports plus the corrected Phase 4–10 instructions for the verified one-Raspberry-Pi / one-Grove-Base-HAT architecture.

## Current verified architecture

Read first:

`docs/claude_phases/00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md`

Current mapping:

```text
ONE Raspberry Pi 4
    -> ONE Seeed Grove Base HAT

TX:
  MCP4725 0x60 -> IR
  MCP4725 0x61 -> Red
  DAC full-scale -> 3.2 V

RX:
  OPT101 IR  -> Grove ADC A0
  OPT101 Red -> Grove ADC A1

The same Pi/HAT performs TX, RX, processing, and UI.
A2 is obsolete and must not be used.
```

## Phase status

```text
Phase 1 -> COMPLETE
Phase 2 -> COMPLETE
Phase 3 -> COMPLETE
Phase 4 -> NEXT TO RUN
Phase 5 -> NOT STARTED
Phase 6 -> NOT STARTED
Phase 7 -> NOT STARTED
Phase 8 -> NOT STARTED
Phase 9 -> NOT STARTED
Phase 10 -> NOT STARTED
```

## Keep Phase 1–3

Do not delete them. They preserve the audit trail, completed work, tests, formulas, source changes, and do-not-redo handoffs.

Phase 4 must read the Phase 1 architecture report and Phase 1–3 completion reports before changing code.

## Important precedence rule

Historical Phase 1–3 documents may contain older unknowns or obsolete receiver mapping. Current verified hardware truth takes precedence:

- `0x60=IR TX`
- `0x61=Red TX`
- `A0=IR RX`
- `A1=Red RX`
- `A2` is obsolete.

## Files

```text
docs/
├── architecture/
│   └── PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md
├── claude_phases/
│   ├── 00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md
│   ├── 00_README_ALL_PHASES.md
│   ├── 00_README_PHASE_INDEX.md
│   ├── 00_README_FROM_PHASE_4.md
│   ├── 01_PHASE_REFERENCE_AUDIT_AND_MASTER_DESIGN.md
│   ├── 02_PHASE_CONFIG_AND_SPO2_CALIBRATION.md
│   ├── 03_PHASE_AC_DC_PI_AND_RED_IR_MODEL.md
│   ├── 04_PHASE_DUAL_DAC_AND_LED_DRIVER_INTEGRATION.md
│   ├── 05_PHASE_OPT101_AND_GROVE_ADC_ACQUISITION.md
│   ├── 06_PHASE_SIGNAL_PROCESSING_AND_MEASURED_SPO2.md
│   ├── 07_PHASE_LINUX_UI_TX_RX_VISUALIZATION.md
│   ├── 08_PHASE_HARDWARE_DIAGNOSTICS_AND_RUNTIME_SAFETY.md
│   ├── 09_PHASE_TESTS_AND_VALIDATION.md
│   ├── 10_PHASE_CALIBRATION_DOCUMENTATION_AND_FINAL_ACCEPTANCE.md
│   └── RUN_PHASE_4_PROMPT.md
└── phase_reports/
    ├── PHASE_01_COMPLETION_REPORT.md
    ├── PHASE_02_COMPLETION_REPORT.md
    └── PHASE_03_COMPLETION_REPORT.md
```

## Next action

Run Phase 4 only. Do not automatically continue to Phase 5.
