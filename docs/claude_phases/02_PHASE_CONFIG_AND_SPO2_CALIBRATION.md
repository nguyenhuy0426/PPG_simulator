# Phase 2 — Configuration Cleanup and SpO2 Calibration Model

## Prerequisite

Read and follow the approved Phase 1 report. Do not redo the Phase 1 audit. Inspect the current repository state and only implement work assigned to this phase.

## Objective

Centralize system constants and remove deep hardcoding for SpO2 calibration, units and DAC full-scale configuration.

## Required work

1. Add configurable SpO2 coefficients:
   - `A` default 110.0 unless Phase 1 defines another justified default.
   - `B` default 25.0 unless Phase 1 defines another justified default.
   - User-editable later through the UI.
   - Validate finite numeric values.
   - Reject `B <= 0`.

2. Implement clear functions for:
   - `SpO2 = A - B * R`
   - `R_target = (A - SpO2_target) / B`

3. Do not hardcode A/B in multiple files.

4. Centralize DAC full-scale/reference voltage into one source of truth.
   - Use the user-confirmed measured DAC full-scale voltage of `3.2 V` as the target source of truth; identify and remove any inconsistent `3.3 V` hardcoding.
   - Do not silently change hardware behavior without evidence.

5. Standardize units:
   - AC/DC user-facing units: mV.
   - Internal representation must be explicit and consistent.
   - Avoid silent V↔mV conversion.

6. Preserve backward compatibility with existing saved configuration where practical.

7. Add unit tests for:
   - forward SpO2 mapping,
   - inverse R mapping,
   - invalid B,
   - non-finite input,
   - DAC voltage-to-code boundaries,
   - unit conversion.

## Constraints

Do not yet redesign the full PPG waveform model, ADC path or UI. Keep this phase narrow.

Do not claim hardware validation without measurements.

## Deliverables

- Minimal code changes.
- Tests.
- Short Phase 2 report listing modified files, exact behavior changes and remaining gaps.
- Stop after Phase 2. Do not start Phase 3 automatically.


## Confirmed hardware constraints for this phase

- Two MCP4725 modules exist at `0x60` and `0x61`.
- Measured DAC full-scale is `3.2 V`.
- Centralize this value in one configuration constant and make all model clamping and voltage-to-code conversion use the same source of truth.
