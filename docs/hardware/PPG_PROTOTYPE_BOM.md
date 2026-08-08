# PPG Prototype BOM

**Status: PROTOTYPE BOM. DESIGN CALCULATED / HARDWARE NOT VERIFIED. No final
PCB, no Gerbers.** Reference designators match
`PPG_PROTOTYPE_SCHEMATIC.md`. Classifications come from the Stage 1 review
(`04_STAGE1_RECALCULATION_REVIEW.md` §21): FIXED = fixed by
datasheet/calculation; REC = recommended starting value; MR =
measurement-required; DNP = do not populate initially.

## 1. Active parts and modules

| Ref | Part | Package | Qty | Class | Notes |
|---|---|---|---|---|---|
| U1 | LM358P (classic, **not** LM358B/BA) | PDIP-8 | 1 | FIXED (limits) | both channels: amp A = IR, amp B = Red; classic datasheet table governs all limits |
| Q1, Q2 | 2SC1815 | TO-92 | 2 | MR (pinout, hFE bin) | datasheet order E-C-B; installed pinout DMM-confirmed before power-on |
| D1 | SIR234 IR LED, 875 nm | 3.3 mm radial | 1 | REC (operating point) | I_F abs 100 mA cont.; design full scale 20.00 mA; V_R abs max 5 V — polarity DMM-confirmed |
| D2 | YSL-R341R3D-D2 Red LED | 3.3 mm radial | 1 | REC (operating point) | I_F abs 20 mA, suggestion 16–18 mA; design full scale 16.40 mA; reverse abs max UNKNOWN — polarity DMM-confirmed |
| M1 | MCP4725 breakout (Adafruit, A1 variant) | module | 1 | — | I2C 0x60 = IR TX; VDD = 3V28 only |
| M2 | MCP4725 breakout (Adafruit, A1 variant) | module | 1 | — | I2C 0x61 = Red TX; VDD = 3V28 only |
| M3, M4 | OPT101 monolithic photodiode + TIA | DIP-8 | 2 | MR (pin 4–5 strap) | VS = 3V28 only; M3 = IR RX → A0, M4 = Red RX → A2 |
| M5 | Grove Base HAT (MM32 revision) | HAT | 1 | — | ADC 0x08, 12-bit, ref 3.28 V; A1 never used |
| — | Raspberry Pi 4, Ubuntu 24.04 | — | 1 | — | I2C SDA1/SCL1 (pins 3/5); supplies 3V28 and 5V0 |

## 2. Resistors (all fixed, 1 %, ¼ W through-hole)

| Ref | Value | Qty | Class | Role |
|---|---|---|---|---|
| R1a, R1b | 10 kΩ | 2 | ratio FIXED, value REC | IR command divider (÷2) |
| R4a, R4b | 10 kΩ | 2 | ratio FIXED, value REC | Red command divider (÷2) |
| R2 | 1 kΩ | 1 | REC | IR base series (caps shorted-R_sense drive at 2.8 mA) |
| R5 | 1 kΩ | 1 | REC | Red base series |
| R3 | 82 Ω | 1 | REC | IR R_sense → 20.00 mA full scale; 32.8 mW at FS |
| R6 | 100 Ω | 1 | REC | Red R_sense → 16.40 mA full scale; 26.9 mW at FS |
| R3be | footprint only | 1 | **MR / DNP** | IR base-emitter bleed; options DNP / 100 kΩ / 10 kΩ, chosen on the bench |
| R6be | footprint only | 1 | **MR / DNP** | Red base-emitter bleed; same options, same choice as R3be |

Divider legs for the two channels should come from the same batch (ratio
matching drives the channel gain error, Stage 1 §3).

**R_sense mounting rule (Stage 1 §16): R3 and R6 must be soldered — never
breadboard-jumpered. A shorted R_sense is the only destructive single fault
(≥ 196 mA bound).**

## 3. Capacitors

| Ref | Value | Qty | Class | Role |
|---|---|---|---|---|
| C1a, C1b | footprint + option kit: 10 nF, 100 nF, 220 nF | 2 fp + 2×3 caps | **MR / DNP** | command-node filter; both channels always fitted identically; chosen with scope on TP_CMD_* |
| C2a, C2b | footprint only | 2 | **MR / DNP** | loop compensation (op-amp out → IN−); fitted only if the bench shows instability |
| C3 | 100 nF | 1 | REC | LM358P pin 8 bypass |
| C4a | 10 µF (≥ 10 V) | 1 | REC | 5 V entry bulk |
| C4b | 100 nF | 1 | REC | 5 V entry HF |
| C5a, C5b | 100 nF | 2 | REC | one per OPT101 pin 1 (3V28) |

## 4. Test points and mechanical

| Item | Qty | Notes |
|---|---|---|
| Test-point pins/loops | 15 | TP_DAC_IR, TP_DAC_RED, TP_CMD_IR, TP_CMD_RED, TP_LM358_IR, TP_LM358_RED, TP_RSENSE_IR, TP_RSENSE_RED, TP_OPT101_IR, TP_OPT101_RED, TP_ADC_A0, TP_ADC_A2, TP_3V28, TP_5V0, TP_GND |
| Prototype board (perfboard/stripboard, soldered) | 1 | soldered construction required for the R_sense rule above; **not a PCB order — no Gerbers** |
| Opaque optical compartments | 2 | one per channel; completely isolated; no shared detector or cavity; rigid LED/OPT101 mounting with operator-adjustable, measurable spacing (Stage 6) |
| Grove analog cables | 2 | to A0 and A2 sockets; signal pin identified by continuity before use; A1 never connected |
| Hookup wire — LED-current returns vs signal returns | — | separate runs to the single ground star point (schematic §9) |

## 5. Explicitly absent from this BOM

- Any 12 V part (task: keep 5 V).
- Any part connecting 5 V to MCP4725, OPT101, or Grove analog inputs.
- A final LED-to-OPT101 spacer: the distance comes from the Stage 6
  measured sweep, never from this BOM.
- PCB fabrication items (no Gerbers at this stage).
