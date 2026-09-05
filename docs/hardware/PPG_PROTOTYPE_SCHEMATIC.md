# PPG Prototype Schematic — 5 V LED Driver + Dual Optical RX

**Status: PROTOTYPE SCHEMATIC ONLY. DESIGN CALCULATED / HARDWARE NOT
VERIFIED. This is not a final PCB; no Gerbers exist or will be generated at
this stage.**

Source of every value: `docs/superpowers/ppg_design_audit/04_STAGE1_RECALCULATION_REVIEW.md`
(the Stage 1 recalculation) and the executable `led_driver` package. Evidence
labels follow `00_BASE_CONTEXT.md` §6.

## 1. Power nets

| Net | Value | Source | Allowed loads |
|---|---|---|---|
| `3V28` | 3.28 V `[VERIFIED-USER]` | Pi 3.3 V rail (measured 3.28 V) | MCP4725 ×2, OPT101 ×2, Grove Base HAT |
| `5V0` | 5.00 V `[VERIFIED-USER]` (4.75–5.25 V design window) | Pi 5 V rail | **LM358P and the two LED strings ONLY** |
| `GND` | 0 V | common ground — mandatory single reference | all |

**RULE (task-mandated): no 5 V connection to the MCP4725 modules, the OPT101s
or the Grove analog inputs — ever.** The only parts on `5V0` are the LM358P
(pin 8) and the two LED anodes.

## 2. Block overview — four separate blocks

The Red and IR paths are optically and electrically separate: two isolated
optical compartments, no shared detector, no shared optical cavity, no tissue
phantom, no WhaleTeq fixture.

```
I2C bus (Pi pins 3=SDA1, 5=SCL1, 3.3 V logic)
 ├── 0x60  MCP4725 #1 ──► IR TX driver  ──► IR LED   ─┐ optical, isolated
 ├── 0x61  MCP4725 #2 ──► Red TX driver ──► Red LED  ─┼─ compartments
 └── 0x08  Grove Base HAT ADC (MM32)                  │
        A0 ◄── OPT101 #1 (IR RX)  ◄───────────────────┘
        A2 ◄── OPT101 #2 (Red RX) ◄───────────────────┘
        A1: NEVER USED (task rule)
```

## 3. IR TX block (MCP4725 @ 0x60 → LM358P amp A → Q1 → IR LED)

```
                3V28
                 │
        ┌────────┴────────┐
        │ MCP4725 #1      │  I2C addr 0x60  [VERIFIED-USER]
        │ (Adafruit brkt) │  VDD=3V28, GND, SDA, SCL, VOUT
        └───────┬─────────┘
                │ VOUT                        ● TP_DAC_IR
               R1a 10k 1%
                │
                ├──────────────● TP_CMD_IR
                │         │
               R1b 10k 1%   C1a (DNP / 10n / 100n / 220n)
                │         │
               GND       GND
                │
   (midpoint) ──┴──► LM358P pin 3 (IN A+)          PDIP-8, amp A
                                                      ┌─────────┐
     LM358P pin 1 (OUT A) ●TP_LM358_IR       OUT A  1 │●        │ 8  V+ ── 5V0 (+C3 100n to GND)
        │                                    IN A−  2 │         │ 7  OUT B
       R2 1k ──► Q1 BASE                     IN A+  3 │         │ 6  IN B−
        │                                    V−     4 │         │ 5  IN B+
   C2a (DNP) from pin 1 to pin 2                      └─────────┘
                                             pin 4 ── GND
     LM358P pin 2 (IN A−) ◄── feedback wire from the SENSE node

                5V0
                 │
              IR LED D1 (SIR234)  ANODE to 5V0, CATHODE to Q1 collector
                 │                [VERIFIED-DATASHEET: pkg pin①=cathode,
                 │                 pin②=anode — installed part still
                 │                 DMM-confirmed before power-on]
              Q1 COLLECTOR
              Q1 = 2SC1815, TO-92
              Q1 EMITTER ──┬───────────────● TP_RSENSE_IR  (= SENSE node)
                           │
              R3be (DNP / 100k / 10k) from Q1 BASE to SENSE node
                           │
                          R3 82 Ω 1% (R_sense IR)
                           │
                          GND (LED-current return — see §7)
```

Full-scale design point: I_sense = 1.64 V / 82 Ω = 20.00 mA `[CALCULATED]`.

## 4. Red TX block (MCP4725 @ 0x61 → LM358P amp B → Q2 → Red LED)

Identical topology, second half of the **same** LM358P package:

```
MCP4725 #2 (0x61) VOUT ● TP_DAC_RED
  → R4a 10k 1% / R4b 10k 1% divider, midpoint ● TP_CMD_RED
    + C1b (DNP / 10n / 100n / 220n) to GND   [same option as C1a — the two
                                              channels must be fitted
                                              identically, Stage 1 §20]
  → LM358P pin 5 (IN B+)
LM358P pin 7 (OUT B) ● TP_LM358_RED → R5 1k → Q2 BASE
C2b (DNP) from pin 7 to pin 6
LM358P pin 6 (IN B−) ◄ feedback from Q2 SENSE node
5V0 → Red LED D2 (YSL-R341R3D-D2) ANODE → CATHODE → Q2 collector
      [Red datasheet has NO polarity diagram — polarity is
       MEASUREMENT-REQUIRED by DMM diode test before power-on]
Q2 (2SC1815) EMITTER → SENSE node ● TP_RSENSE_RED
R6be (DNP / 100k / 10k) from Q2 BASE to SENSE node
SENSE node → R6 100 Ω 1% (R_sense Red) → GND
```

Full-scale design point: I_sense = 1.64 V / 100 Ω = 16.40 mA `[CALCULATED]`,
inside the datasheet 16–18 mA suggestion window.

## 5. LM358P PDIP-8 pin assignment (exact)

`[VERIFIED-DATASHEET]` `lm358ba.pdf` §6 pinout; assignment is this design's
choice:

| Pin | Function | Net in this design |
|---|---|---|
| 1 | OUT A | IR drive → R2 1 k → Q1 base ● TP_LM358_IR |
| 2 | IN A− | feedback from IR SENSE node (TP_RSENSE_IR) |
| 3 | IN A+ | IR command (divider midpoint, TP_CMD_IR) |
| 4 | V− | GND |
| 5 | IN B+ | Red command (divider midpoint, TP_CMD_RED) |
| 6 | IN B− | feedback from Red SENSE node (TP_RSENSE_RED) |
| 7 | OUT B | Red drive → R5 1 k → Q2 base ● TP_LM358_RED |
| 8 | V+ | 5V0, with C3 100 nF to GND at the pin |

Only the classic LM358/LM358A datasheet table was used for all limits
(task rule); the installed part is an LM358P (classic PDIP).

## 6. Transistors Q1, Q2 — footprint and pinout status

- Part: 2SC1815, TO-92 footprint.
- `[VERIFIED-DATASHEET]` the Toshiba 2SC1815 drawing gives **pin 1 = Emitter,
  pin 2 = Collector, pin 3 = Base** in the datasheet's own orientation.
- **Pinout status of the installed parts: MEASUREMENT-REQUIRED.** Parts
  marked "C1815" have shipped with reordered pinouts. **DMM confirmation of
  the actual installed transistor's pinout is mandatory before power-on**
  (procedure in `PPG_PROTOTYPE_WIRING_AND_TEST_POINTS.md` §4). Package pin
  ordering is never assumed from the part name.
- Why it matters (Stage 1 §16): a reversed transistor puts up to 3.7 V on
  the E-B junction (V_EBO abs max 5 V) and its regulation behaviour is
  UNKNOWN.

## 7. IR RX block (OPT101 #1 → Grove A0) and Red RX block (OPT101 #2 → Grove A2)

Two identical, physically separate blocks — one per optical compartment.

```
        3V28 ──┬── OPT101 pin 1 (VS)
               C5 (100 nF) to GND at the pin
  OPT101 pinout [VERIFIED-DATASHEET opt101.pdf p.3]:
     1 = VS          5 = Output ────────● TP_OPT101_IR (or _RED)
     2 = −In         6 = NC             │
     3 = −V  ── GND  7 = NC             └──► Grove signal wire ► A0 (IR)
     4 = 1MΩ Feedback— strap to pin 5   ─── or A2 (Red) ● TP_ADC_A0 / _A2
     8 = Common ── GND
```

- Pin 4 → pin 5 strap activates the internal 1 MΩ transimpedance feedback.
  **Whether the strap exists on the assembled modules is
  MEASUREMENT-REQUIRED** (continuity check, wiring doc §4).
- Single-supply use: pin 3 (−V) and pin 8 (Common) both to GND.
- `[CALCULATED]` output swing ceiling at VS = 3.28 V is ≈ (VS − 1.15 V) ≈
  **2.13 V** — the ADC will never see a valid OPT101 signal above ~2.1 V;
  higher readings indicate a wiring fault, not signal.
- Grove Base HAT ADC: address **0x08** (MM32 revision, `[VERIFIED-USER]`),
  12-bit, reference 3.28 V. IR OPT101 → **A0**, Red OPT101 → **A2**,
  **A1 is never used**. The 4-pin Grove socket's internal pin order is not
  established by local evidence — identify the signal pin by continuity
  before connecting (wiring doc §3).

## 8. Decoupling summary

| Ref | Value | At | Net |
|---|---|---|---|
| C3 | 100 nF | LM358P pin 8 | 5V0 |
| C4a/C4b | 10 µF + 100 nF | 5 V entry point to the board | 5V0 |
| C5a/C5b | 100 nF each | each OPT101 pin 1 | 3V28 |
| (on-module) | — | MCP4725 breakouts carry their own VDD bypass `[VERIFIED-SCHEMATIC]` | 3V28 |

C1a/C1b (command filters) and C2a/C2b (loop compensation) are **selectable /
DNP** — see §3, §4; selection is MEASUREMENT-REQUIRED (Stage 1 §20, §14).

## 9. Ground-return topology (task-mandated separation)

```
                     Pi GND (star point at the 5 V/3V28 entry)
                        │
        ┌───────────────┼─────────────────────┐
   LED-current returns  │                signal returns
   R3 (IR sense) ───────┤                OPT101 #1 pin 3/8 ──┤
   R4 (Red sense) ──────┤                OPT101 #2 pin 3/8 ──┤
   C4 bulk ─────────────┤                Grove socket GND ───┤
   LM358P pin 4 ────────┤                MCP4725 GND ×2 ─────┤
```

The two LED-current loops (5V0 → LED → Q → R_sense → GND, up to 20 mA
modulated) must reach the star point on their **own** wire segments, shared
with nothing on the OPT101/ADC side. A shared segment converts LED current
into signal-ground bounce at the ADC (Stage 1 §20). `[ENGINEERING-INFERENCE]`
— verifiable only on the built prototype.

## 10. I2C bus

- Pi physical pin 3 = SDA1, pin 5 = SCL1 (`[VERIFIED-DATASHEET]` Pi 4
  datasheet §5.1.1), 3.3 V logic.
- Devices: MCP4725 #1 (0x60), MCP4725 #2 (0x61), Grove HAT ADC (0x08).
- `[VERIFIED-SCHEMATIC]` each MCP4725 breakout carries its own pull-ups;
  with two breakouts plus the HAT on one bus the parallel pull-up load is a
  known open question — check SDA/SCL rise on the scope during bring-up
  (wiring doc §6).
- MCP4725 General Call Reset (0x06) is **bus-wide** — it cannot be used as a
  per-channel mitigation, and after reset both DACs reload their EEPROM
  contents, which (factory default) turns both LEDs ON at half scale
  (Stage 1 §17–18). Never write MCP4725 EEPROM.

## 11. What this schematic deliberately does not decide

Per Stage 1 classification (§21): R_BE value (footprints R3be/R6be fitted,
DNP initially), C1 option, C2 (DNP unless the bench shows instability),
installed transistor pinout/hFE bin, installed LED polarity, MCP4725 EEPROM
power-up contents, OPT101 strap presence, LED-to-OPT101 distance (Stage 6 —
no distance is invented here).

> **Transistor identity is unconfirmed.** This document says 2SC1815 because that is the only transistor datasheet in `docs/ds_linhkien/`; the operator has stated the board carries a 2N4401. The TO-92 pinouts differ (E-C-B vs E-B-C) — verify with a DMM before soldering. See [TRANSISTOR_IDENTIFICATION.md](TRANSISTOR_IDENTIFICATION.md).
