# Phase 8 — Diagnostics and Runtime Safety for the Unified One-Pi / One-HAT System

## Prerequisites

Read the Phase 1 architecture report, Phase 1–7 completion reports, current source, and current `git diff`.

Do not redesign completed features.

## Verified endpoints

Exactly one Raspberry Pi 4 and one Grove Base HAT manage:

```text
TX IR  -> MCP4725 0x60
TX Red -> MCP4725 0x61
RX IR  -> OPT101 -> A0
RX Red -> OPT101 -> A1
```

Measured DAC full-scale used by software: 3.2 V.

## Objective

Make the complete local simulator diagnosable and robust against runtime failures across the same Pi/HAT TX/RX pipeline.

## Required checks

At minimum cover:

- presence/initialization of MCP4725 `0x60`;
- presence/initialization of MCP4725 `0x61`;
- Grove ADC availability;
- A0 IR configuration;
- A1 Red configuration;
- I2C NACK/error;
- timeout only where supported by the real API;
- shared-bus contention/lock misuse;
- stale RX data;
- buffer overflow/underflow;
- DAC clipping;
- ADC saturation;
- invalid AC/DC;
- invalid A/B;
- invalid R;
- OPT101 signal too low/high where thresholds are evidence-based;
- one receiver channel missing;
- hardware disconnect during run.

Do not invent timeout/retry APIs that the actual library does not provide.

## Safe-state behavior

Define the real behavior for:

- user stop;
- exception;
- DAC disconnect;
- ADC disconnect;
- application shutdown.

Safe-state requirements must be grounded in actual hardware/library capabilities. Do not claim electrical safety guarantees that were not measured or designed.

## Shared one-Pi/one-HAT concurrency

Because TX and RX use the same Raspberry Pi 4 and Grove Base HAT, review:

- one owner versus shared owners of I2C operations;
- lock duration;
- deadlock risk;
- starvation;
- RX buffer backlog;
- TX deadline misses;
- UI blocking;
- exception propagation.

Make the smallest correct change.

## Structured diagnostics

Use concise structured logs and UI state indicators. Distinguish:

- software initialized;
- device address found;
- command attempted;
- command acknowledged where verified;
- measured analog behavior;
- optical behavior.

Do not infer successful hardware operation from logs alone.

## Oscilloscope debug guide

Document for each relevant test point:

- probe point;
- ground reference;
- coupling mode;
- vertical scale where known;
- time scale where known;
- expected DC range where known;
- expected AC range where known;
- clipping/saturation signature.

Cover:

- DAC `0x60` IR output;
- DAC `0x61` Red output;
- IR driver output/current-sense node if present;
- Red driver output/current-sense node if present;
- OPT101 IR output to A0;
- OPT101 Red output to A1.

## Logic analyzer debug guide

Document checks for:

- I2C address `0x60`;
- I2C address `0x61`;
- Grove ADC device path/API if visible on I2C;
- ACK/NACK;
- payload bytes;
- update intervals;
- timing gaps;
- retries only if supported.

## Timestamp correlation

Preserve/compare:

```text
TX model timestamp
-> DAC command timestamp
-> ADC A0/A1 sample timestamp
-> processing window timestamp
-> UI frame timestamp
```

Do not claim deterministic end-to-end latency unless measured.

## Tests

Add focused failure-mode tests where hardware-independent:

- missing 0x60;
- missing 0x61;
- missing A0;
- missing A1;
- stale samples;
- invalid channel mapping;
- clipping/saturation status;
- safe-state transition;
- no fake measured values after failure.

Preserve all previous tests.

## Required completion report

Create:

`docs/phase_reports/PHASE_08_COMPLETION_REPORT.md`

Include:

- status;
- prerequisites read;
- exact diagnostics added;
- safe-state behavior;
- concurrency findings;
- files changed;
- exact commands run;
- real PASS/FAIL/NOT RUN/BLOCKED status;
- real hardware debug performed, or NOT RUN/BLOCKED;
- oscilloscope and logic-analyzer guide locations;
- remaining unknowns;
- `git diff --stat`;
- acceptance checklist;
- do-not-redo handoff for Phase 9.

Then STOP. Do not start Phase 9.
