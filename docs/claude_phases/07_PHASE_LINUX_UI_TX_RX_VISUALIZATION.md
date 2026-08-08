# Phase 7 — Linux UI Showing TX and RX on the Same Raspberry Pi 4

## Prerequisites

Read the Phase 1 architecture report, Phase 1–6 completion reports, current source, and current `git diff`.

Preserve the existing CustomTkinter architecture. Do not rewrite unrelated UI code.

## Verified single-device architecture

Exactly one Raspberry Pi 4 and one Grove Base HAT perform:

- waveform generation;
- MCP4725 TX;
- OPT101 ADC acquisition;
- signal processing;
- Linux GUI display.

The GUI must therefore present one unified local system, not separate transmitter and receiver computers.

## Verified channel mapping

```text
TX IR  -> MCP4725 0x60
TX Red -> MCP4725 0x61
RX IR  -> OPT101 on A0
RX Red -> OPT101 on A1
```

Do not use A2.

## Objective

Extend the existing Linux application so the same screen can show:

- generated/transmitted IR and Red waveforms;
- real received IR and Red waveforms;
- target parameters;
- measured values;
- real hardware status.

## Required controls

Expose, without duplicating model logic:

- Heart Rate (BPM);
- Respiratory Rate (BrPM);
- target SpO2 (%);
- calibration coefficient A;
- calibration coefficient B;
- AC amplitude in mV;
- IR DC level in mV;
- Red DC level in mV;
- noise level with explicit meaning/unit;
- start;
- stop;
- apply;
- reset/default.

Where already implemented in Phase 3 and useful:

- AC above/below DC polarity.

Only add BM/AM/FM, noise frequency, apnea, or other controls if the current phase specification and existing architecture support them without scope creep.

## TX display

Show at minimum:

- IR TX waveform;
- Red TX waveform;
- IR AC/DC/PI;
- Red AC/DC/PI;
- target R;
- target SpO2;
- DAC channel labels `0x60 IR`, `0x61 Red`.

## RX display

Show at minimum:

- IR RX raw waveform from A0;
- Red RX raw waveform from A1;
- optional filtered waveforms if implemented in Phase 6;
- measured IR AC/DC/PI;
- measured Red AC/DC/PI;
- measured R;
- measured SpO2.

Never duplicate the TX waveform into RX as a placeholder.

## Hardware status

Display truthful per-path status:

```text
MCP4725 0x60 / IR TX
MCP4725 0x61 / Red TX
Grove ADC A0 / IR RX
Grove ADC A1 / Red RX
```

Also show as applicable:

- connected/disconnected;
- stale/no data;
- clipping;
- saturation;
- I2C error;
- dry-run/simulation label.

Never show fabricated real measurements while hardware is disconnected.

## Performance/threading

- No blocking I/O in the Tk main thread.
- Use thread-safe snapshots of existing bounded buffers.
- Bound plot refresh rate independently of DAC/ADC rates.
- Avoid race conditions between generation, acquisition, processing, and rendering.
- Do not create a second process/computer architecture unless the existing project already requires it and evidence supports it.

## Tests/checks

Where practical, test:

- UI state binding to TX values;
- UI state binding to RX values;
- per-channel labels/mapping;
- no fake RX value when hardware is unavailable;
- stale-data display;
- clipping/saturation indicator;
- dry-run labeling;
- compatibility with current config persistence.

Run an actual GUI smoke test only if a display/session is available; otherwise mark NOT RUN/BLOCKED.

## Required completion report

Create:

`docs/phase_reports/PHASE_07_COMPLETION_REPORT.md`

Include:

- status;
- prerequisites read;
- exact UI changes;
- screenshots only if actually produced;
- files modified/created/deleted;
- TX/RX mapping presented;
- threading/refresh design;
- exact commands run;
- real test results;
- GUI smoke status;
- remaining UI/hardware gaps;
- `git diff --stat`;
- acceptance checklist;
- do-not-redo handoff for Phase 8.

Then STOP. Do not start Phase 8.
