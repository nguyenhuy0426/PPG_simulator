# PPG Simulator — Phase 4 to Phase 10 Execution Pack

## Verified physical baseline that all phases must preserve

This project uses exactly:

- **1 x Raspberry Pi 4** as the only controller/computer.
- **1 x Seeed Grove Base HAT** mounted/connected to that same Raspberry Pi 4.
- The same Raspberry Pi 4 + Grove Base HAT are used for **both transmit and receive paths**, signal processing, and Linux UI visualization.
- The Raspberry Pi 4 communicates over its I2C bus through the Grove Base HAT I2C path to the two MCP4725 DAC modules.
- **MCP4725 `0x60` = IR transmit channel.**
- **MCP4725 `0x61` = Red transmit channel.**
- Measured DAC full-scale used by the project is **3.2 V**.
- **OPT101 IR receiver -> Grove Base HAT ADC `A0`.**
- **OPT101 Red receiver -> Grove Base HAT ADC `A1`.**
- There is no second Raspberry Pi, no second Grove Base HAT, no separate receiver computer, and no separate transmitter controller.

## Unified physical architecture

```text
                         ONE Raspberry Pi 4
                                  |
                    waveform generation + control
                                  |
                                  v
                      ONE Seeed Grove Base HAT
                       /                      \
             I2C transmit path            ADC receive path
               /          \                 /          \
              v            v               v            v
       MCP4725 0x60   MCP4725 0x61     A0 / OPT101  A1 / OPT101
           IR TX          Red TX          IR RX          Red RX
              |            |               ^              ^
              v            v               |              |
       IR LED driver  Red LED driver       |              |
              |            |               |              |
              v            v               |              |
            IR LED       Red LED            \            /
              |            |                 optical path
              +------------+-----------------------+
                                  |
                                  v
                         same Raspberry Pi 4
                   buffering -> filtering -> AC/DC
                     -> PI -> R -> measured SpO2
                                  |
                                  v
                     same Linux application / UI
                    showing TX and RX waveforms
```

## Execution rules for every phase

1. Read the current phase file, Phase 1 architecture report, and all previous phase completion reports before changing code.
2. Inspect the current source code and current `git diff` so completed work is not repeated.
3. Make the smallest technically correct change.
4. Never invent APIs, I2C behavior, ADC behavior, circuit values, LED ratings, optical power, timing, measurements, or validation results.
5. Keep configured targets, generated digital waveforms, commanded DAC values, measured electrical values, received optical signals, and calculated physiological outputs clearly separated.
6. Do not redesign the system into multiple Raspberry Pis, multiple Grove Base HATs, a separate transmitter, or a separate receiver.
7. At the end of each phase, create `docs/phase_reports/PHASE_XX_COMPLETION_REPORT.md`, record exact commands actually executed and real PASS/FAIL/NOT RUN/BLOCKED status, then stop.
8. Do not automatically begin the next phase.

## Recommended model/effort

| Phase | Recommended model | Effort |
|---|---|---|
| Phase 4 | Opus | xhigh |
| Phase 5 | Opus | xhigh |
| Phase 6 | Opus | high or xhigh |
| Phase 7 | Sonnet | high |
| Phase 8 | Opus | xhigh |
| Phase 9 | Opus | xhigh |
| Phase 10 | Opus | high |
