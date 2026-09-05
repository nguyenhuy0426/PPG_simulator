# Transistor identity: 2SC1815 vs 2N4401 — unresolved, and what depends on it

Status: **OPEN — requires a physical measurement by the operator.**
Last reviewed: 2026-09-05

## 1. The contradiction

The repository does not agree with itself about which NPN sits in the LED
current sink.

| Source | Says | Weight |
|---|---|---|
| `docs/ds_linhkien/2SC1815L-GR.PDF` | 2SC1815-GR | Datasheet physically present in the repo |
| `led_driver/params.py` (`TransistorSpec`, `Q_2SC1815`) | 2SC1815 | The values every calculation in `led_driver/` uses |
| `docs/hardware/PPG_PROTOTYPE_{SCHEMATIC,BOM,WIRING_AND_TEST_POINTS}.md` | 2SC1815 | Electrical documentation |
| `docs/superpowers/ppg_design_audit/*` | 2SC1815 | The audit the driver values were derived in |
| `docs/system_3d/README.md`, `docs/system_3d/build_system.py` | 2N4401 | 3D case model labels only — no electrical model behind them |
| Operator statement (2026-09) + hand-drawn schematic | 2N4401 | The part actually soldered, per the user |

There is **no 2N4401 datasheet in `docs/ds_linhkien/`**. Nothing in this
repository can therefore verify a single 2N4401 parameter. Any 2N4401 number
quoted anywhere in these docs is `[UNVERIFIED]` until that PDF is added.

## 2. What actually depends on the answer

Two things, and only two.

### 2.1 The sense resistor: does NOT depend on it (verified)

`I_LED = alpha * V_sense / R_sense` with `alpha = hFE/(hFE+1)`. At hFE >= 50
alpha is already >= 0.980, so the transistor's current gain moves the LED
current by well under 1 %. V_BE only enters constraint (2), the op-amp output
headroom, which has volts of margin at these levels.

Swept with the repository's own `led_driver.compliance.compliance_report`,
CASE B (with the /2 divider, V_sense = 1.64 V, R_IR = 82R, R_Red = 100R):

| Assumed device | hFE_min | V_BE | I_IR | I_Red | All 3 constraints |
|---|---|---|---|---|---|
| 2SC1815-GR (datasheet in repo) | 70 | 0.75 V | 19.72 mA | 16.17 mA | PASS |
| 2N4401 commonly cited `[UNVERIFIED]` | 100 | 0.85 V | 19.80 mA | 16.24 mA | PASS |
| Pessimistic bound | 50 | 0.95 V | 19.61 mA | 16.08 mA | PASS |

Spread across the entire plausible range: **0.19 mA on IR, 0.16 mA on Red
(under 1 %)**. The published values R_IR = 82R and R_Red = 100R stand
regardless of which of the two devices is fitted. Do not re-derive them
pending the datasheet.

### 2.2 The pinout: DOES depend on it, and it is the real risk

TO-92 packages of these two parts are **not** pin-compatible.

| Device | TO-92 pin order (flat/printed face toward you, leads down) |
|---|---|
| 2SC1815 (Toshiba) | **E - C - B** |
| 2N4401 (ON Semi / Fairchild lineage) | **E - B - C** |

`[UNVERIFIED — general component knowledge, no 2N4401 datasheet in this repo]`

The centre and right pins swap. Building the board to the wrong pinout puts
the LED current into the base and the op-amp feedback onto the collector: the
loop does not regulate, and the base-emitter junction can be driven into
reverse breakdown (`V_EBO` is only ~5 V — see `led_driver/faults.py`, which
already models this fault). This is a build-destroying error, not a tuning
error.

## 3. Required action by the operator (cannot be done from software)

1. Read the part marking on the actual transistor body with a magnifier.
   Toshiba prints `C1815` plus a bin letter (`GR`, `Y`, `BL`); ON Semi prints
   `2N4401` or `4401`.
2. Confirm the pinout with a DMM in diode mode, on the board, before powering
   anything:
   - Find the pin that reads ~0.6-0.7 V forward to **both** other pins with
     the red (+) lead on it. That pin is the **base**.
   - Of the remaining two, the one with the slightly *higher* forward drop
     from the base is normally the **collector**.
   - Cross-check: the emitter is the pin that goes to R_sense and to the
     op-amp inverting input; the collector must be the pin that goes to the
     LED cathode.
3. Add the datasheet of whatever is actually fitted to `docs/ds_linhkien/`.
4. Only then update `led_driver/params.py::TransistorSpec`. Until step 3 is
   done, changing those numbers would be fabricating datasheet values.

## 4. Documentation policy applied here

`docs/system_3d/` labels the 3D case model only; it carries no electrical
model and was the sole source asserting 2N4401. Its labels now point at this
file instead of asserting a part number the repository cannot verify.
`led_driver/` and `docs/hardware/` keep 2SC1815 because that is the datasheet
on disk and the source of every number in them — with a pointer to this file
recording that the operator has stated otherwise.

Neither name is being presented as confirmed. The design is insensitive to
the choice (section 2.1); the wiring is not (section 2.2).
