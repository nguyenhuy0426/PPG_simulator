# Phase 4 — Unified Raspberry Pi / Grove Base HAT Dual-DAC TX and LED-Driver Integration

## Prerequisites

Before changing code, read:

- `docs/claude_phases/00_README_FROM_PHASE_4.md`
- `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md`
- `docs/phase_reports/PHASE_01_COMPLETION_REPORT.md`
- `docs/phase_reports/PHASE_02_COMPLETION_REPORT.md`
- `docs/phase_reports/PHASE_03_COMPLETION_REPORT.md`
- the current source code and current `git diff`.

Do not redo Phases 1–3.

## Verified hardware facts — do not treat these as unknown

- The entire simulator uses **one Raspberry Pi 4** and **one Seeed Grove Base HAT**.
- That same Raspberry Pi 4 and Grove Base HAT are responsible for TX, RX, processing, and UI.
- Raspberry Pi 4 communicates over I2C through the Grove Base HAT I2C path to both DAC modules.
- **MCP4725 `0x60` = IR TX.**
- **MCP4725 `0x61` = Red TX.**
- User-measured DAC full-scale = **3.2 V**.
- RX mapping is already confirmed for later phases: **A0 = OPT101 IR**, **A1 = OPT101 Red**.

Do not use the obsolete A2 mapping.

## Objective

Complete and verify the software/hardware architecture for the two MCP4725 transmit channels and define the practical Red/IR LED-driver stage while preserving the single-Raspberry-Pi, single-Grove-Base-HAT architecture.

Do not create a second controller, second HAT, second I2C subsystem, or separate TX computer.

## Preserve completed Phase 2–3 primitives

Do not rewrite or duplicate:

- `config.DAC_FULLSCALE_V = 3.2`
- `calibration.dac_voltage_to_code()`
- `calibration.spo2_from_r()`
- `calibration.r_target_from_spo2()`
- `calibration.perfusion_index_from_ac_dc()`
- `calibration.ratio_of_ratios()`
- `calibration.ac_red_from_target()`
- `calibration.validate_ac_dc()`
- independent Red/IR AC/DC model
- A/B persistence
- existing passing Phase 2 and Phase 3 tests.

## Unified TX architecture to preserve

```text
ONE Raspberry Pi 4
        |
        | generated IR/Red waveforms
        v
ONE Grove Base HAT / shared Raspberry Pi I2C path
        |
        +------------------------------+
        |                              |
        v                              v
MCP4725 0x60                      MCP4725 0x61
   IR TX                              Red TX
        |                              |
        v                              v
IR LED current-control stage     Red LED current-control stage
        |                              |
        v                              v
      IR LED                         Red LED
```

## Required software audit and implementation

Inspect the actual current implementation before changing anything:

- actual Linux I2C initialization path;
- actual MCP4725 library/API;
- current per-address initialization;
- actual call order and sequential-write behavior;
- thread ownership of the DAC path;
- current rate target and timing mechanism;
- dry-run behavior;
- shutdown behavior;
- exception handling.

Then make only the minimum required corrections.

### Mandatory channel mapping

Maintain exactly:

```text
0x60 -> IR
0x61 -> Red
```

Never silently swap channels. Do not leave comments or configuration that contradict this verified mapping.

## DAC conversion requirements

- Use the existing single source of truth `DAC_FULLSCALE_V = 3.2`.
- Use the existing centralized voltage-to-code conversion.
- Respect 12-bit code limits 0–4095.
- Do not reintroduce `/3.3`, `3300`, or duplicate `*4095` conversion formulas.
- Keep DAC and ADC reference values separate; do not change ADC scaling just because DAC full-scale is 3.2 V.

## Shared-bus / one-controller constraint

The same Raspberry Pi 4 and Grove Base HAT will later also acquire A0/A1 ADC data. Therefore Phase 4 must not create an architecture that monopolizes or duplicates the I2C path in a way that blocks Phase 5.

Analyze and document:

- current DAC write cadence;
- sequential writes to 0x60 then 0x61;
- likely shared-bus contention once ADC reads are added;
- need for one clear owner/serialization strategy for I2C access;
- Linux userspace scheduling and jitter as unverified until measured.

Do not claim timing success without measurement.

## LED-driver design

Do not directly assume the DAC can drive the LED as a final design.

Document the target concept:

```text
MCP4725 voltage command
        -> op-amp control stage
        -> transistor/MOSFET if required
        -> current-sense resistor
        -> LED
```

For LM358, analyze only from actual supply/circuit evidence available in the project:

- supply rails;
- input common-mode range;
- output swing;
- output current capability;
- bandwidth/slew limitations;
- headroom;
- saturation;
- stability/load concerns;
- whether an external transistor or MOSFET is required.

Do not invent:

- LED current rating;
- LED wavelength;
- LED forward voltage;
- resistor values;
- MOSFET/transistor part numbers;
- optical power;
- successful bench results.

If evidence is insufficient, explicitly state: `I am not sure based on the currently available evidence.`

## Validation plan

### Logic analyzer

Plan checkpoints for:

- ACK/NACK at `0x60` and `0x61`;
- payload bytes;
- actual update interval;
- timing gap between IR and Red writes;
- retries/errors if the real library supports them.

### Oscilloscope

Plan checkpoints for each DAC output separately:

- test point;
- ground reference;
- DC level;
- AC amplitude;
- pulse period;
- clipping at 0 V / 3.2 V;
- output settling;
- driver-stage saturation.

Do not fabricate measurements.

## Tests

Add or extend focused tests for:

- fixed channel mapping `0x60=IR`, `0x61=Red`;
- 3.2 V conversion boundaries;
- per-channel DAC output routing;
- dry-run status;
- disconnected DAC behavior where testable;
- shutdown safe-state behavior where testable without inventing hardware support.

Preserve all existing passing tests.

## Out of scope

Do not implement:

- OPT101 acquisition — Phase 5;
- measured AC/DC/R/SpO2 from receiver samples — Phase 6;
- major UI redesign — Phase 7.

## Required completion report

At the end create:

`docs/phase_reports/PHASE_04_COMPLETION_REPORT.md`

It must include:

- COMPLETE / PARTIAL / BLOCKED status;
- prerequisites read;
- exact tasks completed;
- files modified/created/deleted;
- confirmed mapping status `0x60=IR`, `0x61=Red`;
- actual DAC API and thread ownership found;
- shared-bus implications for the same Pi/HAT that will later read A0/A1;
- LED-driver findings and unknowns;
- commands actually executed;
- real test results as PASS/FAIL/NOT RUN/BLOCKED;
- hardware validation status;
- `git diff --stat`;
- acceptance checklist;
- do-not-redo handoff for Phase 5.

Then STOP. Do not start Phase 5.
