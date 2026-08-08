# Current Verified PPG Simulator Architecture — Source of Truth

This file is the current architecture truth for Phases 4–10. It overrides older unknowns or obsolete mappings that may still appear in historical Phase 1–3 prompts or reports.

## Verified hardware architecture

- Exactly **1 Raspberry Pi 4** is used.
- Exactly **1 Seeed Grove Base HAT** is used with that same Raspberry Pi 4.
- The same Raspberry Pi 4 + Grove Base HAT perform **TX generation, DAC output, RX acquisition, signal processing, and Linux UI visualization**.
- Raspberry Pi I2C is exposed/routed through the Grove Base HAT I2C path to the DAC modules.
- **MCP4725 `0x60` = IR transmit channel.**
- **MCP4725 `0x61` = Red transmit channel.**
- **MCP4725 supply = 3.28 V; MCP4725 DAC full-scale = 3.28 V.** [VERIFIED-USER 2026-07-29] (The MCP4725 is ratiometric to VDD, so full-scale tracks the supply.) This supersedes the earlier "measured DAC full-scale = 3.2 V" figure recorded in Phase 2–5 documents.
- **Grove Base HAT MCU = MM32 -> ADC I2C address `0x08`.** [VERIFIED-USER 2026-07-29] This supersedes the earlier `0x04` assumption, which is the STM32 revision of the same HAT. Independently corroborated by `docs/ds_linhkien/grove_base_hat.pdf` p.3: *"the IIC address of MM32 is 0x08, while the STM32 is 0x04."*
- **Grove ADC full-scale / reference used by this project = 3.28 V; resolution = 12 bits.** [VERIFIED-USER 2026-07-29] This supersedes the earlier nominal 3.3 V assumption. It is a distinct quantity from the MCP4725 full-scale even though both currently hold 3.28 V.
- **OPT101 supply = 3.28 V.** [VERIFIED-USER 2026-07-29]
- **OPT101 IR receiver -> Grove Base HAT ADC A0.**
- **OPT101 Red receiver -> Grove Base HAT ADC A2.** [VERIFIED-USER 2026-07-12]
- **A1 is NOT used for OPT101.** (An earlier revision of this file stated A1 = Red and "A2 obsolete"; that was superseded by the user's verified hardware facts at Phase 5 start. See PHASE_05_COMPLETION_REPORT.md.)
- **LM358 installed device = LM358P (standard/classic variant, PDIP package); LM358 supply = 5.00 V.** [VERIFIED-USER 2026-07-29] Do not apply LM358B / LM358BA offset, output-swing, GBW or slew-rate specifications to this part.
- **All modules share a verified common ground.** [VERIFIED-USER 2026-07-29]
- No second Raspberry Pi, no second Grove Base HAT, no separate receiver computer, and no separate transmitter controller exist in the target architecture.

## Verified optical arrangement [VERIFIED-USER 2026-07-29]

The dark chamber is divided into **two completely isolated compartments**:

- **IR compartment:** IR LED -> dedicated IR OPT101 -> Grove ADC A0
- **Red compartment:** Red LED -> dedicated Red OPT101 -> Grove ADC A2

There is **no** WhaleTeq optical fixture, **no** common optical cavity, **no**
shared detector, **no** tissue phantom and **no** intentional Red/IR optical
mixing. WhaleTeq documents are functional references only. Any older diagram or
text implying a shared optical path is superseded by this section.

## Unified architecture

```text
User parameters
(HR, RR, target SpO2, A, B, AC, DC, noise)
        |
        v
PPG model on ONE Raspberry Pi 4
        |
        v
IR + Red generated waveforms
        |
        v
ONE Grove Base HAT / shared Raspberry Pi I2C path
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
 [isolated IR compartment]      [isolated Red compartment]
        |                               |
        v                               v
OPT101 IR -> A0                 OPT101 Red -> A2
        |                               |
        +-------------+-----------------+
                      |
                      v
              same Grove Base HAT ADC (MM32, 0x08)
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
               same Linux application
               showing TX and RX waveforms
```

## Historical-document precedence rule

Phase 1–3 files are retained because they record completed work and prevent redoing tasks. However, where they contain old unknowns or obsolete mappings, this file and `00_README_FROM_PHASE_4.md` take precedence.

In particular, do not treat the following as unknown anymore:

- `0x60` is IR TX.
- `0x61` is Red TX.
- A0 is IR RX.
- A2 is Red RX. [VERIFIED-USER 2026-07-12]
- Grove Base HAT ADC is at `0x08` (MM32), not `0x04` (STM32). [VERIFIED-USER 2026-07-29]
- DAC full-scale is 3.28 V, not 3.2 V and not 3.3 V. [VERIFIED-USER 2026-07-29]
- Grove ADC reference is 3.28 V, not 3.3 V. [VERIFIED-USER 2026-07-29]
- The two optical compartments are isolated; there is no shared cavity. [VERIFIED-USER 2026-07-29]

Do not use A1 for OPT101.
