# Phase 3 — AC/DC/PI and Red/IR SpO2 Waveform Model

## Prerequisite

Read the approved Phase 1 design and Phase 2 implementation report. Do not redo completed work.

## Objective

Make AC and DC master adjustable parameters, calculate PI from AC/DC, and implement correct Red/IR ratio-of-ratios behavior.

## Required behavior

Inputs:
- Heart rate.
- Respiratory rate.
- SpO2 target.
- A coefficient.
- B coefficient.
- AC amplitude in mV.
- DC level in mV.
- noise level.

Required calculations:

`PI_red = AC_red / DC_red * 100%`

`PI_ir = AC_ir / DC_ir * 100%`

`R_target = (A - SpO2_target) / B`

`R = (AC_red / DC_red) / (AC_ir / DC_ir)`

`AC_red = R_target * AC_ir * (DC_red / DC_ir)`

Only simplify when DC values are equal.

## Required model changes

- Remove the old behavior where AC is forced from PI by a fixed global scale, if present.
- Do not keep DC fixed unless explicitly selected by a preset.
- Keep PI as a derived value.
- Keep target SpO2 separate from measured SpO2.
- Add AC above DC and AC below DC behavior if approved in Phase 1.
- Keep waveform clipping bounded by the real configured DAC range.
- Preserve existing PPG morphology unless there is a documented defect.
- Preserve existing condition/pathology presets unless the Phase 1 report identifies a conflict.

## Respiration and noise

Preserve or refine existing:
- BM baseline modulation,
- AM amplitude modulation,
- FM/RSA timing modulation,
- noise generation.

Do not invent unverified physiology or calibration claims.

## Tests

Add tests for:
- AC/DC → PI.
- equal and unequal DC ratio-of-ratios.
- A/B changes.
- clipping.
- AC above/below DC.
- invalid combinations that produce non-physical or unsafe values.

## Deliverables

- Minimal code changes.
- Tests.
- Phase 3 report.
- Stop before hardware DAC changes.


## Confirmed output hardware context

- Two MCP4725 modules are available at `0x60` and `0x61`, so the software may target two independent Red/IR DAC output streams.
- Do not assume which address maps to Red or IR until verified from the current code and wiring.
- Use `3.2 V` as the confirmed DAC full-scale constraint when checking clipping.
