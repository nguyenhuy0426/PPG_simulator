# Phase 4 — Dual-DAC TX Path & LED-Driver Analysis

Date: 2026-07-12
Status: software path implemented and unit-tested; **no hardware measurement performed** (development machine is x86_64, not the Pi).

Evidence tags used below:
- **[VERIFIED-CODE]** — read directly from project source or installed library source
- **[VERIFIED-USER]** — hardware fact stated by the user (source-of-truth doc)
- **[DATASHEET-CLASS]** — standard published characteristics of a common part; the exact vendor/variant in this project is unverified — confirm against the actual part's datasheet
- **[INFERENCE]** — engineering calculation/reasoning from the above; not measured
- **[UNKNOWN]** — no evidence available

---

## 1. Verified dual-DAC TX path

### 1.1 Topology [VERIFIED-USER]

One Raspberry Pi 4 + one Seeed Grove Base HAT perform TX, RX, processing, and UI.
On I2C bus 1 (`/dev/i2c-1`):

| Address | Device | Role |
|---------|--------|------|
| 0x60 | MCP4725 | **IR TX** (fixed mapping — never swap) |
| 0x61 | MCP4725 | **Red TX** (fixed mapping — never swap) |
| 0x04 | Grove Base HAT STM32 ADC | RX (Phase 5): OPT101 IR → A0, OPT101 Red → A1, A2 obsolete |

DAC measured full-scale = **3.2 V** (`DAC_FULLSCALE_V`, single source of truth in `config.py`). The ADC reference stays a separate constant (`ADC_VOLTAGE_REF = 3.3`).

### 1.2 Actual driver API [VERIFIED-CODE]

`adafruit-circuitpython-mcp4725` 1.4.21 (read from `~/.local/lib/python3.12/site-packages/adafruit_mcp4725.py`):

- `MCP4725.__init__(i2c, address)` wraps the bus in `adafruit_bus_device.i2c_device.I2CDevice`, which **probes the address at construction** — a missing DAC raises at init, not at first write.
- `raw_value = <0..4095>` → `_write_fast_mode()` → one **2-byte fast-mode I2C write** (`0x00|(val>>8), val&0xFF`). On the wire: START + address byte + 2 data bytes + STOP.
- The payload buffer `_BUFFER` is a **class-level attribute shared by all MCP4725 instances**, and the library source states: *"Note this is not thread-safe or re-entrant by design!"* Both project DAC objects share it.
- `I2CDevice` locks the `busio.I2C` object only for the duration of each single transaction; it provides no cross-transaction or cross-library exclusion.

### 1.3 Write path, cadence, and thread ownership [VERIFIED-CODE]

- `SignalEngine` (singleton) runs one daemon thread ("SignalGen"): PPG model @ 100 Hz → 10× linear interpolation → ring buffer → `DACManager.set_values(ir, red)` at the `FS_TIMER_HZ = 1000` Hz cadence, paced by `time.perf_counter()` polling with 0.5 ms sleeps.
- `set_values()` writes **IR (0x60) first, then Red (0x61)** — two sequential I2C transactions per tick. Red therefore always lags IR by one transaction time + Python overhead within the same tick. This skew is deterministic in order but **unmeasured in magnitude** (see §4).
- Writers of the DAC path:
  1. SignalGen thread (sole writer while a simulation runs);
  2. the Tk main thread — `CalibrationFrame.periodic_update()` writes a test sine directly, and `stop_simulation()`/`begin()` write the idle value. `CalibrationFrame.on_show()` stops the engine first, so overlap is excluded by convention only (thread join has a 2 s timeout).
- **Phase 4 correction:** because two threads can reach the driver and the driver's shared `_BUFFER` is not thread-safe, `DACManager` now serializes all writes with an internal `threading.Lock`. This is also the single serialization point for the TX side of the bus going into Phase 5.

### 1.4 Failure and safe-state behavior after Phase 4 [VERIFIED-CODE]

- Init failure (missing library, no bus, DAC absent → probe NACK): `begin()` returns `False`, manager stays not-ready, all writes become safe no-ops. Unit-tested.
- Runtime write failure is handled **per channel**: an IR write exception no longer skips the Red write. Per-channel error counters accumulate; repeated errors are logged once per 1000 failures (~1 line/s at 1 kHz) instead of flooding the log. Unit-tested with simulated NACKs.
- Safe idle/shutdown: `DAC_IDLE_VALUE = 0` (0 V). `begin()`, `stop_simulation()`, and process exit (`engine.shutdown()`) park both channels at 0 V. Rationale: in the LED-driver concept (§3) LED current is proportional to the DAC voltage, so the previous behavior of parking at mid-scale (2048 ≈ 1.6 V) would have held both LEDs at ~half drive indefinitely. 0 V = LEDs off. Unit-tested in dry-run.
- Dry-run (`PPG_DRY_RUN=1`): `begin()` succeeds, writes update `last_ir`/`last_red` bookkeeping only, no hardware imports occur. Unit-tested.

---

## 2. Shared-bus analysis (one Pi, one HAT)

### 2.1 Facts

- All three devices (0x60, 0x61, 0x04) share `/dev/i2c-1`. [VERIFIED-USER]
- The DAC path uses Blinka `busio.I2C`; the Grove ADC (Phase 5) uses Seeed's `grove.adc`, a separate library with its own file descriptor on the same adapter. [VERIFIED-CODE for the DAC side; the grove library source was not available on this machine — its exact transaction shape is to be verified in Phase 5.]
- The Linux I2C core serializes **individual transactions** per adapter, so interleaved writes/reads from different fds cannot corrupt each other's transactions. Multi-transaction sequences are *not* atomic across libraries. [DATASHEET-CLASS / kernel behavior]

### 2.2 Timing budget [INFERENCE — calculation only, not measured]

One MCP4725 fast-mode write ≈ 3 bytes ≈ 27 SCL clocks + START/STOP:

| Bus clock | Per DAC write | Both DACs / 1 ms tick | Bus utilization (TX only) |
|-----------|--------------|----------------------|---------------------------|
| 100 kHz (Pi default) | ≈ 0.28 ms | ≈ 0.56 ms | ≈ 56% |
| 400 kHz (`dtparam=i2c_arm_baudrate=400000`) | ≈ 0.07 ms | ≈ 0.14 ms | ≈ 14% |

The actual bus clock on the target Pi is **[UNKNOWN]** (check `/boot/firmware/config.txt` or measure with a logic analyzer).

**Implication for Phase 5:** at the 100 kHz default, the two TX writes alone consume roughly half of each 1 ms tick. A Grove ADC register read (register write + 2-byte read, ≈ 45 clocks ≈ 0.45 ms/channel at 100 kHz) for two channels would push the combined TX+RX traffic past 1 ms per tick — **1 kHz TX + per-tick RX does not fit at 100 kHz**. Phase 5 must therefore (a) verify/raise the bus clock to 400 kHz, and/or (b) sample the ADC at a decoupled lower rate (e.g., 100–200 Hz, ample for 0.5–10 Hz PPG bandwidth), and (c) keep a single owner per direction: SignalGen thread owns TX; the Phase 5 acquisition thread must own RX and must never call into the DAC path. These numbers are calculations; **do not treat them as validated timing until measured** (§4).

### 2.3 Jitter

The 1 kHz cadence is produced by a userspace polling loop with `time.sleep(0.0005)` under a non-realtime Linux scheduler. Tick-to-tick jitter, worst-case latency, and the IR→Red skew are **unmeasured**. No timing success is claimed. [UNKNOWN until measured]

---

## 3. LED-driver stage analysis

### 3.1 Target concept (design intent, from Phase 1 master design)

```
MCP4725 DAC (0..3.2 V) ──► op-amp control stage ──► NPN/MOSFET (if required)
                                                        │
                                                   LED (Red or IR)
                                                        │
                                                   R_sense ──► GND
                     op-amp feedback forces V(R_sense) = V_DAC
                     ⇒ I_LED = V_DAC / R_sense
```

One such stage per channel (IR from 0x60, Red from 0x61). The DAC voltage is a *current command*, which is why 0 V idle = LED off is the mandatory safe state.

### 3.2 Available evidence

- Parts on hand: LM358 dual op-amp, 3 mm Red LED, 3 mm IR LED, OPT101 photodiodes, 2× MCP4725. [VERIFIED-USER, Phase 1 BOM]
- LED wavelengths, forward voltages, and current ratings: **[UNKNOWN]** — not documented anywhere in the project.
- LM358 supply rail in the actual circuit: **[UNKNOWN]** — the Pi header offers 3.3 V and 5 V, but no schematic exists.
- Sense-resistor value, divider values, transistor part: **[UNKNOWN]** — never chosen.

### 3.3 LM358 sufficiency [DATASHEET-CLASS characteristics + INFERENCE]

Standard LM358 characteristics (verify against the exact vendor/variant used):
single-supply 3–32 V; input common-mode range ≈ 0 to V_CC − 1.5 V; output swings to near 0 V but only to ≈ V_CC − 1.5 V high; output current capability is tens of mA short-circuit (not a guaranteed precision drive); GBW ≈ 1 MHz, slew ≈ 0.3–0.6 V/µs; class-B output stage with crossover distortion at low output currents.

- **If powered from 3.3 V:** usable input common-mode range ends around 1.8 V. DAC commands span 0–3.2 V, so the control stage would misbehave for commands above ≈ 1.8 V. Output swing is similarly insufficient. **A 3.3 V rail is not sufficient for the full command range.**
- **If powered from 5 V:** input common-mode (≈ 0–3.5 V) covers the full 0–3.2 V command range, and output swing (≈ 3.5 V) is adequate for driving a transistor base/gate. Feasible for the *control* function.
- **Headroom [INFERENCE]:** with V(R_sense) = V_DAC up to 3.2 V, the remaining headroom on a 5 V rail is ≈ 1.8 V for LED forward voltage plus transistor drop. Typical red LEDs need ≈ 2 V — likely insufficient at full-scale command. In practice the PPG operating region (DC ≈ 1.5 V ± 0.3 V) fits, but a full-range design needs either a scaled command (divider before the op-amp so V_sense is a fraction of V_DAC), a smaller sense voltage budget, or a higher LED supply. This must be resolved with the real LED parameters.
- **Bandwidth/slew:** irrelevant constraint for ≤ 10 Hz PPG envelopes updated in 1 kHz steps; the binding constraints are common-mode range, swing/headroom, and drive current.
- **Is an external transistor required?** It depends on the target LED current, which is unknown. If the target is ≲ 10 mA, direct LM358 drive is conceivable; at typical pulse-oximeter LED currents (tens of mA) an external NPN/MOSFET inside the feedback loop is required. **I am not sure based on the currently available evidence.**
- **Final component values** (R_sense, divider, transistor choice, per-channel current targets): **I am not sure based on the currently available evidence.** These require the LED datasheets or bench characterization first.

No LED-driver circuit values, part numbers, optical powers, or bench results are claimed in this phase.

---

## 4. Hardware validation plan (NOT RUN — no hardware on this machine)

### 4.1 Logic analyzer (SDA/SCL on /dev/i2c-1, during a running simulation)

1. ACK (not NACK) on address 0x60 and 0x61 for every write.
2. Payload = fast-mode format: first byte `0x0V` (upper nibble 0), i.e. `(code >> 8)`, second byte `code & 0xFF`; spot-check against `last_ir`/`last_red` logged values.
3. Actual DAC update interval: nominal 1.000 ms; record mean, std-dev, min/max over ≥ 10 s.
4. IR(0x60) → Red(0x61) gap within one tick: record distribution.
5. Actual SCL clock frequency (resolves the 100 vs 400 kHz unknown in §2.2).
6. Any retries/aborted transactions or clock stretching.

### 4.2 Oscilloscope (per DAC output, then per LED-driver node once built)

Per channel (probe DAC OUT test point, ground at HAT GND):
1. DC level with simulation stopped: expect 0 V (safe idle) — this is the new Phase 4 behavior.
2. Running NORMAL condition: DC ≈ 1.5 V region, AC amplitude per configured PI; compare against `dac_voltage_to_code` predictions.
3. Pulse period consistent with configured HR.
4. No clipping at 0 V or at the 3.2 V measured full-scale.
5. Step settling on 1 kHz updates (MCP4725 output-buffer settling; staircase visible or filtered).
6. Once the driver stage exists: verify no op-amp saturation across the command range, and measure V(R_sense) tracking V_DAC.

Every item above is **NOT RUN** in Phase 4. Nothing in this document constitutes hardware validation.
