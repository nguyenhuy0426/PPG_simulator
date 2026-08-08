# 03 — LED Driver Architecture Comparison and Component Calculations

**Status:** design analysis, not an as-built description.
**Date:** 2026-07-29
**Depends on:** `00_BASE_CONTEXT.md` (facts F-01…F-17, evidence-label rules §6),
`01_CURRENT_SYSTEM_AUDIT.md`, `02_DATASHEET_EVIDENCE.md`.
**Scope:** the TX chain between the two MCP4725 outputs and the two LEDs, one
independent driver per optical compartment. RX front-end (OPT101 → Grove ADC)
is out of scope except where it constrains the TX operating point (§9).

---

## 0a. ERRATA — corrections applied 2026-07-30, and where the numbers now live

Every table in this document was originally computed by hand. The arithmetic has
since been re-derived in executable Python under `led_driver/` (stdlib only, no
GPIO and no I2C imports) and locked down by 145 hardware-independent tests in
`tests/test_led_driver_{dac,compliance,power,error_budget}.py`. **Where this
document and `led_driver/` disagree, `led_driver/` is correct** — it is the
tested artefact.

The design status is unchanged and unchanged-able by any of this:
`led_driver.params.DESIGN_STATUS` — **HYPOTHESIS, NOT HARDWARE-VERIFIED.** No
board has been built and no current, voltage or optical measurement has been
taken. Laptop test runs prove arithmetic, not circuits.

| # | Original claim | Correction | Authority |
|---|---|---|---|
| E-1 | §7.7, §7.6: 5 V rail total **37.3 mA** | **37.60 mA.** The old figure summed LED currents plus op-amp I_Q. The correct KCL per channel is `I_C + I_B + I_RBE = I_E + I_RBE = I_sense`, so rail = 16.40 + 20.00 + 2×0.600 = 37.60 mA. h_FE and R_BE move current between the LED and op-amp branches without changing the total — but they *do* reduce what reaches the LED. | `led_driver.power.rail_current_budget` |
| E-2 | §6.3, §7.3: R_BE = 10 kΩ, decided | **NOT FINALISED.** 10 kΩ, 100 kΩ and DNP are compared in `led_driver.error_budget.rbe_comparison`; see §7.3 below. `RBE_DECISION.require_value()` raises `MeasurementRequiredError` so no code can silently adopt a number. `[MEASUREMENT-REQUIRED]` | `led_driver.error_budget.RBE_DECISION` |
| E-3 | §8.3: C2 = 1 nF, "recommended starting value" | **DNP.** Fit the footprint, leave it unpopulated. The correct value depends on loop gain, β at the operating point and layout parasitics, none of which are known. Set it only after a scope step response or a validated loop model. `[MEASUREMENT-REQUIRED]` | `led_driver.error_budget.C2_COMPENSATION` |
| E-4 | §8.1: "a 1 kHz component aliases to **exactly DC**" | Overstated. That holds for two ideal, phase-locked clocks. The TX timer and the ADC sampling derive from independent oscillators under a non-real-time Linux userspace: **phase** is unconstrained, **clock drift** of only 100 ppm moves the alias anywhere in 0–0.2 Hz (into the baseline band that feeds the DC term) and 500 ppm reaches 1 Hz (inside the heart-rate band), and **timer jitter** spreads the update-train energy instead of collapsing it onto one line. The real spectrum is `[MEASUREMENT-REQUIRED]`. | `led_driver.error_budget.ALIASING_CAVEAT`, `alias_band_hz` |
| E-5 | §7.4: constant h_FE "cancels in PI and R", residual "≪ 1 %" | The *algebraic* half is right: a constant `α = h_FE/(h_FE+1)` is a pure multiplicative gain and divides out of PI and R. The *quantitative* half is not evidence. Real h_FE varies with I_C and with junction temperature; any variation across the AC swing, or thermal drift correlated with the modulation, survives the ratio. The residual must be **measured** on the real part at the real operating point over the real temperature range before any accuracy figure is quoted. | `led_driver.error_budget.HFE_CANCELLATION_CAVEAT` |
| E-6 | §6.3 / §7.2: op-amp output = `V_sense + V_BE + I_B·R_B` | Incomplete. When R_BE is fitted the op-amp also sources the bleed current through R_B: `V_OUT = V_sense + V_BE + (I_B + I_RBE)·R_B`. Omitting `I_RBE` understates the R_B drop and therefore overstates output headroom. | `led_driver.compliance.opamp_output_required_v` |
| E-7 | §8.4 note: the 4095-vs-4096 scale discrepancy is "≈ ¼ LSB" | It is **exactly 1 LSB** at code 4095 (0.80078 mV, 0.0244 % FS). The two conventions agree at code 0 and diverge linearly to a full LSB at the top code. | `led_driver.dac.convention_discrepancy` |

Two things this document got right and the tests confirm: the LM358P input
common-mode ceiling (3.50 V at 25 °C, 3.00 V over temperature) is the binding
constraint that justifies the ÷2 attenuator, and the §8.4 code table
(Red 499/1248/1872/2496, IR 409/1023/1535/2047) reproduces exactly.

---

## 0. Scope note and a declared assumption

The instruction that produced this document read, in full:

> STAGE B — Immediately perform Prompt 03: LED-driver architecture comparison
> and resistor/capacitor calculations.

The detailed specification of "Prompt 03" was lost when the originating message
was truncated mid-code-block by a `SessionStart` hook injection, and no copy of
it exists anywhere in the repository (searched: `docs/superpowers/ppg_design_audit/`
contains only `00_`, `01_`, `02_`; no file matching `*prompt*` or `*03*` holds
it). **This document was therefore written from that one-line description plus
the authoritative hardware facts in `00_BASE_CONTEXT.md` §3.** If the original
Prompt 03 asked for something narrower, wider or differently structured, this
document must be re-scoped rather than assumed complete.

---

## 1. The governing finding: there is no as-built schematic

`02_DATASHEET_EVIDENCE.md` §4 item 10 records that **no schematic of the LED
driver stage exists locally at all**. Nothing in the repository — no netlist, no
photo, no BOM, no wiring note — states how the MCP4725 outputs are presently
connected to the LEDs.

**Therefore:**

- **F-B1 `[UNKNOWN]` — The as-built LED driver topology is unknown.** Every
  topology discussed below is a *candidate*, not a description of the bench
  hardware. Nothing in this document may be cited as evidence of what is wired.
- If a driver is already physically built, the values in §6 must be **compared
  against it by measurement**, not applied to it. Substituting a resistor
  computed here into an unknown circuit is not a validated change.
- The one prior analysis of this stage,
  `docs/architecture/PHASE_4_DUAL_DAC_TX_AND_LED_DRIVER.md`, describes the same
  op-amp + transistor current-sink *concept* (its §3.1: "op-amp feedback forces
  V(R_sense) = V_DAC ⇒ I_LED = V_DAC / R_sense") but is **stale on the verified
  constants** — it states ADC `0x04`, "A0 = IR, A1 = Red, A2 obsolete",
  `DAC_FULLSCALE_V = 3.2` and `ADC_VOLTAGE_REF = 3.3`, all four of which are
  superseded by F-10, F-13, F-15 and F-16. Per `00_BASE_CONTEXT.md` §2 that file
  is read-only for this audit, so the contradiction is **recorded here as a
  finding (F-B2) and not edited**.

---

## 2. Verified inputs used in every calculation

Values carried forward from `02_DATASHEET_EVIDENCE.md`, plus first-hand
re-extractions performed for this document.

### 2.1 Command source — MCP4725 ×2

| Quantity | Value | Label |
|---|---|---|
| Supply / full-scale | 3.28 V | `[VERIFIED-USER]` F-10 |
| Resolution | 12 bit → LSB = 3.28/4096 = **0.801 mV** | `[CALCULATED]` from F-10 |
| `0x60` | IR channel | `[VERIFIED-USER]` F-06 |
| `0x61` | Red channel | `[VERIFIED-USER]` F-07 |
| Update rate | 1000 Hz per channel | `[VERIFIED-CODE]` `config.FS_TIMER_HZ` |
| Output drive capability | **not established** — `docs/ds_linhkien/MCP4725-Data-Sheet.pdf` does **not exist** locally; only the Adafruit module schematic image is present (`02` §2.6) | `[UNKNOWN]` |

The missing MCP4725 IC datasheet matters here: it bounds how heavily the DAC
output may be loaded (§6.2). It is listed as a required read in the task but is
absent from disk — recorded as **F-B3 `[UNKNOWN]`**.

### 2.2 Op-amp — LM358P, classic variant, V+ = 5.00 V

First-hand extraction from `docs/ds_linhkien/lm358ba.pdf` §5.7, the
**"Electrical Characteristics: LM358, LM358A"** table (the classic table, per the
explicit instruction not to apply LM358B/BA figures to the installed LM358P).
Conditions VS = 5 V, TA = 25 °C unless noted.

| Parameter | Value | Consequence for this design |
|---|---|---|
| V_OS | 3 mV typ, **7 mV max** (9 mV over 0–70 °C) | sets the LED-current DC offset (§7.2) |
| dV_OS/dT | 7 µV/°C | thermal drift of LED current (§7.5) |
| I_B | −20 nA typ, **−250 nA max** (−500 nA over temp) | offset via divider source impedance (§6.2) |
| **Input CM range** | **(V−) to (V+) − 1.5 V** = 0…3.50 V; **(V+) − 2** = 0…3.00 V over 0–70 °C | **the binding constraint** — see §5 |
| CMRR | 65 dB min, 80 dB typ | |
| A_OL | 25 V/mV min, 100 V/mV typ | loop gain ≫ needed |
| GBW | **0.7 MHz** | loop bandwidth budget (§8) |
| SR | **0.3 V/µs** (G = +1) | slew check (§8.2) |
| Output swing from V+ | RL ≥ 2 kΩ, VS = 5 V → **1.5 V max dropout** ⇒ V_OUT ≤ 3.50 V | output headroom (§5.3) |
| Output swing to V− | RL ≤ 10 kΩ, VS = 5 V → 5 mV typ, 20 mV max | LED turn-off (§7.3) |
| I_O source | −20 mA min, −30 mA typ — **specified at VS = 15 V** | see caveat below |
| I_O sink | 10 mA min, 20 mA typ — **at VS = 15 V** | |
| I_O sink at V_O = 200 mV | **12 µA min, 30 µA typ** | near-ground sink collapse (§7.3) |
| Channel separation | 120 dB typ, f = 1–20 kHz | IR/Red crosstalk through the shared package (§7.6) |
| I_Q | 350 µA typ, 600 µA max per amplifier | rail budget (§7.7) |

**Caveat, stated explicitly:** the output source/sink current limits are
tabulated at **VS = 15 V, not 5 V**. Any claim about how much current the LM358P
can source from a 5.00 V rail is therefore **`[ENGINEERING-INFERENCE]`**, not
`[VERIFIED-DATASHEET]`. This single fact is the strongest argument against the
architectures that ask the op-amp to carry the LED current directly (D-2, D-3).

### 2.3 Pass device — 2SC1815 (NPN, TO-92)

First-hand extraction from `docs/ds_linhkien/2SC1815L-GR.PDF`.

| Parameter | Value | Label |
|---|---|---|
| V_CBO / V_CEO / V_EBO | 60 / 50 / 5 V | `[VERIFIED-DATASHEET]` |
| I_C max / I_B max | 150 mA / 50 mA | `[VERIFIED-DATASHEET]` |
| P_C | 400 mW | `[VERIFIED-DATASHEET]` |
| h_FE(1) | 70 min … 700 max @ V_CE = 6 V, I_C = 2 mA | `[VERIFIED-DATASHEET]` |
| h_FE bins | O 70–140, Y 120–240, **GR 200–400**, BL 350–700 | `[VERIFIED-DATASHEET]` |
| V_CE(sat) | 0.1 V typ, 0.25 V max @ I_C = 100 mA, I_B = 10 mA | `[VERIFIED-DATASHEET]` |
| V_BE(sat) | 1.0 V max @ same | `[VERIFIED-DATASHEET]` |
| f_T | 80 MHz min | `[VERIFIED-DATASHEET]` |
| **Installed bin** | filename says GR, part marking **not confirmed on the physical device** | `[MEASUREMENT-REQUIRED]` (`02` §4 item 4) |
| **Installed pinout** | E-C-B vs E-B-C not confirmed for the actual part | `[MEASUREMENT-REQUIRED]` (`02` §4 item 5) |
| V_BE(on) at ~10–20 mA | **not tabulated**; pp. 2–3 curves are images that did not extract | `[ENGINEERING-INFERENCE]` — 0.65–0.75 V assumed below |

### 2.4 LEDs

| Parameter | Red — YSL-R341R3D-D2 | IR — Everlight SIR234 | Label |
|---|---|---|---|
| V_F @ I_F = 20 mA | **1.8 min … 2.2 max V** | **1.30 typ / 1.65 max V** | `[VERIFIED-DATASHEET]` |
| I_F continuous max | 20 mA | 100 mA | `[VERIFIED-DATASHEET]` |
| **"Suggestion Using Current"** | **16–18 mA** | — | `[VERIFIED-DATASHEET]` (new; not in `02`) |
| I_FP pulsed | 30 mA | 1.0 A (PW ≤ 100 µs, duty ≤ 1 %) | `[VERIFIED-DATASHEET]` |
| P_D | 105 mW | 150 mW | `[VERIFIED-DATASHEET]` |
| Wavelength | λ_d 620–625 nm | λ_p 875 nm, Δλ 45 nm | `[VERIFIED-DATASHEET]` |
| Radiant/luminous output | I_v 150–200 mcd | I_e 5.6 min / 9.0 typ mW/sr @ 20 mA | `[VERIFIED-DATASHEET]` |
| Reverse | I_R 10 µA @ V_R = 5 V | I_R 10 µA @ V_R = 5 V | `[VERIFIED-DATASHEET]` |
| Polarity marking | **no pin diagram in the datasheet** | Pin ① = cathode, Pin ② = anode | Red = `[MEASUREMENT-REQUIRED]` |

The Red LED's page-1 tables are scanned images; `pdftotext` cannot reach them.
They were read by rendering page 1 as an image. The **16–18 mA "Suggestion Using
Current"** band is the manufacturer's own recommended operating window and is
used below as the Red design ceiling in preference to the 20 mA absolute
maximum.

### 2.5 Rails

| Rail | Value | Label |
|---|---|---|
| LM358P V+ | 5.00 V, V− = GND (single supply) | `[VERIFIED-USER]` F-11 |
| MCP4725 / OPT101 | 3.28 V | `[VERIFIED-USER]` F-10, F-12 |
| Common ground | verified across all modules | `[VERIFIED-USER]` F-17 |
| LED anode rail | **assumed 5.00 V** (the only rail with enough headroom for the Red LED — see §5.2) | `[ENGINEERING-INFERENCE]` |

---

## 3. What the driver has to do

The simulator's whole purpose is that the *received* optical waveform reproduces
a commanded perfusion index. The calibration model is
`PI = AC/DC × 100` and `R = (AC_red/DC_red)/(AC_ir/DC_ir)`
(`[VERIFIED-CODE]` `calibration.py`). Two consequences follow, and they decide
the architecture:

1. **Linearity of command → LED current is the whole product.** Any curvature
   between DAC volts and radiant flux distorts AC/DC and hence PI and R
   directly. A driver whose transfer function contains the LED's exponential
   I–V characteristic cannot produce a correct PI.
2. **A constant per-channel gain error is harmless.** `PI = AC/DC` is invariant
   under `I → g·I` for any constant `g`, and `R` is a ratio of ratios, so it is
   invariant under independent per-channel constants `g_red`, `g_ir`. This is
   why the unconfirmed h_FE bin (§7.4) turns out **not** to threaten the
   measurement, while the op-amp offset (§7.2), which is *additive*, does.
3. **DC stability over minutes matters more than absolute accuracy.** Drift in
   the DC term moves PI even when AC is perfect.

Requirements, therefore:

| # | Requirement | Source |
|---|---|---|
| R1 | I_LED linear in DAC command over the full working range | §3 point 1 |
| R2 | I_LED independent of LED V_F and its tempco | §3 point 3 |
| R3 | Command range 0…3.28 V must map monotonically, with **0 V = LED off** | `[VERIFIED-CODE]` `config.DAC_IDLE_VALUE = 0` |
| R4 | Safe by construction: even a commanded full-scale must not exceed the LED rating — no reliance on software limits | engineering policy |
| R5 | Bandwidth ≥ the 1 kHz DAC update, with matched Red/IR delay | `config.FS_TIMER_HZ` |
| R6 | Both channels continuously on (isolated compartments — no time-multiplexing needed) | F-14 optical arrangement |

R6 is worth stating: because the two compartments are **optically isolated**,
there is no crosstalk to suppress and therefore **no reason to time-multiplex
the LEDs**. A shared-cavity oximeter would need alternating Red/IR drive; this
build does not. That removes an entire class of complexity (switching, settling,
sample-phase alignment) from the design.

---

## 4. Candidate architectures

### D-1 — DAC → series resistor → LED (passive)

```
MCP4725 ──[R]──▶|── GND
```

`I = (V_DAC − V_F(I)) / R`.

**Quantitatively fatal.** Sizing R so that full scale gives the Red design
current (16 mA at 3.28 V, V_F ≈ 2.0 V → R = 80.0 Ω), the current at the
project's nominal DC operating command of 1.5 V is **0.00 mA** — the command is
below V_F, so the LED is dark over the entire lower half of the range. The IR
channel with the same treatment (R = 99.0 Ω) yields 2.02 mA at the same command.
The two channels are dark/nonlinear in completely different places, so `R` is
meaningless. Sensitivity to V_F drift at full scale is **0.156 %/K** (Red) —
about 26× worse than D-4 (§7.5). Violates R1, R2, R3.

Also loads the MCP4725 with the full LED current, which §2.1 says is
`[UNKNOWN]`. **Reject.**

### D-2 — DAC → LM358P voltage buffer → series resistor → LED

Same exponential transfer function as D-1, merely buffered. Adds the op-amp
output-swing ceiling (3.50 V, §2.2) on top, and asks the op-amp to source the
full LED current from a 5 V rail — a capability that is `[UNKNOWN]` at 5 V
(§2.2 caveat). Violates R1, R2. **Reject.**

### D-3 — LM358P as a current source, LED in the op-amp output path, no transistor

```
V_cmd ─▶ (+)              ┌──▶|──[R_sense]──┬── GND
              LM358 ──────┘                 │
              (−) ◀───────────────────────-─┘
```

This *is* a real current source and satisfies R1 and R2. It fails on headroom
and drive:

- Compliance: `V_OUT = V_F + I·R_sense ≤ 3.50 V`. With Red V_F up to 2.2 V only
  1.30 V remains for the sense resistor, and that 3.50 V ceiling is specified at
  **RL ≥ 2 kΩ** — at a ~16 mA load the real dropout is larger and **not
  specified at VS = 5 V**.
- The op-amp carries the entire LED current, with source capability again only
  characterised at VS = 15 V.

`[ENGINEERING-INFERENCE]`: workable for the IR channel, marginal-to-unworkable
for Red. **Reject** — it fails exactly on the channel with the least headroom,
and its margin cannot be verified from the datasheet.

### D-4 — attenuator → LM358P + 2SC1815 emitter-sense current sink ✅ RECOMMENDED

```
              +5.00 V
                 │
                ─▼─  LED (anode to +5 V, no series resistor)
                 │
      ┌──────────┤ collector
      │        ╱ │
V_DAC │  ┌───▶│  2SC1815
 ──[Ra]┴─┤ LM358 ╲ │
      │  │  out──[R_B]── base
     [Rb]│                emitter ──┬── (−) input
      │  └── (+) input              │
     GND     (via R_a/R_b divider)  │
                              [R_sense]
                                    │
                                   GND
```

The op-amp forces `V(emitter) = V_cmd`, so `I_E = V_cmd / R_sense` and
`I_LED = I_C = I_E · h_FE/(h_FE+1)`.

Why this one:

- **The op-amp supplies only base current** (≤ 286 µA worst case, §7.4), so the
  unspecified-at-5 V output drive stops being a risk factor.
- **The op-amp's output ceiling stops constraining the LED.** The LED sits on the
  5 V rail above the collector; the op-amp output only has to reach
  `V_sense + V_BE + I_B·R_B` ≈ **2.68 V** against a 3.50 V ceiling.
- **Zero sensitivity to V_F.** V_F is absorbed by V_CE; it never enters the loop.
- **Both compartments get an identical, independent driver**, and one LM358P
  package (dual) serves both — amplifier A = IR, amplifier B = Red.
- No series resistor is needed with the LED. This is worth stating explicitly
  because it is a habitual addition: in a current-sink topology it only steals
  headroom.

Its one structural weakness — the base-current gain error — is precisely the
kind of error that cancels in `PI` and `R` (§3 point 2, §7.4).

### D-5 — same, but LED in the emitter leg

Requires `V_OUT ≥ V_sense + V_F + V_BE` ≈ 1.64 + 2.2 + 0.75 = **4.59 V** against
the 3.50 V ceiling. **Reject** on arithmetic.

### D-6 — Raspberry Pi PWM + RC filter instead of the DAC

Discards two verified, already-integrated MCP4725 modules and the entire
code-verified TX path (`hw/dac_manager.py`), and substitutes ripple and jitter
for a clean 12-bit command. **Reject** — no benefit against fixed hardware.

### D-7 — high-side PNP/PMOS source, or MOSFET pass device

A MOSFET would remove the base-current error entirely. **No MOSFET and no PNP
exists in the verified BOM** (`02` §2), so this is out of reach without new
parts. Noted as the upgrade path if the h_FE-related 0.14–1.41 % absolute-current
error ever becomes relevant (it does not, per §3 point 2).

### Comparison summary

| | D-1 passive | D-2 buffer+R | D-3 op-amp source | **D-4 sink (rec.)** | D-5 LED in emitter | D-6 PWM |
|---|---|---|---|---|---|---|
| Linear in command (R1) | ✗ | ✗ | ✓ | **✓** | ✓ | ~ |
| Immune to V_F (R2) | ✗ | ✗ | ✓ | **✓** | ✓ | ✗ |
| Red-channel headroom | ✗ | ✗ | marginal | **✓ 1.16 V** | ✗ −1.09 V | — |
| Op-amp carries I_LED | — | ✗ yes | ✗ yes | **✓ no (≤286 µA)** | ✗ yes | — |
| Loads the DAC output | ✗ heavily | ✓ no | ✓ no | **✓ no (≥20 kΩ)** | ✓ no | — |
| Thermal drift (Red) | 0.156 %/K | 0.156 %/K | ~0.006 %/K | **0.0059 %/K** | ~0.006 %/K | — |
| Parts on hand | ✓ | ✓ | ✓ | **✓** | ✓ | ✓ |
| **Verdict** | reject | reject | reject | **recommend** | reject | reject |

---

## 5. The binding constraint: LM358P common-mode range on a 5.00 V rail

This is the single most important design consequence of the verified rails, and
it is easy to miss.

### 5.1 The problem

The MCP4725 commands 0…**3.28 V**. The LM358P's guaranteed input common-mode
range on a 5.00 V supply is **0…3.50 V at 25 °C** and only **0…3.00 V over
0–70 °C**. Feeding the raw DAC output into the non-inverting input therefore
**exceeds the guaranteed CM range by +0.28 V over temperature**. Behaviour above
CM range is not specified — for the LM358 family it can include gain collapse or
output-phase anomalies, which in a current-sink loop means an uncontrolled LED
current. This is a safety issue, not a precision issue.

### 5.2 The fix: a 1:2 command attenuator

Insert `R_a`/`R_b` (equal values) at each op-amp input:

`V_cmd = V_DAC / 2` → full-scale **1.640 V**, against a 3.00 V worst-case CM
limit. Margin: 1.36 V. The attenuation is folded into the R_sense choice, so it
costs nothing in resolution beyond halving the LSB (§7.1).

### 5.3 Resulting headroom budget

| | Red | IR |
|---|---|---|
| V_F (max) | 2.2 V | 1.65 V |
| V_sense at full-scale command | 1.640 V | 1.640 V |
| **V_CE at full scale, 5.00 V rail** | **1.16 V** | **1.71 V** |
| V_CE at full scale, 4.75 V rail (−5 %) | 0.91 V | 1.46 V |
| V_CE at the nominal 1.5 V command | 2.05 V | 2.60 V |
| V_CE(sat) limit | ≤ 0.25 V @ 100 mA (far less at 16–20 mA) | same |
| Op-amp output required (max) | 2.68 V | 2.68 V |
| Op-amp output ceiling | 3.50 V | 3.50 V |

Every case clears saturation with ≥ 0.66 V of margin even on a 5 % low rail.
General design inequality for any future change:
**`V_rail − V_F(max) − I_max·R_sense ≥ 0.5 V`.**

---

## 6. Component values

All values below are **`[RECOMMENDED STARTING VALUE]`**, inheriting the weakest
label among their inputs. They are starting points for bench bring-up (§10), not
validated design values.

### 6.1 Sense resistors — the safety-by-construction choice

R_sense is chosen so that **a commanded full scale produces the maximum
permissible LED current**. Then no software fault can overdrive the LED (R4).

| Channel | Target ceiling | Ideal R | E24 choice | Resulting I at full scale | I at the nominal 1.5 V command |
|---|---|---|---|---|---|
| **Red** | 16.4 mA — inside the manufacturer's 16–18 mA "suggestion" band, under the 20 mA max | 1.640/0.0164 = 100.0 Ω | **100 Ω** | **16.40 mA** | **7.50 mA** |
| **IR** | 20 mA — the datasheet's photometric characterisation point (I_e 9.0 mW/sr typ), 5× under the 100 mA max | 1.640/0.020 = 82.0 Ω | **82 Ω** | **20.00 mA** | **9.15 mA** |

Both **1 %, 50 ppm/°C metal film, ≥ 1/4 W** — dissipation is 26.9 mW (Red) and
32.8 mW (IR), an ~8× margin. The tempco grade matters: R_sense tempco is the
dominant thermal term in the whole driver (§7.5).

Transfer functions:

```
I_red = V_DAC / 200      [A, V]        I_ir = V_DAC / 164
```

### 6.2 Attenuator

**R_a = R_b = 10 kΩ, 1 %**, per channel.

- DAC load 20 kΩ — light, which matters because the MCP4725's output drive is
  `[UNKNOWN]` locally (F-B3).
- Thévenin source 5 kΩ → with I_B max 250 nA, an added offset of 1.25 mV
  (§7.2).
- Ratio matching, not absolute value, sets the channel gain. 1 % parts give a
  ±1 % per-channel gain error — which cancels in PI and R (§3 point 2).
- If §7.2's offset proves limiting on the bench, 2.2 kΩ/2.2 kΩ cuts the I_B term
  5× — **but only if the MCP4725 can drive 4.4 kΩ**, which is
  `[MEASUREMENT-REQUIRED]` until the IC datasheet is obtained.

### 6.3 Base resistor

**R_B = 1 kΩ** between op-amp output and base.

Limits op-amp output current if the loop rails, and isolates the op-amp output
from the transistor's input capacitance. Worst case (h_FE = 70, IR channel) it
drops 286 µA × 1 kΩ = 0.29 V, already included in the 2.68 V figure of §5.3.

*Corrected (E-6):* the R_B drop is **not** `I_B × R_B` alone. If R_BE is fitted,
the op-amp also sources the bleed current through R_B, so the required output is

```
V_OUT = V_sense + V_BE + (I_B + I_RBE) · R_B
```

With R_BE = 10 kΩ the bleed adds 70 µA, i.e. another 70 mV across R_B. Omitting
it understates the drop and therefore overstates output headroom. Implemented in
`led_driver.compliance.opamp_output_required_v`.

**R_BE base-to-emitter: value NOT decided.** The LM358P's sink capability near
ground collapses to **12 µA min / 30 µA typ at V_O = 200 mV** (§2.2), so it is
weak at actively pulling the base down, and a bleed resistor would guarantee
turn-off independently of the op-amp's output stage. But the bleed is an
*additive* current that does not cancel in PI or R, and it creates a low-current
dead zone. See §7.3 for the 10 kΩ / 100 kΩ / DNP comparison. The decision is
`[MEASUREMENT-REQUIRED]` (E-2).

### 6.4 Capacitors

| Ref | Value | Placement | Purpose | Basis |
|---|---|---|---|---|
| **C1** | **100 nF**, per channel | divider midpoint → GND | reconstruction filter for the 1 kHz DAC staircase | §8.1 |
| **C2** | **DNP — footprint only** | op-amp output → inverting input | HF feedback path bypassing the transistor. The mechanism is sound; no value is justified without a measured loop response, so do not populate it. `[MEASUREMENT-REQUIRED]` | §8.3, E-3 |
| **C3** | **100 nF** ceramic | LM358P pin 8 (V+) → GND, at the pin | supply decoupling | TI layout guidance |
| **C4** | **10 µF** + **100 nF** | 5 V rail at the LED anodes | bulk reservoir; keeps the 37.60 mA of driver current (E-1) from modulating the shared rail — the only credible IR↔Red coupling path (§7.6) | §7.6 |
| **C5** | **100 nF** | each OPT101 V_S pin | per OPT101 layout guidance (0.01–0.1 µF) | `02` §2.4 |

**Do not** place a capacitor across R_sense — it sits inside the feedback loop
and would degrade phase margin. **Do not** hang a large capacitor directly on an
OPT101 output; that part tolerates ≤ 10 nF of direct capacitive load (`02` §2.4)
and needs a series isolation resistor if filtering is wanted there.

### 6.5 Bill of materials (both channels)

| Qty | Part | Note |
|---|---|---|
| 1 | LM358P (dual) | amp A = IR, amp B = Red |
| 2 | 2SC1815 | bin and pinout `[MEASUREMENT-REQUIRED]` |
| 1 | 100 Ω 1 % 50 ppm 1/4 W | Red R_sense |
| 1 | 82 Ω 1 % 50 ppm 1/4 W | IR R_sense |
| 4 | 10 kΩ 1 % | attenuators |
| 2 | 1 kΩ | R_B |
| 2 | **footprint only, value TBD** | R_BE — fit the pads; 10 kΩ / 100 kΩ / DNP compared in §7.3, decision is `[MEASUREMENT-REQUIRED]` (E-2) |
| 2 | 100 nF | C1 |
| 2 | **footprint only, DNP** | C2 — do not populate until a scope step response justifies a value (§8.3, E-3) |
| 1 | 100 nF | C3 |
| 1 | 10 µF + 1 × 100 nF | C4 |
| 2 | 100 nF | C5 |

---

## 7. Error budget for D-4

### 7.1 Quantisation

| | Red | IR |
|---|---|---|
| DAC LSB after the ÷2 attenuator | 0.400 mV | 0.400 mV |
| → LED current LSB | **4.00 µA** | **4.88 µA** |
| Full-scale current | 16.40 mA | 20.00 mA |

At the nominal 7.50 mA (Red) DC operating point, a PI of 1 % is an 75 µA
amplitude ≈ 19 LSB; a PI of 0.1 % is 7.5 µA ≈ **2 LSB**. **The 12-bit DAC, not
the driver, sets the floor on low-PI fidelity.** Below roughly PI = 0.2 % the
commanded waveform is visibly quantised. That is a property of the verified
hardware, not something this driver can improve.

### 7.2 DC offset — the error that does *not* cancel

`V_OS` (7 mV max) plus `I_B × 5 kΩ` (1.25 mV) = **8.25 mV** appears in series
with the command:

| | Red | IR |
|---|---|---|
| Worst-case current offset | **82.5 µA** | **100.6 µA** |
| as % of full scale | 0.50 % | 0.50 % |
| **as % of the 1.5 V operating point** | **1.10 %** | **1.10 %** |

Because it is *additive*, it shifts DC and therefore biases PI by up to ~1.1 %
relative. It is static, so a per-channel DC calibration removes it; it is
temperature-dependent at 7 µV/°C, so the residual after calibration is small
(§7.5). Typical V_OS is 3 mV, giving ~0.5 % — the 1.10 % is the guaranteed-worst
bound, not the expected value.

**Consequence for `config.DAC_IDLE_VALUE = 0`:** the code comments state that a
0 V command means "LEDs off". With this driver that is true only to within the
offset — a +7 mV worst-case V_OS commands ~70 µA (Red) rather than zero.
Optically that is ~0.4 % of full brightness and negligible for the simulator, but
the claim "LEDs off" is **approximate, not exact**, and if a genuine hard-off is
required it needs an enable/shutdown path, not a zero command. Recorded as
**F-B4**.

### 7.3 Turn-off behaviour — R_BE is NOT decided *(corrected, E-2)*

At V_cmd → 0 the op-amp output falls below V_BE(on) and base current ceases; no
active sink is required, which is fortunate given the 12 µA near-ground sink
limit (§2.2).

The original text then declared R_BE = 10 kΩ. That was premature: R_BE buys
turn-off certainty by injecting a bleed current that is *additive*, so it does
**not** cancel in PI or R. At the 7.50 mA Red operating point, with
V_BE(on) = 0.70 V (`led_driver.error_budget.rbe_comparison`):

| R_BE | Bleed | Dead zone (V_cmd) | Dead zone in DAC codes | PI error | AC stolen @ PI 1 % |
|---|---|---|---|---|---|
| 10 kΩ | 70.0 µA | 7.00 mV | 17 | **+0.94 %** | 0.034 % |
| 100 kΩ | 7.00 µA | 0.70 mV | 1 | **+0.094 %** | 0.0034 % |
| DNP | 0 | 0 | 0 | 0 | 0 |

Read the PI column as: a constant bleed leaves the AC amplitude alone but
shrinks the DC term, so the *measured* PI is inflated by
`DC_ideal / (DC_ideal − I_bleed)`. The dead-zone column is the low-current
distortion: below that command the transistor is off and the LED is dark, so
the bottom of any large-PI waveform is clipped.

Against that, DNP leaves turn-off entirely to the LM358 output pulling the base
down, and the datasheet guarantees only **12 µA** of sink current with the
output near ground. Whether that is enough, and what the residual LED current
at code 0 actually is, cannot be settled from datasheets.

**`[MEASUREMENT-REQUIRED]` — decide R_BE with a scope on the emitter node during
a real code-0 transition, not from this table.** Encoded as
`led_driver.error_budget.RBE_DECISION`, whose `.require_value()` raises
`MeasurementRequiredError` rather than returning a number.

### 7.4 Base-current gain error

`I_LED = (V_cmd/R_sense) · h_FE/(h_FE+1)`, i.e. the LED current is low by
`1/(h_FE+1)`:

| h_FE | error |
|---|---|
| 70 (worst of any bin) | −1.41 % |
| 200 (GR min) | −0.50 % |
| 400 (GR max) | −0.25 % |
| 700 (best) | −0.14 % |

**A *constant* per-channel `α = h_FE/(h_FE+1)` is a pure multiplicative gain, so
it divides out of `PI = AC/DC` and out of `R`** (§3 point 2). That is an
algebraic result about ratios, verified in
`tests/test_led_driver_error_budget.py`. It is not a hardware claim.

*Corrected (E-5):* the original text went on to call the second-order residual
"expected ≪ 1 %". That figure had no grounding and is withdrawn. Real h_FE is a
function of collector current *and* of junction temperature; the 2SC1815 bin
spread alone is 200–400 (70–700 across bins). Any h_FE variation **across the AC
swing**, or any thermal drift **correlated with the modulation**, survives the
ratio. As a scale check, a 20 000 /A current dependence of h_FE at the 7.5 mA
operating point already produces ≈ 0.12 % of PI error. The datasheet's
h_FE-vs-I_C curve is an unextractable image.

**`[MEASUREMENT-REQUIRED]` — the residual must be measured on the real
transistor, at the real operating point, over the real temperature range, before
any accuracy figure is quoted.** See
`led_driver.error_budget.HFE_CANCELLATION_CAVEAT` and the §10 linearity sweep.

Worst-case base current, h_FE = 70: 234 µA (Red), **286 µA (IR)** — far below any
plausible LM358P 5 V drive limit. Note that the op-amp must additionally source
the R_BE bleed through R_B if R_BE is fitted (E-6).

### 7.5 Thermal drift (Red channel)

| Contribution | Value |
|---|---|
| R_sense, 50 ppm/°C metal film | 0.0050 %/K |
| V_OS drift 7 µV/°C referred to V_sense = 0.75 V | 0.0009 %/K |
| **D-4 total** | **0.0059 %/K** |
| D-1 passive, for comparison (LED V_F tempco −2 mV/K) | 0.156 %/K |

**≈ 26× more stable than the passive alternative.** Over a 10 °C lab swing the
DC term moves 0.06 % instead of 1.6 % — the difference between a stable and an
unusable PI baseline.

### 7.6 Inter-channel coupling

Two paths exist:
- **Through the shared LM358P package:** channel separation 120 dB typ (1–20 kHz)
  → negligible.
- **Through the shared 5 V rail:** the real path. The driver draws up to 37.60 mA
  total from the same rail (E-1); rail sag modulated by the IR waveform would appear in
  the Red channel as a V_CE change. Because D-4's current is set by R_sense and
  not by the rail, first-order immunity is good, but C4 (§6.4) is what keeps it
  that way. **This is the coupling to check on the bench** (§10 step 6) — it is
  the only mechanism by which the two *optically isolated* compartments can still
  contaminate each other, and it would corrupt `R` directly.

### 7.7 5 V rail budget *(corrected, E-1)*

The original figure, 37.3 mA, summed the two LED currents and the op-amp
quiescent current. That is the wrong KCL. Per channel the current drawn *from
the rail* is

```
rail = I_C (through the LED) + I_RB (out of the op-amp output)
     = I_C + I_B + I_RBE
     = I_E + I_RBE
     = I_sense
```

so the base current and the R_BE bleed are already inside I_sense and must not
be dropped. Both channels at full scale plus LM358P quiescent (600 µA max per
amplifier × 2):

| Term | Current |
|---|---|
| Red channel, I_sense at V_cmd = 1.640 V | 16.40 mA |
| IR channel, I_sense at V_cmd = 1.640 V | 20.00 mA |
| LM358P quiescent, 2 amplifiers | 1.20 mA |
| **Total** | **37.60 mA** |

Verified invariant in `tests/test_led_driver_power.py`: the total is unchanged
across h_FE ∈ {70, 200, 400, 700} and R_BE ∈ {DNP, 10 kΩ, 100 kΩ} to within
floating-point summation order. h_FE and R_BE redistribute current between the
LED branch and the op-amp branch; they do not change what the rail supplies —
but they *do* reduce what reaches the LED.

Well within a Raspberry Pi 4 header 5 V supply.

---

## 8. Dynamic behaviour

### 8.1 Reconstruction filter (C1)

The DAC emits a 1 kHz staircase and the RX side samples at 100 Hz, so the update
tone is far below Nyquist and folds down rather than appearing as visible
ripple. Either way it lands on the DC term, which is precisely the term PI
divides by, so filtering it on the TX side is worth doing.

*Corrected (E-4):* the original text said the 1 kHz component "aliases to exactly
DC". **Do not report that as a guarantee.** It is true only for two ideal,
phase-locked clocks. Three things break it here:

1. **Phase.** The fold to 0 Hz assumes a fixed phase relationship between the
   DAC update instants and the ADC sample instants. Nothing in this system
   enforces one.
2. **Clock drift.** The TX timer and the Grove ADC sampling derive from
   independent oscillators. A relative error of **100 ppm** puts the alias
   anywhere in **0–0.2 Hz** — inside the baseline band that feeds the DC term.
   **500 ppm** reaches **1 Hz**, inside the 0.5–4 Hz heart-rate band, where it
   is indistinguishable from a pulse.
3. **Jitter.** Userspace timer jitter under a non-real-time Linux kernel means
   the update train is not a clean comb, so its energy spreads across frequency
   instead of collapsing onto a single line.

`led_driver.error_budget.alias_band_hz(1000, 100, tolerance_ppm)` computes the
band the alias can occupy; `overlaps_band` tests it against `PPG_HR_BAND_HZ` and
`PPG_BASELINE_BAND_HZ`. The real spectrum is **`[MEASUREMENT-REQUIRED]`** —
capture it on the assembled system, do not assume it.

With R_th = 5 kΩ:

| C1 | f_c | τ | \|H(1 kHz)\| | \|H(20 Hz)\| | phase @ 20 Hz |
|---|---|---|---|---|---|
| 10 nF | 3183 Hz | 0.05 ms | 0.954 (−0.4 dB) | 1.0000 | −0.4° |
| **100 nF** | **318 Hz** | **0.50 ms** | **0.303 (−10.4 dB)** | **0.9980** | **−3.6°** |
| 220 nF | 145 Hz | 1.10 ms | 0.143 (−16.9 dB) | 0.9906 | −7.9° |

**100 nF selected.** Context for why −10 dB suffices: the staircase step itself
is already tiny. At the largest waveform in the model (AC = 0.30 V, PI 20 %, at
2 Hz) the command changes by **3.77 mV per 1 ms step = 0.251 %** of a 1.5 V DC
command; at a realistic AC = 45 mV, 1.2 Hz it is **0.34 mV = 0.023 %**. A further
−10 dB puts the residual at ~0.08 % and ~0.007 % respectively.

**Matching matters more than the absolute value.** The two channels' C1 must be
the same value and reasonably matched, or their group delays differ and `R`
acquires a phase-dependent error. A 5 % mismatch gives a **25 µs** delay skew =
**0.009° at 1 Hz** — negligible. Any value between 10 nF and 220 nF is defensible
provided **both channels use the same one**.

### 8.2 Slew rate

Worst case is a full-scale command step. After C1 the input slews at
**0.0033 V/µs** against the LM358P's 0.3 V/µs — a **91× margin**. No slew
limiting, and the driver's step response is set by the deliberate 0.5 ms
filter time constant, not by any op-amp limitation.

### 8.3 Loop stability — C2 is DNP *(corrected, E-3)*

The emitter follower inside the loop adds phase lag. The mechanism the original
text described is real: a C2 across R_B creates a direct feedback path around the
transistor above `1/(2π·R_B·C2)`, and above that corner the amplifier runs as a
plain unity-gain follower, which the LM358 family is unconditionally stable in.
The transistor's f_T ≥ 80 MHz places its own pole far above audio.

What the original text should not have done is **name a value**. C2 = 1 nF was
presented as a "recommended starting value"; the corner it implies (159 kHz) was
chosen by inspection, not computed from a loop model. The correct value depends
on the loop gain, on β at the actual operating point, and on layout parasitics —
none of which are known, and none of which a datasheet can supply.

**Decision: fit the C2 footprint, leave it `DNP`.**
`[MEASUREMENT-REQUIRED]` — populate it only after a scope step response on the
emitter node (§10 step 4) or a validated loop model shows the actual phase
margin. If it is needed, 330 pF … 4.7 nF is the range to sweep. Encoded as
`led_driver.error_budget.C2_COMPENSATION`, whose `.require_value()` raises
`MeasurementRequiredError`.

### 8.4 DAC code tables

Using `calibration.py`'s convention `code = int(V/3.28 × 4095)`:

| Target I | Red (R = 100 Ω) | IR (R = 82 Ω) |
|---|---|---|
| 2.0 mA | 499 | 409 |
| 5.0 mA | 1248 | 1023 |
| 7.5 mA | 1872 | 1535 |
| 10.0 mA | 2496 | 2047 |
| full scale | 4094–4095 (16.40 mA) | 4095 (20.00 mA) |

Note that 1.5 V → code 1872 reproduces exactly the figure already documented in
`core/signal_engine.py` after the Stage A correction, so the driver's operating
point aligns with the existing code without any software change.

*Corrected (E-7):* the original note called the 4095-vs-4096 discrepancy
"≈ ¼ LSB". It is **exactly 1 LSB at code 4095** — 0.80078 mV, 0.0244 % of full
scale. The MCP4725 has 4096 levels and a maximum code of 4095; the two
conventions (`code/4096 × V_FS`, the ratiometric one, versus
`code/4095 × V_FS`, full-scale-at-max-code) agree at code 0 and diverge linearly
to a full LSB at the top code. `calibration.py` uses the second,
`config.DAC_V_PER_STEP` the first. Quantified by
`led_driver.dac.convention_discrepancy`. Still a pre-existing software
inconsistency, out of scope for this document, flagged so it is not rediscovered
as a driver defect.

---

## 9. What this design deliberately does not determine

**The optical operating point.** How much LED current produces a usable OPT101
output depends on emitter–detector distance, aperture, chamber reflectivity, and
OPT101 responsivity at 620–625 nm and 875 nm — **none of which is established**
(`02` §4 items 1, 2). The OPT101 output ceiling is ≈ 1.98–2.13 V on a 3.28 V
supply with a 5–10 mV dark offset (`02` §2.4), and the DC operating point should
land near 1.0–1.2 V to leave symmetric AC room.

This design fixes the **electrical envelope** (0 → 16.4 mA Red, 0 → 20.0 mA IR,
linear in the DAC command). Placing the optical operating point inside that
envelope is done by **choosing the DC command**, per §8.4, and is
`[MEASUREMENT-REQUIRED]`. Only if the required current falls outside the envelope
should R_sense be changed — and then §5.3's headroom inequality must be
re-checked.

**Two unresolved RX-side items that bound the TX design and are recorded here as
findings, not solved:**

- **F-B5 `[MEASUREMENT-REQUIRED]`** — the OPT101's pin 4 → pin 5 strap, which
  connects the internal 1 MΩ feedback resistor, is unverified on this build
  (`02` §4 item 1). Without it the part is not an operating transimpedance
  amplifier and no LED current will produce a sensible output. **Check this
  before concluding anything about the driver from an RX measurement.**
- **F-B6 `[ENGINEERING-INFERENCE]`** — the OPT101's ~14 kHz bandwidth feeding a
  100 Hz sampler with no anti-alias filter folds wideband noise into the
  measurement band. This belongs to the RX front-end design, not to Prompt 03,
  but it directly limits the SNR achievable from any TX driver and should be
  addressed there.

---

## 10. Bring-up procedure (required before any value here is trusted)

Every `[RECOMMENDED STARTING VALUE]` above becomes a verified value only after
this sequence. Steps 1–2 must be done before power is applied to a built board.

1. **Confirm the 2SC1815 pinout** with a DMM diode test (both junctions from the
   base). Do not rely on the assumed E-C-B ordering. *(Closes `02` §4 item 5.)*
2. **Confirm the Red LED polarity** — its datasheet has no pin diagram. Diode
   test, or a brief 1 kΩ-limited 5 V probe.
3. **Static transfer check, per channel.** Command DAC codes 0, 499, 1248, 1872,
   2496, 4095. Measure V across R_sense with a DMM. Pass: measured
   `I = V_sense/R_sense` within ±2 % of `V_DAC/(2·R_sense)` at every point above
   1 mA, and monotonic. Fail → check the attenuator ratio and op-amp CM range
   first.
4. **Step response.** Command a 0 → half-scale step, scope on R_sense. Pass:
   settles within ~2 ms with no overshoot > 10 % and no ringing. Fail → adjust
   C2 (§8.3).
5. **Turn-off.** Command code 0. Pass: V_sense ≤ 10 mV (i.e. ≤ 100 µA), and the
   LED is visually dark (Red) / reads dark on the OPT101 (IR). Records the actual
   offset of §7.2 for that channel.
6. **Cross-channel check — the important one.** Drive IR with a full-amplitude
   waveform while Red holds a constant DC command. Pass: Red's V_sense shows
   < 0.1 % modulation at the IR frequency. Fail → C4 / rail impedance (§7.6).
7. **Thermal soak.** Hold both channels at the DC operating point for 30 minutes
   from cold. Pass: current drift < 0.2 %. This validates §7.5 in situ.
8. **Only then** set the optical operating point per §9 and re-run the RX-side
   AC/DC calibration.

---

## 11. Findings raised by this document

| ID | Label | Finding |
|---|---|---|
| **F-B1** | `[UNKNOWN]` | The as-built LED driver topology is unknown — no schematic exists locally (`02` §4 item 10). Everything in this document is a candidate design. |
| **F-B2** | contradiction | `docs/architecture/PHASE_4_DUAL_DAC_TX_AND_LED_DRIVER.md` states ADC `0x04`, "A0 = IR / A1 = Red / A2 obsolete", `DAC_FULLSCALE_V = 3.2`, `ADC_VOLTAGE_REF = 3.3` — all superseded by F-10, F-13, F-15, F-16. Recorded, **not edited** (read-only per `00` §2). Its *concept* (op-amp + pass device current sink) is sound and is adopted as D-4. |
| **F-B3** | `[UNKNOWN]` | `docs/ds_linhkien/MCP4725-Data-Sheet.pdf` does not exist locally despite being named in the task's read list. The DAC's output drive capability is therefore unestablished, which is why §6.2 chooses a light 20 kΩ load. |
| **F-B4** | `[ENGINEERING-INFERENCE]` | `config.DAC_IDLE_VALUE = 0` is documented as "LEDs off". Under D-4 that is exact only to within the op-amp offset (~70 µA worst case, ~0.4 % of full brightness). Approximate, not exact. |
| **F-B5** | `[MEASUREMENT-REQUIRED]` | OPT101 pin 4 → pin 5 strap unverified (carried from `02` §4 item 1) — blocks any RX-based validation of the driver. |
| **F-B6** | `[ENGINEERING-INFERENCE]` | No anti-alias filter between the ~14 kHz OPT101 and the 100 Hz sampler. RX-side issue; bounds achievable SNR. |
| **F-B7** | `[MEASUREMENT-REQUIRED]` | 2SC1815 h_FE bin and pinout unconfirmed (`02` §4 items 4, 5). The bin does **not** affect PI or R (§7.4); the pinout must be confirmed before power-on. |
| **F-B8** | `[VERIFIED-DATASHEET]` | New evidence captured for this document and not present in `02`: the Red LED's **"Suggestion Using Current" = 16–18 mA**, which is the basis for the 16.40 mA Red ceiling rather than the 20 mA absolute maximum. `02` §2 should be extended with it. |

---

## 12. Verification of this document

Every numeric result quoted above was computed by a single script rather than by
hand, and the script was executed:

- Script: `scratchpad/stage_b_calc.py` (session scratchpad; not added to the repo)
- Run: `.venv/bin/python .../stage_b_calc.py` — completed, output transcribed
  into §4–§8 without modification.
- Inputs to that script are only the values in §2, each carrying its label.

No file in the project source tree was modified in producing this document.
