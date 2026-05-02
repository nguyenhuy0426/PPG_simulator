# CLAUDE.md — PPG Signal Simulator (Raspberry Pi 4) Architecture Guide

> **AI-generated architecture documentation for the PPG Signal Simulator.**
> Python port from the ESP32-S3 C++ firmware to Raspberry Pi 4.

---

## 1. Project Overview

**PPG Signal Simulator** is a Python application for Raspberry Pi 4 that generates realistic dual-channel PPG signals. It synthesizes IR and Red PPG waveforms using a 3-component Gaussian model and outputs them via dual MCP4725 DACs. The GUI runs on a 7-inch HDMI display using Pygame.

### Key Specifications

| Feature | Value |
|---------|-------|
| Platform | Raspberry Pi 4 (Ubuntu 24.04 LTS) |
| Language | Python 3.10+ |
| Display | 7" HDMI (1024×600), Pygame full-screen |
| DAC | Dual MCP4725 (12-bit, I2C) |
| ADC | Grove Base Hat (12-bit, STM32 I2C) |
| Controls | 1 MODE button (GPIO17) + 1 potentiometer + keyboard/mouse |
| Model Rate | 100 Hz |
| DAC Rate | 1 kHz |
| Architecture | Python threading (main + generation) |

---

## 2. Hardware Interface

### Pin Assignments (BCM)

```
Raspberry Pi 4 Pin Map
═══════════════════════════════════════
MCP4725 DACs (I2C Bus 1):
  GPIO2 → SDA, GPIO3 → SCL
  0x60 = IR Channel, 0x61 = Red Channel

Grove Base Hat ADC:
  I2C addr 0x04, Channel A0 → Potentiometer (5 kΩ)

Push Button (Active LOW, pull-up):
  GPIO17 → BTN_MODE

Display:
  HDMI → 7" screen (1024×600)
```

---

## 3. Software Architecture

### Threading Model

```
Main Thread                    Background Thread (daemon)
═══════════════                ════════════════════════════
Pygame loop @ 60 FPS           signal_engine._generation_loop()
├── Events (keyboard/mouse)    ├── PPGModel @ 100 Hz
├── Button/ADC polling         ├── 10× interpolation → 1 kHz
├── Display rendering          ├── Ring buffer (1024)
└── State machine              └── MCP4725 DAC writes
```

### Module Dependency

```
main.py
├── config.py                    Constants, pins, colors
├── config_store.py              JSON persistence
├── core/signal_engine.py        Generation thread + DAC
│   ├── models/ppg_model.py      3-Gaussian PPG model
│   └── hw/dac_manager.py        Dual MCP4725
├── core/state_machine.py        State flow
├── core/param_controller.py     Limits & validation
├── hw/adc_reader.py             Grove ADC
├── hw/button_handler.py         GPIO button
├── ui/pygame_display.py         Pygame GUI
└── comm/logger.py               Logging
```

---

## 4. Signal Generation Pipeline

```
PPGModel (100 Hz) → 10× Interpolation → Ring Buffer (1 kHz) → DACManager (2× MCP4725)
     ↑                                                            ↓
generate_both_samples()                                    0–3.3V analog
returns IR, Red, display_IR                                (0–4095, 12-bit)
```

### PPG Model (ppg_model.py)

3-component Gaussian decomposition:
1. **Systolic peak** — position 15%, σ=0.055
2. **Dicrotic notch** — position 28%, σ=0.02 (subtracted)
3. **Diastolic peak** — position 35%, σ=0.10

**Dual-channel**: SpO₂ determines R-ratio → AC_red = AC_ir × R.
**Respiratory modulations**: BW (baseline), AM (amplitude), FM (RSA).

---

## 5. Key Data Structures

### PPGParameters (ppg_model.py)
```python
class PPGParameters:
    condition: int        # 0-5
    heart_rate: float     # BPM (40-180)
    perfusion_index: float # PI % (0.5-20)
    spo2: float           # SpO2 % (85-100)
    resp_rate: float      # RR BPM (0-60)
    noise_level: float    # 0.0-0.10
    dicrotic_notch: float # 0.0-1.0
    amplification: float  # 0.5-2.0
```

### State Machine (state_machine.py)
```
INIT → SELECT_CONDITION → SIMULATING ↔ PAUSED
                               ↓
         (MODE cycles back to CONDITION_SELECT → STOP)
```

### Edit Modes
```
CONDITION_SELECT → EDIT_HR → EDIT_PI → EDIT_SPO2 → EDIT_RR → EDIT_NOISE → (cycle)
```

---

## 6. Dry-Run Mode

Activated via `--dry-run` flag or `PPG_DRY_RUN=1` env var.
- **DACManager**: Accepts writes but doesn't access I2C
- **ADCReader**: Returns simulated value (controlled by keyboard/mouse)
- **ButtonHandler**: Only responds to keyboard (SPACE/M key)
- **Display**: Fully functional Pygame window

---

## 7. Configuration Persistence

`config.json` stores:
- Current condition index
- HR, PI, SpO₂, RR, noise level
- Edit mode

Saved on clean shutdown, loaded on startup.

---

## 8. Extending the System

### Adding a new PPG condition
1. Add constant in `ppg_model.py` (e.g., `COND_NEW = 6`)
2. Add entry in `CONDITION_NAMES`
3. Add `ConditionRanges` in `_init_condition_ranges()`
4. Add `PPGLimits` in `get_ppg_limits()`
5. Update `COND_COUNT`

### Adding a new adjustable parameter
1. Add field to `PPGParameters`
2. Add `EDIT_NEW_PARAM` constant in `state_machine.py`
3. Add limits to `get_ppg_limits()`
4. Add pot mapping case in `main.py._handle_inputs()`
5. Add display rendering in `main.py._update_display()`

---

## 9. Build & Run

```bash
# Setup
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt

# Run (hardware)
python main.py

# Run (dry-run)
python main.py --dry-run

# Enable/disable logging
PPG_LOG_ENABLED=1 python main.py
PPG_LOG_ENABLED=0 python main.py
```

---

## 10. Design Decisions

1. **Python threading vs multiprocessing** — Threading is sufficient since the DAC write rate (1 kHz) is well within Python's capabilities. The GIL is not a bottleneck because the generation loop spends most time in `time.sleep()`.

2. **Grove Base Hat ADC** — Uses the Seeed Studio STM32-based ADC on the Grove Base Hat instead of a separate ADS1115, since it's already integrated with the hat's I2C.

3. **Pygame vs Tkinter** — Pygame provides much better waveform rendering performance and full-screen support on the RPi's framebuffer.

4. **Dry-run mode** — Essential for development on non-RPi machines. All hardware classes gracefully degrade to simulated operation.

5. **Config persistence** — JSON file saves parameters on shutdown and restores on startup, preventing loss of calibration between reboots.

6. **Virtual environment with --system-site-packages** — Required because `grove.py` is installed system-wide and needs to be accessible from within the venv.

---

## 6. Data Logging Architecture

The `core/csv_logger.py` module continuously captures the simulated physiological state to a `data.csv` file for external analysis.
- **Trigger**: The logger is initialized when the simulation starts (`STATE_SIMULATING`) and stopped upon pause/exit.
- **Frequency**: Data is logged at 50 Hz, perfectly synced with the Pygame waveform rendering loop.
- **Fields saved**: `IR_Raw`, `RED_Raw`, `HR_BPM`, `SpO2_%`, `RR_BPM`, `PI_%`, `Condition`.
