# Phase 10 — Final Calibration, Documentation, and Acceptance for the One-Pi / One-HAT PPG Simulator

## Prerequisites

Read the Phase 1 architecture report, Phase 1–9 completion reports, actual final source code, real test results, and current `git diff`.

Do not rewrite completed work unless a verified defect blocks final acceptance.

## Verified hardware architecture baseline

The final system uses exactly:

- **1 x Raspberry Pi 4**;
- **1 x Seeed Grove Base HAT**;
- **MCP4725 `0x60` = IR TX**;
- **MCP4725 `0x61` = Red TX**;
- DAC full-scale source of truth = **3.2 V**;
- **OPT101 IR -> Grove ADC A0**;
- **OPT101 Red -> Grove ADC A1**;
- the same Raspberry Pi 4 performs TX generation, RX acquisition, processing, and Linux UI display.

Do not use the obsolete A2 mapping. Do not document multiple Raspberry Pis or multiple Grove Base HATs.

## Objective

Finalize the exact architecture, calibration workflow, hardware/software documentation, remaining limitations, and honest acceptance status.

## Required final architecture documentation

Include explicit diagrams for:

1. system overview;
2. one-Raspberry-Pi software architecture;
3. one-Grove-Base-HAT hardware architecture;
4. IR TX path: Pi -> Grove I2C -> MCP4725 0x60 -> driver -> IR LED;
5. Red TX path: Pi -> Grove I2C -> MCP4725 0x61 -> driver -> Red LED;
6. IR RX path: IR optical path -> OPT101 -> A0 -> Grove ADC -> Pi;
7. Red RX path: Red optical path -> OPT101 -> A1 -> Grove ADC -> Pi;
8. shared I2C topology;
9. ADC topology;
10. power/common-ground plan;
11. thread/timing/buffer architecture;
12. end-to-end data pipeline;
13. UI data flow showing TX and RX on the same Raspberry Pi display.

## Required canonical end-to-end pipeline

```text
User parameters
(HR, RR, target SpO2, A, B, AC, DC, noise)
        |
        v
PPG model on the Raspberry Pi 4
        |
        v
IR and Red generated TX waveforms
        |
        v
same Raspberry Pi I2C path through one Grove Base HAT
        |
        +-------------------------------+
        |                               |
        v                               v
MCP4725 0x60 IR                  MCP4725 0x61 Red
        |                               |
        v                               v
IR LED driver                     Red LED driver
        |                               |
        v                               v
      IR LED                          Red LED
        |                               |
        +----------- optical -----------+
                        |
          +-------------+-------------+
          |                           |
          v                           v
OPT101 IR -> A0                OPT101 Red -> A1
          |                           |
          +-------------+-------------+
                        |
                        v
              same Grove Base HAT ADC
                        |
                        v
                same Raspberry Pi 4
                        |
                        v
       acquisition -> buffering -> filtering
                        |
                        v
            measured AC/DC per channel
                        |
                        v
                  PI_ir / PI_red
                        |
                        v
             R = (AC_red/DC_red)/(AC_ir/DC_ir)
                        |
                        v
               measured SpO2 = A - B*R
                        |
                        v
               same Linux application/UI
                showing TX and RX waveforms
```

## Calibration workflow

Document the complete chain without collapsing distinct quantities:

```text
Configured target parameters
-> generated digital waveform
-> commanded 12-bit DAC code
-> measured DAC voltage
-> LED-driver current
-> optical emission
-> OPT101 analog voltage
-> Grove ADC sample
-> extracted AC/DC
-> PI
-> R
-> measured SpO2
```

Keep each of the following explicitly separate:

- configured target;
- generated digital sample;
- DAC command;
- measured electrical output;
- optical output;
- receiver analog voltage;
- ADC code/voltage;
- processed values;
- calculated SpO2.

## Calibration coefficient documentation

Explain:

```text
SpO2 = A - B*R
```

and make clear:

- 110/25 are defaults/reference approximations;
- A/B are configurable;
- A/B are not universal clinical constants;
- changing A/B changes numeric mapping;
- in target-generation mode A/B also change R_target and therefore Red/IR amplitude ratio.

## BOM

Split into:

- already owned;
- required;
- optional;
- recommended replacement.

Do not invent exact component values or part numbers where LED ratings, supply rails, or driver design evidence is incomplete.

## Final acceptance criteria

The intended architecture should support:

```text
HR + RR + target SpO2 + A + B + AC + DC + noise
-> PPG generation
-> IR/Red TX waveforms
-> MCP4725 0x60 IR + MCP4725 0x61 Red
-> LED drivers
-> IR/Red optical emission
-> OPT101 IR A0 + OPT101 Red A1
-> Grove Base HAT ADC
-> same Raspberry Pi 4 acquisition
-> AC/DC extraction
-> PI
-> R
-> measured SpO2
-> same Linux application showing TX and RX
```

For each criterion mark:

- COMPLETE;
- PARTIAL;
- BLOCKED;
- NOT VERIFIED.

Do not promote unmeasured hardware behavior to COMPLETE.

## Final similarity assessment

Use the Phase 9 feature matrix. Do not state a single 80–90% result without:

- scope;
- weighting method;
- feature list;
- software verification status;
- hardware verification status;
- unverified assumptions.

Do not claim clinical-grade performance.

## Required completion report

Create:

`docs/phase_reports/PHASE_10_COMPLETION_REPORT.md`

Include:

- final status;
- completed features;
- partial features;
- blocked features;
- actual hardware dependencies;
- actual measurement dependencies;
- real tests/measurements;
- unverified assumptions;
- final architecture diagrams;
- BOM;
- calibration workflow;
- acceptance matrix;
- AECG100 feature similarity matrix;
- `git diff --stat`;
- explicit statement that no clinical-grade claim is made.

Then STOP.
