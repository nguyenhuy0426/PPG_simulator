# Phase 9 — End-to-End Tests and Engineering Validation for the Single Raspberry Pi PPG Simulator

## Prerequisites

Read the Phase 1 architecture report, Phase 1–8 completion reports, final source state, and current `git diff`.

Do not rewrite completed implementation merely to make testing easier unless a real architectural defect is found and documented.

## Verified final architecture baseline

Exactly one Raspberry Pi 4 and one Grove Base HAT perform all of the following:

```text
PPG generation
-> MCP4725 0x60 IR + MCP4725 0x61 Red
-> LED-driver stages
-> IR/Red optical emission
-> OPT101 IR on A0 + OPT101 Red on A1
-> acquisition
-> filtering
-> AC/DC extraction
-> PI
-> ratio-of-ratios R
-> measured SpO2
-> same Linux UI showing TX and RX
```

## Objective

Build an evidence-based software and hardware validation matrix from the lowest layer upward.

## Software tests

At minimum cover:

- A/B validation;
- SpO2 forward/inverse mapping;
- AC/DC/PI;
- equal and unequal DC ratio-of-ratios;
- Red amplitude derivation;
- waveform bounds;
- 3.2 V DAC conversion;
- `0x60=IR`, `0x61=Red` routing;
- `A0=IR`, `A1=Red` acquisition mapping;
- shared-bus ownership/serialization where applicable;
- buffering;
- timestamps;
- filtering;
- AC extraction;
- DC extraction;
- measured R;
- measured SpO2;
- clipping/saturation detection;
- stale data;
- missing hardware;
- dry-run labeling;
- UI state without fabricated measurement.

## Hardware validation hierarchy

Validate in this exact evidence order:

1. Raspberry Pi 4 power/ground.
2. Grove Base HAT presence and common ground.
3. Shared I2C bus visibility.
4. MCP4725 `0x60` IR address and command.
5. MCP4725 `0x61` Red address and command.
6. IR DAC output voltage.
7. Red DAC output voltage.
8. IR LED-driver stage.
9. Red LED-driver stage.
10. IR LED current.
11. Red LED current.
12. Optical output/geometry.
13. OPT101 IR analog output into A0.
14. OPT101 Red analog output into A1.
15. Grove ADC acquisition.
16. Timestamps/buffering.
17. Filtering.
18. AC/DC extraction.
19. PI.
20. ratio-of-ratios R.
21. measured SpO2.
22. Linux UI TX/RX display.

Do not skip lower-layer failures by changing higher-layer software randomly.

## Result labeling

Every test must be explicitly labeled:

- PASS — verified by actual execution/measurement;
- FAIL — verified failure;
- NOT RUN;
- BLOCKED by missing hardware/evidence.

Do not convert an inference into PASS.

## Functional similarity matrix against AECG100 PPG/SpO2 scope

Build a feature-by-feature matrix including at least:

- HR control;
- RR control;
- target SpO2;
- A/B coefficients;
- Red/IR AC/DC;
- PI;
- Red/IR dual TX;
- selectable polarity where implemented;
- noise;
- respiration modulation;
- RX Red/IR;
- measured AC/DC/PI/R/SpO2;
- TX/RX visualization;
- diagnostics;
- calibration workflow.

For every feature record:

- implemented / partial / missing;
- software verified?
- hardware verified?
- reference evidence;
- weight if a score is used.

Do not claim 80–90% similarity without showing the scope, weighting, verified/unverified items, and the calculation.

Do not claim clinical equivalence or medical-device validation.

## Required completion report

Create:

`docs/phase_reports/PHASE_09_COMPLETION_REPORT.md`

Include:

- status;
- prerequisites read;
- test inventory;
- exact commands executed;
- hardware measurements actually performed;
- PASS/FAIL/NOT RUN/BLOCKED matrix;
- functional similarity matrix;
- score method if any;
- known limitations;
- `git diff --stat`;
- acceptance checklist;
- do-not-redo handoff for Phase 10.

Then STOP. Do not start Phase 10.
