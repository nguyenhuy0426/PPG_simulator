# 04 — Stage 1 Independent Recalculation Review of the 5 V LED-Driver Candidate

**Date:** 2026-07-30
**Status of every number in this document:** DESIGN CALCULATED / HARDWARE NOT VERIFIED.
**Method:** Every numeric value below was produced by running the executable
`led_driver` package (`params`, `dac`, `compliance`, `power`, `error_budget`,
`faults`, `startup`, `filters`, `classification`) in this session, on the
laptop, against the locally present datasheets. Nothing was copied from
`03_LED_DRIVER_ARCHITECTURE.md`; where this review agrees with that document
the agreement is a result, not an input. The arithmetic is enforced by the
test suite (`tests/test_led_driver_*.py`, 331 tests passing at the time of
writing — see §23).

**Datasheets used (all local, `docs/ds_linhkien/`):**

| File | Component | Table(s) used |
|---|---|---|
| `MCP4725-Data-Sheet.pdf` (DS20002039E) | MCP4725 DAC | Eq. 5-1, DC specs, Table 5-3 (factory EEPROM), §5.4 (POR), General Call section, abs max |
| `lm358ba.pdf` | LM358P | §5.7 **classic LM358/LM358A table only** — per the task, the LM358B/LM358BA columns were not used |
| `2SC1815L-GR.PDF` | 2SC1815 | abs max, hFE classification, V_BE characterisation |
| `red_led_3.3mm_datasheet.pdf` | YSL-R341R3D-D2 | abs max, Vf, suggestion-current, reverse leakage |
| `IR_led_3.3mm_datasheet.pdf` | SIR234 | abs max (incl. V_R), Vf |
| `opt101.pdf` | OPT101 | supply bypass practice (item 20 only) |
| `grove_base_hat.pdf` | Grove Base HAT | ADC reference context only |

**Topology under review (candidate, `[ENGINEERING-INFERENCE]`, no hardware
built):** MCP4725 → 10 kΩ/10 kΩ divider → LM358P (unity follower onto the
sense node) → R_B 1 kΩ → 2SC1815 emitter-sense current sink → LED fed from
5.00 V → R_sense (Red 100 Ω, IR 82 Ω) to GND. R_BE options DNP/100 kΩ/10 kΩ;
input capacitor C1 options DNP/10 nF/100 nF/220 nF; C2 DNP initially.

**Evidence labels** follow `00_BASE_CONTEXT.md` §6 and are never upgraded.

---

## 1. DAC code range and levels (item 1)

`[VERIFIED-DATASHEET]` The MCP4725 is a 12-bit DAC: **4096 levels, codes
0–4095** (`dac.py`: `level_count = 4096`, `max_code = 4095`). At the
`[VERIFIED-USER]` 3.28 V supply, one LSB is **0.80078125 mV** at the DAC
output, **0.40039 mV** at the command node after the ÷2 divider.

## 2. Real MCP4725 transfer equation (item 2)

`[VERIFIED-DATASHEET]` Equation 5-1 of DS20002039E:
**V_OUT = V_DD · D / 4096**, with V_DD as the reference (ratiometric — there
is no internal reference). Consequences, computed by `dac.code_to_voltage`:

| Code | V_DAC (ratiometric) | V_cmd after ÷2 |
|---|---|---|
| 0 | 0.000000 V | 0.000000 V |
| 1 | 0.000801 V | 0.000400 V |
| 2047 | 1.639199 V | 0.819600 V |
| 2048 | 1.640000 V | 0.820000 V |
| 4094 | 3.278398 V | 1.639199 V |
| 4095 | **3.279199 V** | 1.639600 V |

**Finding (carried into the code):** code 4095 does **not** reach 3.28 V under
Eq. 5-1; it reaches V_DD·4095/4096 = 3.2792 V. The repository's calibration
(`calibration.dac_voltage_to_code`) uses the max-code convention
(V = V_FS·D/4095, truncating). `dac.convention_discrepancy` quantifies the
difference: **exactly 1 LSB = 0.8008 mV = 0.0244 %** at full scale. This is
far below every tolerance in the chain (±1 % resistors) and is acceptable,
but the two conventions must not be mixed inside one computation. The stale
claim in `led_driver/params.py` that the IC datasheet was absent has been
corrected in place; the same stale claims in documents 02/03 are recorded as
findings F-S1/F-S2 in §22 (documents are read-only per audit rules).

## 3. Divider ratio and worst-case tolerance (item 3)

`[CALCULATED]` R_top = R_bot = 10 kΩ, 1 %:

- Nominal ratio **0.500**; extremes with ±1 % parts (from
  `error_budget.divider_ratio_extremes`): **0.495 to 0.505**, i.e. a
  **±1.0 %** channel gain error (`divider_gain_error_fraction`).
- Thevenin source resistance **5.0 kΩ** (sets the C1 filter, §item 20 of
  `led_driver/filters.py`); DAC load **20 kΩ** — a factor of 4 above the
  5 kΩ load used for the datasheet DC accuracy specs, so the DC spec table
  applies conservatively. Divider load current at full scale: **0.164 mA**,
  0.66 % of the DAC's 25 mA absolute-maximum output current.
- The ratio (not the absolute value) sets the gain; ratio error cancels in
  PI and R only if both channels use the same-lot parts. Classification:
  ratio **FIXED BY CALCULATION** (forced by the LM358 CM ceiling, item 4);
  absolute 10 kΩ value **RECOMMENDED STARTING VALUE**.

## 4. LM358P input common-mode range at 5 V (item 4)

`[VERIFIED-DATASHEET]` (classic LM358 table only, per task): input CM range
at V+ = 5.00 V is 0 V up to **(V+) − 1.5 V = 3.50 V at 25 °C** and
**(V+) − 2.0 V = 3.00 V over temperature**. The binding design constraint is
the over-temperature figure. Computed check at the full-scale command
(`compliance.input_common_mode(1.64, ch)`):

> [OK] actual 1.6400 V, limit 3.0000 V, **margin +1.36 V** (both channels).

The undivided DAC full scale (3.279 V) would violate the over-temperature
limit by 0.28 V — this is why the ÷2 divider is FIXED, not optional.

## 5. Op-amp output headroom (item 5)

`[CALCULATED]` Required output = V_sense + V_BE(on) + I_B·R_B, against the
classic-table output ceiling of **3.50 V** (V+ = 5 V, R_L ≥ 2 kΩ). From
`compliance.opamp_output_required_v` at full scale (V_sense = 1.64 V):

| Channel | hFE = 200 (GR bin min) | hFE = 70 (abs min, any bin) | Ceiling | Worst margin |
|---|---|---|---|---|
| Red | 2.4216 V | 2.5710 V | 3.50 V | **+0.929 V** |
| IR | 2.4395 V | 2.6217 V | 3.50 V | **+0.878 V** |

Closes with ≈ 0.9 V of margin even for an unbinned worst-case transistor.
(This supersedes the pre-divider infeasibility statement in
`PHASE_04_COMPLETION_REPORT.md:72` — finding F-S3, §22.)

## 6. Full KCL including base and R_BE currents (item 6)

`[CALCULATED]` At the sense node: I_sense = V_cmd/R_sense (loop-enforced);
I_LED = α·(I_sense − I_RBE) with α = hFE/(hFE+1). At full scale
(V_sense = 1.64 V), from `dac.sense_current` / `dac.led_current_from_command`:

| Channel | I_sense | I_B (hFE 70) | I_B (hFE 200) | I_B (hFE 400) | I_RBE (100 k) | I_RBE (10 k) |
|---|---|---|---|---|---|---|
| Red | 16.4000 mA | 230.99 µA | 81.59 µA | 40.90 µA | 7.00 µA | 70.00 µA |
| IR | 20.0000 mA | 281.69 µA | 99.50 µA | 49.88 µA | 7.00 µA | 70.00 µA |

Resulting I_LED at full scale (hFE = 200): Red 16.3184 mA (no R_BE),
16.3114 mA (R_BE 100 k), 16.2488 mA (R_BE 10 k); IR 19.9005 / 19.8935 /
19.8308 mA. The loop regulates I_sense exactly; the LED receives I_sense
minus base current minus (α-scaled) R_BE bleed — a deterministic ≤ 1.4 %
systematic deficit, not noise.

## 7–8. LED current across the DAC range (items 7, 8)

`[CALCULATED]` `dac.led_current_from_code` (ratiometric convention,
hFE = 200):

| Code | Red I_LED | IR I_LED |
|---|---|---|
| 0 | 0.0000 mA | 0.0000 mA |
| 499 | 1.9880 mA | 2.4244 mA |
| 1023 | 4.0756 mA | 4.9703 mA |
| 2047 | 8.1552 mA | 9.9454 mA |
| 4095 | 16.3144 mA | 19.8956 mA |

Ideal full-scale I_sense: **Red 16.40 mA** (inside the datasheet
"suggestion using current" window 16–18 mA, below the 20 mA abs max) and
**IR 20.00 mA** (one fifth of the SIR234 100 mA continuous rating). Current
resolution: **Red 4.004 µA/LSB, IR 4.883 µA/LSB**. At code 0 the ideal
current is zero; the real residual is offset-dominated (item 13) and its
turn-off behaviour with R_BE = DNP is MEASUREMENT-REQUIRED (item 14).

## 9. Compliance at 4.75 / 5.00 / 5.25 V (item 9)

`[CALCULATED]` `compliance.supply_sweep` at full scale, V_F = datasheet max,
minimum required V_CE = 0.5 V:

| Rail | Red V_CE | Red margin | IR V_CE | IR margin |
|---|---|---|---|---|
| 4.75 V | 0.910 V | +0.410 V | 1.460 V | +0.960 V |
| 5.00 V | 1.160 V | +0.660 V | 1.710 V | +1.210 V |
| 5.25 V | 1.410 V | +0.910 V | 1.960 V | +1.460 V |

All six cases pass. Minimum rail that still closes (V_F max, V_CE 0.5 V):
**Red 4.34 V, IR 3.79 V** (`compliance.minimum_rail_v`) — the Red channel is
the binding one, with 0.41 V of margin at the USB-spec low rail of 4.75 V.

## 10. Forward-voltage worst cases (item 10)

| Channel | V_F min | V_F typ | V_F max | Label |
|---|---|---|---|---|
| Red (YSL-R341R3D-D2) | 1.80 V | 2.00 V | 2.20 V | `[VERIFIED-DATASHEET]` (min is a real datasheet minimum) |
| IR (SIR234) | 1.30 V | 1.30 V | 1.65 V | `[VERIFIED-DATASHEET]` typ/max; **the 1.30 V "min" is the typ reused as a modelling lower bound** (`vf_min_is_datasheet_minimum = False`) — the datasheet states no minimum |

V_F max is used for compliance (item 9), V_F min for transistor dissipation
(item 11) and for the reversed-transistor V_EB bound (item 16).

## 11. Transistor V_CE and dissipation (item 11)

`[CALCULATED]` At full scale, 5.00 V rail (`power.dissipation_report`):

- Red: V_CE = 1.16 V (V_F max) … dissipation at V_F **min** (worst for the
  transistor) **25.58 mW** — 6.4 % of the 400 mW rating.
- IR: V_CE = 1.71 V (V_F max) … dissipation at V_F min **41.20 mW** — 10.3 %
  of rating.

No heatsinking consideration required at these levels.

## 12. R_sense and LED dissipation (item 12)

`[CALCULATED]` at full scale:

| Part | Dissipation | Rating | Fraction |
|---|---|---|---|
| R_sense Red 100 Ω | 26.90 mW | 250 mW (¼ W part assumed) | 11 % |
| R_sense IR 82 Ω | 32.80 mW | 250 mW | 13 % |
| Red LED (V_F max) | 36.08 mW | 105 mW (P_D max) | 34 % |
| IR LED (V_F max) | 33.00 mW | 150 mW | 22 % |

All close with ≥ 3× margin. ¼ W R_sense parts are a RECOMMENDED STARTING
VALUE; ⅛ W would also close but with less margin against transients.

## 13. Offset and bias error (item 13)

`[CALCULATED]` from the classic-table worst cases (V_OS 7 mV max at 25 °C
plus I_B 250 nA into the 5 kΩ Thevenin source ≈ 1.25 mV):

- Input-referred worst-case offset ≈ **8.25 mV** → current error
  **82.5 µA (Red), 100.6 µA (IR)**.
- As a fraction of full scale: **0.50 %** — negligible for brightness.
- At 10 % of full scale: **5.0 %** — offset dominates the low-current end
  and is the reason code 0 does not guarantee a dark LED to better than
  ~0.5 % of full brightness.
- Gain errors: R_sense ±1 % → −0.99 %/+1.01 %; divider ±1 % on top → total
  **−1.98 %/+2.02 %** (`error_budget.total_gain_error_fraction`).

These are per-channel DC errors; PI and R depend on AC/DC ratios within one
channel, so pure gain errors cancel there — offset does **not** cancel.

## 14. R_BE dead zone, turn-off and PI distortion (item 14)

`[CALCULATED]` `error_budget.rbe_comparison` (hFE 300, V_BE 0.70 V, 1 % AC
fraction, DC at half scale):

| Option | Bleed | Dead zone (Red) | Dead zone codes | DC error | PI error | Turn-off |
|---|---|---|---|---|---|---|
| DNP | 0 | 0 | 0 | −0.33 % | 0 | **MEASUREMENT-REQUIRED** — classic table guarantees only 12 µA sink near ground; residual LED current at code 0 unproven |
| 100 kΩ | 7 µA | 0.70 mV | 1 | −0.42 % | +0.085 % | active hold-off |
| 10 kΩ | 70 µA | 7.00 mV | 17 | −1.18 % | +0.861 % | active hold-off |

(IR dead zones: 0.574 mV / 5.74 mV = 1 / 14 codes.) The 10 kΩ option costs
17 codes of dead zone and ~0.9 % PI distortion; the 100 kΩ option costs
almost nothing and still provides an active turn-off path. **Per the task,
R_BE is NOT finalised from theory: footprint fitted, value
MEASUREMENT-REQUIRED** (scope the code-0 residual with DNP first).

## 15. hFE models (item 15)

`[CALCULATED]` I_LED at full scale vs hFE (α-model, `dac.led_current_from_command`):

| hFE | Red | IR |
|---|---|---|
| 70 (abs min, any bin) | 16.1690 mA | 19.7183 mA |
| 200 (GR bin min) | 16.3184 mA | 19.9005 mA |
| 300 | 16.3455 mA | 19.9336 mA |
| 400 (GR bin max) | 16.3591 mA | 19.9501 mA |
| 700 (abs max) | 16.3766 mA | 19.9715 mA |

Total spread across the entire 70–700 range is **1.3 %**; within the GR bin
**0.25 %**. Feedback makes the design first-order insensitive to hFE; the
installed part's bin remains MEASUREMENT-REQUIRED because it sets the exact
base-current deficit, not because it threatens regulation.

## 16. Single-fault analysis (item 16)

`[CALCULATED]` `led_driver/faults.py`, drive ceiling
V_DRIVE_MAX = (3.50 − 0.70) = 2.80 V. "Destructive" marks deterministic
steady-state rating violations only.

| Fault | Red signature | IR signature | Destructive? |
|---|---|---|---|
| **Open LED** | base path clamps I at 2.545 mA, V_sense clamp 0.2545 V, op-amp saturated high | 2.588 mA / 0.2122 V | No |
| **Shorted LED** | regulation intact; V_CE 3.36 V, Q diss. 55.10 mW | V_CE 3.36 V, 67.20 mW | No (< 400 mW) |
| **Open R_sense** | LED dark; sense node **INDETERMINATE** (floats) | same | No |
| **Shorted R_sense** | base drive slams to 2.80 mA; worst-gain bound ≥ **196 mA** (hFE 70) | same | **YES — the only destructive single fault**; exceeds both LED abs max and the 2SC1815 150 mA I_C rating |
| **Broken feedback** | output **INDETERMINATE**; worst bound 2.80 V/R_sense = **28.0 mA > 20 mA Red abs max** | 34.15 mA < 100 mA | No (outcome indeterminate; Red flagged `exceeds_led_abs_max`) |
| **Reversed transistor** | V_EB bound 3.20 V < V_EBO 5 V; reverse hFE **UNKNOWN** | 3.70 V < 5 V | No |
| **Reversed LED** | blocks like open LED; Red reverse abs max **UNKNOWN** (datasheet gives only 10 µA leakage at 5 V) | reverse ≈ **4.788 V vs 5 V abs max at a 5.00 V rail — exceeds it at 5.25 V** | No, but IR margin ≈ 0.2 V |

Design consequences: (a) R_sense must be soldered, never breadboard-jumpered,
and TP_RSENSE_* probing must not risk a short to ground; (b) the reversed-IR
margin is the concrete justification for the mandated DMM polarity check
before power-on; (c) bring-up must start at low codes so a broken-feedback
op-amp saturating high is caught before full drive.

## 17. Startup before Pi software control (item 17)

`[VERIFIED-DATASHEET]` + `[CALCULATED]` (`led_driver/startup.py`): the
MCP4725's factory-programmed EEPROM is **normal mode, code 0x800**
(Table 5-3), uploaded to the DAC register at V_POR ≈ 2 V (§5.4), settling
6 µs typ. If the installed modules still hold the factory EEPROM, then at
power-up — before any Pi software runs —

- V_DAC = 1.640 V → V_cmd = 0.820 V → **Red 8.200 mA, IR 10.000 mA**
  (exactly half full-scale). Under all ratings, but **both LEDs are ON at
  boot**.
- The actual EEPROM contents of the two installed modules are
  **MEASUREMENT-REQUIRED**, and are verifiable **read-only**: the MCP4725
  read command returns both the DAC register and the EEPROM. The
  never-write-EEPROM rule is honored — reading suffices.

## 18. Shutdown, exceptions, loss of I2C (item 18)

`[CALCULATED]` The MCP4725 has **no watchdog**: on loss of I2C it holds the
last written code indefinitely (`startup.i2c_loss_sense_current_a`: a stuck
code 4095 holds Red at 16.396 mA and IR at 19.995 mA forever — within
ratings, but uncontrolled). Mitigations, all software-side and mandatory for
Stage 5: park both DACs at **code 0** (= `config.DAC_IDLE_VALUE`) on normal
exit, on exception, on Ctrl+C and on timeout. **General Call Reset (0x06)
cannot be used as a per-channel mitigation**: it acts on every device on the
bus, resetting both DACs (and re-loading EEPROM contents — which, per item
17, may turn both LEDs ON at half scale, not off).

## 19. 5 V current budget (item 19)

`[CALCULATED]` `power.rail_current_budget` at full scale, both channels:

- LEDs: 16.40 + 20.00 = **36.40 mA**
- Base currents (worst hFE 70): ≈ 0.51 mA
- R_BE bleed (10 kΩ fitted both sides): 0.14 mA
- LM358 quiescent: 1.2 mA (classic table max, both amps)
- **Total ≈ 38 mA worst case** — trivial against a Pi 4 USB-C supply. The
  5 V rail feeds only the LM358P and the LED strings;
  **no 5 V connection to MCP4725, OPT101 or Grove analog inputs.**

## 20. Decoupling and ground-return paths (item 20)

`[RECOMMENDED STARTING VALUE]` (values); `[ENGINEERING-INFERENCE]` (routing):

- C3 = 100 nF at the LM358P V+ pin (placement matters more than value).
- C4 = 10 µF bulk + 100 nF at the 5 V entry point.
- C5 = 100 nF per OPT101 on the 3.28 V rail (datasheet practice).
- C1 (command node, DNP/10 n/100 n/220 n): sees the 5 kΩ Thevenin source.
  Computed option space (`filters.option_table`):

| C1 | f_c | \|H\| @ 1 kHz | \|H\| @ 100 Hz | \|H\| @ 10 Hz | 5τ settle |
|---|---|---|---|---|---|
| DNP | ∞ | 1.000 | 1.000 | 1.000 | 0 |
| 10 nF | 3183.1 Hz | 0.954 | 0.9995 | 1.0000 | 0.25 ms |
| 100 nF | 318.3 Hz | 0.303 | 0.954 | 0.9995 | 2.5 ms |
| 220 nF | 144.7 Hz | 0.143 | 0.823 | 0.9976 | 5.5 ms |

  Only 10 nF settles within one 1 ms DAC update; 100/220 nF deliberately
  smooth across updates. The PPG band (≤ 10 Hz) is essentially untouched by
  every option. A ±10 % tolerance on 100 nF creates a ~1.7 % Red-vs-IR gain
  mismatch at 100 Hz — both channels must be fitted identically. **Selection
  is MEASUREMENT-REQUIRED (scope on TP_CMD_IR/TP_CMD_RED).**
- Ground returns: the two LED-current loops (5 V → LED → Q → R_sense → GND)
  must return to the supply entry without sharing trace/wire segments with
  the OPT101/ADC signal ground; a shared segment converts ~20 mA of
  modulated LED current into millivolts of signal-ground bounce at the ADC.
  Star the returns at one point. This is a layout rule, verifiable only on
  the built prototype.

---

## 21. Value classification (task-required four-way table)

Generated from `led_driver/classification.py` (`VALUE_TABLE`, enforced by
`tests/test_led_driver_classification.py`). MEASUREMENT-REQUIRED and UNKNOWN
entries deliberately carry **no number**, so a number cannot be mistaken for
a decision.

**FIXED BY DATASHEET/CALCULATION**

| Value | Number | Basis |
|---|---|---|
| DAC full scale / V_DD | 3.28 V | `[VERIFIED-USER]` rail + Eq. 5-1 |
| ADC reference (separate symbol) | 3.28 V | `[VERIFIED-USER]` |
| 5 V rail (LM358P + LEDs) | 5.00 V | `[VERIFIED-USER]`; 12 V design forbidden |
| Divider ratio | 0.5 | forced by the 3.00 V over-temp CM ceiling |
| LM358P output ceiling (R_L ≥ 2 k) | 3.50 V | classic table, V+ = 5 V |
| LM358P CM ceiling over temp | 3.00 V | classic table — the binding constraint |

**RECOMMENDED STARTING VALUE**

| Value | Number | Basis |
|---|---|---|
| R_sense Red | 100 Ω | full scale 16.40 mA in the 16–18 mA suggestion window |
| R_sense IR | 82 Ω | full scale 20.00 mA = ⅕ of 100 mA rating |
| R_B | 1 kΩ | caps shorted-R_sense base drive at 2.8 mA |
| Divider legs | 10 kΩ | 20 kΩ DAC load, 5 kΩ Thevenin |
| C3 LM358 bypass | 100 nF | standard practice |
| C4 5 V bulk | 10 µF + 100 nF | standard practice |
| C5 OPT101 bypass | 100 nF each | OPT101 datasheet practice |

**MEASUREMENT-REQUIRED** (no value stated by design): R_BE (options
DNP/100 k/10 k), C1 (options DNP/10 n/100 n/220 n), C2 (DNP unless the bench
shows instability), installed 2SC1815 hFE bin, V_BE(on) at the few-mA
operating points, installed 2SC1815 pinout, installed LED polarities,
MCP4725 EEPROM power-up contents (read-only check), OPT101 pin-4-to-5 strap.

**UNKNOWN**: Red LED reverse-voltage absolute maximum (datasheet gives only
a leakage characterisation).

---

## 22. Findings against existing documents (recorded, not edited)

Per the audit rules (`00_BASE_CONTEXT.md`), contradictions with read-only
documents are findings, not edits.

| ID | Document | Claim | Status |
|---|---|---|---|
| **F-S1** | `02_DATASHEET_EVIDENCE.md` §2.6 | "No local IC-level MCP4725 datasheet exists in this repository"; IC parameters listed `[UNKNOWN]` | **STALE.** `docs/ds_linhkien/MCP4725-Data-Sheet.pdf` (DS20002039E, 1.7 MB) exists and was read for this review. Eq. 5-1, Table 5-3, §5.4, the DC spec table and the abs-max table upgrade those parameters to `[VERIFIED-DATASHEET]` as captured in §§1–2, 17–18 here. |
| **F-S2** | `03_LED_DRIVER_ARCHITECTURE.md` F-B3 (also §2.1, §6.2) | "MCP4725-Data-Sheet.pdf does not exist locally … output drive capability unestablished" | **STALE**, same evidence. The output drive question F-B3 left open is now bounded: abs max output current 25 mA, DC specs characterised into 5 kΩ; the 20 kΩ divider load draws 0.164 mA. The 20 kΩ choice remains sound. |
| **F-S3** | `docs/phase_reports/PHASE_04_COMPLETION_REPORT.md:72` | On 5 V, "headroom for V_sense up to 3.2 V + LED Vf + transistor drop does not close at full-scale command" | **SUPERSEDED**, not wrong: it described the pre-divider design with a 3.2 V command range. With the ÷2 divider (V_sense max 1.64 V) the same arithmetic closes with ≥ 0.41 V margin at a 4.75 V rail (§9) and ≥ 0.88 V of op-amp margin (§5). |
| **F-S4** | `led_driver/params.py:40` (code, editable) | claimed the MCP4725 datasheet was absent | **CORRECTED IN PLACE** this session — code comments are not read-only audit documents. |

---

## 23. Verdict and verification evidence

**The candidate design passes the Stage 1 recalculation review.** Every
compliance check closes at 4.75/5.00/5.25 V; all dissipations sit at ≤ 34 %
of ratings; the only destructive single fault (shorted R_sense) and the two
tightest hazards (reversed IR LED at 0.2 V margin; broken feedback bounding
Red at 28 mA vs its 20 mA abs max) are identified with explicit bring-up
countermeasures; startup and I2C-loss behaviour is characterised from the
IC datasheet with a read-only EEPROM verification path.

Open items deliberately **not** decided from theory (per task): R_BE, C1, C2,
plus every installed-part property listed in §21. The final Red and IR
operating currents may be revised after the Stage 6 optical measurements.

Verification run (laptop, this session):

```
$ .venv/bin/python -m unittest discover -s tests -v
...
Ran 331 tests in 0.063s
OK
```

covering `tests/test_led_driver_params.py`, `_dac`, `_compliance`, `_power`,
`_error_budget`, `_faults` (25), `_startup` (17), `_filters` (16),
`_classification` (12) and the pre-existing 261-test baseline, unchanged.

**Nothing in this document is hardware-, optically- or clinically
validated.** Every number is DESIGN CALCULATED / HARDWARE NOT VERIFIED.
