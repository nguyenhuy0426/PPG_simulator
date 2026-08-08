# Phase 6 — Signal Processing and Measured SpO2 on the Unified Single-Pi TX/RX Pipeline

## Prerequisites

Read the Phase 1 architecture report, Phase 1–5 completion reports, current source, and current `git diff`.

Do not redo prior phases.

## Verified system baseline

- One Raspberry Pi 4.
- One Grove Base HAT.
- TX: MCP4725 `0x60=IR`, `0x61=Red`.
- RX: OPT101 IR -> A0, OPT101 Red -> A1.
- The same Raspberry Pi application generates TX, acquires RX, processes measurements, and later displays both.

## Objective

Process only real Phase 5 receiver samples into measured Red/IR AC, DC, PI, ratio-of-ratios R, and measured SpO2.

Never use generated TX samples as if they were received OPT101 measurements.

## Required pipeline

```text
A0 IR raw samples + A1 Red raw samples
        -> timestamps
        -> bounded buffers
        -> validation / stale checks
        -> optional filtering
        -> AC/DC extraction per channel
        -> PI_ir / PI_red
        -> R_measured
        -> SpO2_measured
```

## Required formulas

Use the already-centralized Phase 2–3 primitives wherever applicable. Do not duplicate formulas inline.

```text
PI_ir  = AC_ir_measured  / DC_ir_measured  * 100%
PI_red = AC_red_measured / DC_red_measured * 100%

R_measured = (AC_red_measured / DC_red_measured)
             -------------------------------------
             (AC_ir_measured  / DC_ir_measured)

SpO2_measured = A - B * R_measured
```

A/B remain configurable. Do not treat 110/25 as universal clinical calibration.

## AC definition

Choose one AC definition and use it consistently everywhere. Examples include peak-to-peak, half peak-to-peak, RMS, or fitted amplitude, but do not mix definitions.

The chosen method must be explicitly documented with:

- window length;
- sample-rate dependency;
- filtering assumptions;
- output unit;
- reason it matches the simulator's intended ratio calculation.

Do not invent a sample rate; use the verified Phase 5 rate/timestamps.

## Processing requirements

- Keep TX target values separate from RX measured values.
- Keep raw and filtered data separate.
- Do not block the Tk UI thread.
- Use bounded buffering/windowing.
- Detect insufficient samples.
- Detect stale data.
- Detect clipping/saturation.
- Reject `DC <= 0`.
- Reject invalid or zero IR denominator.
- Reject missing channel.
- Do not display a measured SpO2 when the required RX inputs are invalid.
- Preserve timestamps so TX/RX timing can later be correlated.

## One-device truthfulness rule

Because the same Raspberry Pi 4 both transmits and receives, do not shortcut the pipeline by feeding generated values directly into the measured path. The measured path must consume the real A0/A1 receiver samples produced by Phase 5.

Dry-run values, when present, must be explicitly labeled as simulation and never presented as hardware measurement.

## Tests

Add deterministic tests for:

- DC extraction;
- AC extraction;
- PI_ir;
- PI_red;
- full ratio-of-ratios;
- configurable A/B;
- measured SpO2;
- invalid DC;
- zero/invalid IR denominator;
- clipping/saturation;
- stale buffer;
- insufficient samples;
- missing A0/IR or A1/Red channel;
- no fake measured output on acquisition failure.

Preserve all prior tests.

## Out of scope

Do not perform the major UI redesign yet; that is Phase 7.

Do not claim clinical accuracy.

## Required completion report

Create:

`docs/phase_reports/PHASE_06_COMPLETION_REPORT.md`

Include:

- COMPLETE/PARTIAL/BLOCKED status;
- prerequisites read;
- exact processing pipeline;
- AC definition and windowing method;
- actual sample-rate/timestamp evidence used;
- files modified/created/deleted;
- formulas/API reused from prior phases;
- exact commands run;
- real PASS/FAIL/NOT RUN/BLOCKED results;
- remaining hardware/calibration unknowns;
- `git diff --stat`;
- acceptance checklist;
- do-not-redo handoff for Phase 7.

Then STOP. Do not start Phase 7.
