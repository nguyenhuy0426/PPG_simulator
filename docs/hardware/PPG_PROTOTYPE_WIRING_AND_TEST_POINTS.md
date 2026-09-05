# PPG Prototype Wiring, Test Points and Pre-Power Checks

**Status: DESIGN CALCULATED / HARDWARE NOT VERIFIED.** Companion to
`PPG_PROTOTYPE_SCHEMATIC.md` and `PPG_PROTOTYPE_BOM.md`. Every "expected"
value below is a calculation from the Stage 1 review
(`04_STAGE1_RECALCULATION_REVIEW.md`); none has been measured.

## 1. The 15 test points

| TP | Node | Expected @ code 0 | Expected @ 0x800 | Expected @ 4095 | Instrument |
|---|---|---|---|---|---|
| TP_DAC_IR | MCP4725 #1 VOUT (0x60) | 0.000 V | 1.640 V | 3.279 V | DMM / scope |
| TP_DAC_RED | MCP4725 #2 VOUT (0x61) | 0.000 V | 1.640 V | 3.279 V | DMM / scope |
| TP_CMD_IR | IR divider midpoint (LM358 pin 3) | 0.000 V | 0.820 V | 1.640 V | DMM / scope (C1 selection) |
| TP_CMD_RED | Red divider midpoint (LM358 pin 5) | 0.000 V | 0.820 V | 1.640 V | DMM / scope (C1 selection) |
| TP_LM358_IR | LM358 pin 1 (OUT A) | near 0 V (see note a) | ≈ 1.62–1.70 V | ≈ 2.44–2.62 V (hFE-dependent) | scope |
| TP_LM358_RED | LM358 pin 7 (OUT B) | near 0 V (note a) | ≈ 1.60–1.68 V | ≈ 2.42–2.57 V | scope |
| TP_RSENSE_IR | Q1 emitter / R3 top | 0.000 V (note a) | 0.820 V → 10.00 mA | 1.640 V → 20.00 mA | DMM (current via V/82 Ω) |
| TP_RSENSE_RED | Q2 emitter / R6 top | 0.000 V (note a) | 0.820 V → 8.20 mA | 1.640 V → 16.40 mA | DMM (current via V/100 Ω) |
| TP_OPT101_IR | OPT101 #1 pin 5 | dark baseline (MR) | rises with IR drive (MR) | < 2.13 V always (note b) | DMM / scope |
| TP_OPT101_RED | OPT101 #2 pin 5 | dark baseline (MR) | rises with Red drive (MR) | < 2.13 V always (note b) | DMM / scope |
| TP_ADC_A0 | Grove A0 signal at the socket | = TP_OPT101_IR | = TP_OPT101_IR | = TP_OPT101_IR | DMM (continuity to TP_OPT101_IR) |
| TP_ADC_A2 | Grove A2 signal at the socket | = TP_OPT101_RED | = TP_OPT101_RED | = TP_OPT101_RED | DMM |
| TP_3V28 | 3V28 rail | 3.28 V nominal — **record the actual value** (session metadata field) | ← | ← | DMM |
| TP_5V0 | 5V0 rail | 4.75–5.25 V — **record the actual value** | ← | ← | DMM |
| TP_GND | ground star point | reference | ← | ← | — |

Notes:
(a) With R_BE = DNP the residual at code 0 is MEASUREMENT-REQUIRED — the
classic LM358 table guarantees only 12 µA of sink capability near ground
(Stage 1 §14). A non-zero TP_RSENSE_* at code 0 is a finding, not a fault.
(b) `[CALCULATED]` OPT101 output ceiling ≈ VS − 1.15 V ≈ 2.13 V at 3.28 V.
Readings above ~2.1 V on TP_OPT101_*/TP_ADC_* indicate a wiring fault.
Expected RX signal values are otherwise MEASUREMENT-REQUIRED (MR) — they
depend on the LED-to-OPT101 distance, which is set in Stage 6, not here.

## 2. Wiring order (build sequence)

1. Solder the ground star point and both rails; fit C4a/C4b at the 5 V
   entry. **Do not install U1, Q1/Q2, LEDs, or connect the modules yet.**
2. Verify rails and rail isolation (§3 checks 1–3) with the DMM.
3. Solder the two dividers (R1a/R1b, R4a/R4b), C1 footprints unpopulated,
   the two R_B (R2, R5), R_sense R3/R6 (**soldered — never jumpered**,
   BOM §2 rule), and the R_BE footprints unpopulated.
4. DMM-confirm Q1/Q2 pinout and D1/D2 polarity (§4) — **before** soldering
   them in.
5. Solder Q1/Q2, D1, D2, U1 (with C3), the OPT101s (with C5a/C5b), and the
   pin 4–5 straps if absent (§4 check 3 first).
6. Wire the I2C bus (Pi pin 3 → all SDA, pin 5 → all SCL), the two Grove
   cables to A0 and A2 (signal pin identified per §3 check 5; A1 never
   connected), and the LED-current vs signal ground returns on separate
   runs (schematic §9).
7. Fit the 15 test points.
8. Run the §3 full pre-power checklist, then §5 first power-on.

## 3. Pre-power DMM checklist (all must pass before first power-on)

1. **Rails:** TP_5V0 in 4.75–5.25 V; TP_3V28 ≈ 3.28 V; record both values —
   they are required operator inputs in the capture-session metadata
   (Stage 3).
2. **Rail isolation (task rule):** with power off, resistance from `5V0` to
   every MCP4725 VDD pin, every OPT101 pin 1, and both Grove analog signal
   pins reads open. **No 5 V connection to MCP4725, OPT101 or Grove analog
   inputs.**
3. **No rail shorts:** 5V0↔GND, 3V28↔GND, 5V0↔3V28 all non-shorted.
4. **Ground continuity:** every module GND to TP_GND < 1 Ω.
5. **Grove signal-pin identification:** the Grove socket's internal pin
   order is not established by local evidence. Continuity-map the A0 and A2
   cables from the HAT socket to the wire ends before connecting the
   OPT101s; connect only the confirmed signal wire and GND; **A1 is never
   used.**
6. **Feedback wiring:** continuity LM358 pin 2 ↔ TP_RSENSE_IR and pin 6 ↔
   TP_RSENSE_RED (a broken feedback wire is the fault that can push the Red
   LED past its 20 mA abs max — Stage 1 §16).

## 4. Mandatory part-identification checks (task rule: never assume from the part name)

1. **2SC1815 pinout (Q1, Q2), before soldering.** DMM diode mode:
   - Find the base: the one pin that shows a ~0.5–0.8 V forward drop to
     **both** other pins with the red (+) lead on it (NPN).
   - Distinguish E from C: the B–E junction typically reads a few tens of
     mV **higher** than B–C. If the two readings are too close to call, use
     the DMM's hFE socket or a component tester — do not guess.
   - Record which physical lead is E/C/B and compare against the datasheet
     drawing (1=E, 2=C, 3=B). **Both transistors, individually.** A part
     that disagrees with the datasheet drawing is usable — wire it as
     measured, and record the deviation.
2. **LED polarity (D1, D2), before soldering.** DMM diode mode: exactly one
   orientation conducts. The Red LED (V_F ≈ 1.8–2.2 V) may exceed some
   DMMs' diode-test compliance voltage and read open in **both**
   directions — in that case use a 3.3 V supply through ≥ 330 Ω (≤ 10 mA)
   and observe conduction (the IR LED's emission is invisible; judge by the
   meter, not by eye). Record anode/cathode against the package. The IR
   datasheet marks pin ① = cathode; the Red datasheet has **no** polarity
   drawing — the measurement is the only evidence. A reversed IR LED would
   sit ≈ 0.2 V under its 5 V reverse abs max (Stage 1 §16) — this check is
   not optional.
3. **OPT101 pin 4 → pin 5 strap:** continuity between pins 4 and 5 on each
   assembled module. No strap = no defined transimpedance gain — do not
   power on until strapped.
4. **MCP4725 EEPROM contents (after first I2C contact, §5):** read-only
   verification of the power-up code via the DAC read command. **Never
   write EEPROM.**

## 5. First power-on procedure

1. Expectation `[CALCULATED]` Stage 1 §17: if the modules hold the factory
   EEPROM (0x800), **both LEDs turn ON at half scale at power-up** — Red
   8.2 mA, IR 10.0 mA — before any software runs. Under all ratings; not a
   fault.
2. Power on with the Pi; run `i2cdetect -y 1`: expect exactly 0x08, 0x60,
   0x61.
3. Immediately park both DACs at code 0 (the Stage 5 capture tool does this
   on start; a one-line write is acceptable during bring-up). Verify
   TP_RSENSE_IR ≈ TP_RSENSE_RED ≈ 0 V (note (a) in §1 applies).
4. Read (never write) both EEPROMs; record the power-up codes in the
   session metadata.
5. Single-channel low-code checks per the Stage 5 safety procedure: one
   channel at a time, low codes first, DMM on the channel's TP_RSENSE_*.
   The other channel stays at code 0.

## 6. Scope checks during bring-up

1. **SDA/SCL rise time:** two MCP4725 breakouts each carry their own
   pull-ups plus the HAT on one bus — verify clean edges at 100 kHz/400 kHz
   before trusting timing figures.
2. **TP_CMD_IR / TP_CMD_RED settling (C1 selection, Stage 1 §20):** with a
   1 kHz code staircase, compare DNP / 10 nF / 100 nF / 220 nF. Only 10 nF
   settles within one 1 ms update (5τ = 0.25 ms); 100/220 nF smooth across
   updates by design. Fit both channels identically.
3. **TP_LM358_* stability:** any oscillation → revisit C2 (DNP by default;
   value is bench-determined, never theoretical).
4. **TP_RSENSE_* vs TP_CMD_*:** the loop should hold them equal; a
   persistent gap beyond the Stage 1 error budget (±2 % gain, ~8 mV offset)
   is a finding.

## 7. What is deliberately not in this document

No LED-to-OPT101 distance (Stage 6 measures it; nothing is invented here),
no ADC-code-to-optical-power calibration (Stage 6), no claim that any
expected value has been observed on hardware.

> **Transistor identity is unconfirmed.** This document says 2SC1815 because that is the only transistor datasheet in `docs/ds_linhkien/`; the operator has stated the board carries a 2N4401. The TO-92 pinouts differ (E-C-B vs E-B-C) — verify with a DMM before soldering. See [TRANSISTOR_IDENTIFICATION.md](TRANSISTOR_IDENTIFICATION.md).
