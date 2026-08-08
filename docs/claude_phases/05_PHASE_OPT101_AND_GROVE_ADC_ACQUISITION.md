# Phase 5 — Dual OPT101 Acquisition on the Same Raspberry Pi 4 and Same Grove Base HAT

## Prerequisites

Before changing code, read:

- `docs/claude_phases/00_README_FROM_PHASE_4.md`
- Phase 1 architecture report;
- Phase 1–4 completion reports;
- the current source code and current `git diff`.

Do not redo completed work from Phases 1–4.

## Verified hardware facts — do not treat these as unknown

The complete system uses exactly:

- **1 x Raspberry Pi 4**;
- **1 x Seeed Grove Base HAT**;
- **2 x MCP4725**, with `0x60=IR TX`, `0x61=Red TX`;
- **2 x OPT101**;
- **OPT101 IR -> Grove Base HAT ADC A0**;
- **OPT101 Red -> Grove Base HAT ADC A1**.

The same Raspberry Pi 4 and Grove Base HAT perform TX, RX, processing, and UI visualization.

Do not use A2. The previous A2 mapping is obsolete.

## Objective

Implement real two-channel receiver acquisition on the same Raspberry Pi 4 and same Grove Base HAT without breaking the existing dual-DAC TX path.

## Unified architecture

```text
                         ONE Raspberry Pi 4
                                  |
                                  v
                      ONE Seeed Grove Base HAT
                 /                                  \
        TX over shared Pi I2C                    RX via HAT ADC
       /                    \                   /              \
0x60 MCP4725 IR       0x61 MCP4725 Red      A0 IR OPT101    A1 Red OPT101
       |                    |                   |              |
       v                    v                   +------+-------+
     IR LED               Red LED                     |
       |                    |                          v
       +------ optical -----+                 same Raspberry Pi 4
                                                    |
                                                    v
                                              RX buffers/timestamps
```

## Strict rule

Do not fabricate Grove Base HAT APIs, I2C addresses, register maps, ADC sample rates, ranges, timing, or resolution. Use only:

- actual project source;
- installed real library/API;
- board documentation already present in the project;
- verified runtime evidence.

## Required source audit

Before implementation, inspect:

- existing `hw/adc_reader.py` and whether it is deprecated;
- actual installed/imported Grove ADC API;
- actual channel argument conventions for A0/A1;
- actual ADC resolution/range if verifiable;
- current TX thread and I2C ownership;
- whether ADC reads and MCP4725 writes share the same underlying Pi I2C bus and therefore need serialization.

## Required channel mapping

Use exactly:

```text
A0 -> OPT101 IR
A1 -> OPT101 Red
```

Never duplicate A0 into the Red path. Never fabricate values for a failed/unavailable channel.

## Acquisition requirements

Implement a clean dual-channel receiver abstraction that provides at minimum:

- IR sample from A0;
- Red sample from A1;
- timestamp for acquisition;
- raw ADC code where available;
- converted voltage only if the real ADC conversion behavior/reference is verified;
- per-channel connection/status state;
- bounded buffers;
- stale-data detection hooks;
- disconnect/error handling;
- explicit dry-run/simulation labeling.

Do not perform long blocking work in the UI thread.

## Shared one-Pi/one-HAT bus constraint

TX and RX are not separate devices. They run on the same Raspberry Pi 4 and same Grove Base HAT.

Analyze and implement a safe ownership/scheduling strategy for:

- MCP4725 writes to `0x60` and `0x61`;
- Grove ADC reads for A0 and A1;
- shared I2C access if the Grove ADC driver uses the same Pi bus;
- synchronization and lock scope;
- buffering;
- sample timestamps;
- avoiding starvation of TX or RX.

Do not add a second Raspberry Pi, second HAT, or second I2C controller as an architectural workaround.

## Optical crosstalk and simultaneous emission

Two OPT101 modules do not automatically provide wavelength selectivity.

Analyze, but do not invent results for:

- simultaneous Red and IR illumination;
- Red light reaching the IR receiver;
- IR light reaching the Red receiver;
- fixed optical geometry;
- black partitions/shielding;
- diffuser;
- optical filters;
- time-division multiplexing if evidence later requires it.

Do not implement a complex TDM architecture unless it is justified by actual hardware evidence and does not conflict with prior completed work.

## Electrical compatibility checks

Verify or mark unknown:

- OPT101 supply rail;
- output range;
- Grove ADC input range;
- common ground;
- risk of ADC saturation;
- ability to resolve small PPG AC on a larger DC baseline.

Do not invent compatibility.

## Tests

Add deterministic tests/mocks for:

- `A0=IR`, `A1=Red` mapping;
- timestamp monotonicity/order;
- bounded buffers;
- invalid ADC codes/ranges where applicable;
- disconnected hardware;
- stale data;
- one channel missing;
- no fabricated hardware value when acquisition fails;
- concurrent/shared-I2C abstraction behavior where unit-testable.

Preserve existing Phase 2–4 tests.

## Out of scope

Do not compute final measured AC/DC, PI, R, or SpO2 yet. That belongs to Phase 6.

Keep UI changes minimal; major TX/RX visualization belongs to Phase 7.

## Required completion report

Create:

`docs/phase_reports/PHASE_05_COMPLETION_REPORT.md`

Include:

- status COMPLETE/PARTIAL/BLOCKED;
- prerequisites read;
- exact implementation;
- exact verified Grove ADC API used;
- channel mapping `A0=IR`, `A1=Red`;
- one-Pi/one-HAT shared-bus design;
- thread/lock/buffer ownership;
- files modified/created/deleted;
- exact commands run;
- real tests and results;
- real hardware validation, or NOT RUN/BLOCKED;
- saturation/crosstalk unknowns;
- `git diff --stat`;
- acceptance checklist;
- do-not-redo handoff for Phase 6.

Then STOP. Do not start Phase 6.
