# 🫀 PPG Signal Simulator — Raspberry Pi 4

**Portable photoplethysmography (PPG) signal generator for clinical training and biomedical equipment validation**

![Version](https://img.shields.io/badge/version-3.1.0-blue)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%204-green)
![Language](https://img.shields.io/badge/language-Python%203.10+-orange)
![License](https://img.shields.io/badge/license-MIT-yellow)

**Group #2:** HuyNN, VyPT
**Institution:** Industrial University of Ho Chi Minh City (IUH) — Faculty of Electronic Technology
**Version:** 3.1.0 — Python port for Raspberry Pi 4 with responsive overlaid waveform HDMI display

---

## 📋 Overview

Python port of the ESP32-S3 PPG Signal Simulator firmware for **Raspberry Pi 4**. Generates synthetic PPG waveforms using a 3-component Gaussian sum model (Allen 2007) with Beer-Lambert law for accurate SpO₂-dependent Red/IR ratio, and outputs via dual 12-bit DACs. Features a responsive full-screen GUI on any HDMI display with overlaid dual-channel (IR/Red) waveform visualization.

### Key Features

- ✅ **Overlaid dual-channel PPG waveform** — IR (green) and Red (red-orange) on single panel with shared time axis
- ✅ **Beer-Lambert law physics** — Accurate R = (110 − SpO₂) / 25 for Red/IR amplitude ratio
- ✅ **6 clinical conditions** — Normal, Arrhythmia, Weak perfusion, Vasoconstriction, Strong perfusion, Vasodilation
- ✅ **Full respiratory modulations** — BW (baseline wander at 2% DC), AM (amplitude modulation), FM (RSA)
- ✅ **Responsive display** — Auto-detects any HDMI screen resolution (7", 11", 14", 15", 24", 27")
- ✅ **Dual 12-bit DAC outputs** — IR and Red channels via two MCP4725 (I2C) with proper voltage mapping
- ✅ **Calibration mode** — Standard sine wave output (1/2/5 Hz) for oscilloscope verification
- ✅ **Potentiometer + MODE button** — Real-time parameter control via Grove Base Hat ADC
- ✅ **Mouse & keyboard control** — Full parameter adjustment from the UI
- ✅ **Dry-run mode** — Run on any Linux PC without Raspberry Pi hardware
- ✅ **Config persistence** — Parameters saved to JSON, restored on reboot
- ✅ **Debug logging** — Configurable logging to `/tmp/ppg_simulator.log`
- ✅ **Data logging** — Automatically logs all numerical data (IR, RED, HR, SpO2, RR, PI, condition) to `data.csv` for analysis

### Key Specifications

| Parameter               | Value                                           |
|------------------------|-------------------------------------------------|
| Platform               | Raspberry Pi 4 (Ubuntu 24.04 LTS)               |
| Display                | Any HDMI display (auto-detect resolution)        |
| DAC                    | MCP4725 (12-bit, I2C) × 2 — IR & Red channels   |
| ADC                    | Grove Base Hat (12-bit, I2C STM32)               |
| PPG model rate         | 100 Hz                                           |
| DAC output rate        | 1 kHz (10× linear interpolation)                 |
| Controls               | 1 MODE button (GPIO17) + 1 potentiometer (5 kΩ)  |
| Signal type            | PPG only (6 clinical conditions)                 |
| DAC voltage range      | 0–3.3V linear (0 mV → 0, 3300 mV → 4095)        |
| Language               | Python 3.10+                                     |

---

## 🛠️ Hardware Architecture

### Pin Mapping (Raspberry Pi 4, BCM numbering)

```
Raspberry Pi 4 — PPG Signal Simulator
═══════════════════════════════════════════════════════════════
MCP4725 DACs (I2C Bus 1):
  GPIO2 (pin 3)   → I2C1_SDA
  GPIO3 (pin 5)   → I2C1_SCL
  Addresses: 0x60 (IR channel), 0x61 (Red channel)

Grove Base Hat ADC (I2C, STM32):
  Same I2C bus (GPIO2/GPIO3)
  Address: 0x04 (STM32 version)
  Channel A0 → Potentiometer wiper (5 kΩ)

Push button (active LOW, internal pull-up):
  GPIO17 (pin 11) → BTN_MODE (cycle edit mode)

Display:
  HDMI → Any screen (auto-detect resolution)
  Tested: 7" (1024×600), 15" (1920×1080), 27" (2560×1440)
```

### System Block Diagram

```
                    ┌─────────────────────┐
                    │   Raspberry Pi 4    │
                    │                     │
   Any HDMI ◄──────┤ HDMI                │
   (auto-detect)   │                     │
                    │                     │
   MCP4725 (IR) ◄──┤ I2C1 (SDA=2,SCL=3) │──► IR Channel (BNC)
   MCP4725 (Red) ◄─┘                     └──► Red Channel (BNC)
                    │                     │
   Grove Base Hat ──┤ I2C1 (addr 0x04)   │
   └─ POT (5 kΩ) ──┤ ADC Channel A0     │
                    │                     │
   BTN_MODE ────────┤ GPIO17             │
                    └─────────────────────┘
```

---

## 💻 Software Architecture

### Threading Model

```
Main Thread (GUI + Control)           Background Thread (Real-time Generation)
════════════════════════════           ═════════════════════════════════════════
Pygame event loop @ 60 FPS            signal_engine._generation_loop()
├── handle_events()                   ├── PPGModel.generate_both_samples() @ 100 Hz
│   ├── Keyboard input                │   Returns (IR, Red, disp_IR, disp_Red)
│   └── Mouse scroll                  ├── Linear interpolation (10×) → 1 kHz
├── handle_inputs()                   ├── Ring buffer fill (1024 samples)
│   ├── MODE button (GPIO/keyboard)   └── MCP4725 DAC write @ 1 kHz
│   └── POT (ADC/keyboard/mouse)
├── update_display()
│   ├── Overlaid waveform @ 50 Hz
│   │   (IR green + Red orange, shared scale)
│   ├── Time axis (0s–5s)
│   ├── Amplitude legend (IR/Red mV)
│   └── Metrics text @ 4 Hz
└── config auto-save on exit
```

### Module Dependency Graph

```
main.py
   ├── SignalEngine (signal generation orchestrator)
   │    ├── PPGModel (physiological PPG model + Beer-Lambert)
   │    │    └── digital_filters (optional IIR Butterworth filters)
   │    └── DACManager (dual MCP4725 driver)
   ├── StateMachine (state management)
   ├── ADCReader (Grove Base Hat potentiometer)
   ├── ButtonHandler (GPIO MODE button)
   ├── PygameDisplay (responsive HDMI GUI)
   ├── config_store (JSON persistence)
   └── logger (debug logging)
```

### Folder Structure

```
PPG_simulator_raspi/
├── main.py                      # Application entry point
├── config.py                    # System config, auto-detect layout, compute_layout()
├── config_store.py              # JSON config persistence
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── CLAUDE.md                    # Architecture guide
├── models/
│   └── ppg_model.py             # PPG waveform synthesis (Beer-Lambert, respiratory mods)
├── core/
│   ├── signal_engine.py         # Signal generation thread + DAC output
│   ├── state_machine.py         # System state machine
│   ├── param_controller.py      # Parameter validation & clamping
│   └── digital_filters.py       # IIR biquad filters
├── hw/
│   ├── dac_manager.py           # Dual MCP4725 DAC manager
│   ├── adc_reader.py            # Grove Base Hat ADC reader
│   └── button_handler.py        # GPIO MODE button handler
├── ui/
│   └── pygame_display.py        # Responsive full-screen Pygame GUI
└── comm/
    └── logger.py                # Debug logging handler
```

---

## 🔧 Installation & Setup

### Prerequisites

- Raspberry Pi 4 with Ubuntu 24.04 LTS
- Python 3.10+
- I2C enabled (`sudo raspi-config` → Interface Options → I2C)
- Grove Base Hat installed

### 1. Install Grove Base Hat library (system-wide)

```bash
curl -sL https://github.com/Seeed-Studio/grove.py/raw/master/install.sh | sudo bash -s -
```

### 2. Create virtual environment

```bash
cd PPG_simulator_raspi
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install -r requirements.txt
```

> **Note:** `--system-site-packages` is required to access the grove.py library installed system-wide.

### 3. Run the simulator

```bash
# On Raspberry Pi (with hardware)
source venv/bin/activate
python main.py

# On any Linux PC (without hardware)
source venv/bin/activate
python main.py --dry-run
```

---

## 🎯 Quick Start Guide

1. **Connect hardware**: Wire MCP4725 DACs (I2C), potentiometer (Grove A0), MODE button (GPIO17)
2. **Run**: `python main.py`
3. The display shows the condition selection screen
4. Turn the **potentiometer** (or use LEFT/RIGHT arrow keys) to select a condition
5. Press **MODE button** (or SPACE/M key) to start simulation
6. While simulating:
   - **MODE** cycles: HR → PI → SpO₂ → RR → Noise → Condition Select
   - **Potentiometer** smoothly adjusts the active parameter
   - **Keys 1-6** quick-select a condition
   - When edit mode returns to Condition Select, simulation stops
7. **Connect BNC cables** from IR/Red DAC outputs to external equipment

### Keyboard Controls

| Key | Action |
|-----|--------|
| `SPACE` / `M` | MODE button (cycle edit mode / start) |
| `←` / `→` | Adjust potentiometer value |
| `Mouse scroll` | Fine potentiometer adjustment |
| `1`-`6` | Quick-select condition |
| `C` | Toggle calibration mode (sine wave output) |
| `Q` / `ESC` | Quit |

---

## 📈 PPG Signal Model

### 3-Component Gaussian Sum (Allen 2007)

1. **Systolic peak** — Main blood volume pulse (position: 15% of RR cycle)
2. **Dicrotic notch** — Aortic valve closure artifact (position: 28%)
3. **Diastolic peak** — Reflected arterial wave (position: 35%)

### Beer-Lambert Law (Dual Channel)

The Red/IR amplitude ratio follows the Beer-Lambert law for pulse oximetry:

```
R = (110 − SpO₂) / 25     (clamped to [0.4, 1.6])
AC_red = AC_ir × R

SpO₂ = 98%  →  R = 0.48  (Red ≈ 48% of IR)
SpO₂ = 88%  →  R = 0.88  (Red ≈ 88% of IR)
SpO₂ = 70%  →  R = 1.60  (Red > IR — critical hypoxemia)
```

### Respiratory Modulations

| Modulation | Description | Implementation |
|------------|-------------|----------------|
| **BW** | Baseline wander (2% of DC) | `wander = 0.02 × dc_baseline × sin(respPhase)` |
| **AM** | Peak amplitude changes | `amFactor = 1 + 0.25×sin(respPhase)` |
| **FM/RSA** | Heart rate varies | `rr × (1 + 0.05×sin(respPhase))` |

### DAC Voltage Mapping

```
0 mV    → DAC value 0    (0.000V output)
1500 mV → DAC value 1861 (1.500V output, typical DC baseline)
3300 mV → DAC value 4095 (3.300V output)
```

---

## 🔬 Calibration Mode

Press **C** to enter calibration mode. A known-amplitude sine wave is output on both DAC channels:

| Frequency | Purpose |
|-----------|---------|
| 1 Hz | Verify low-frequency response |
| 2 Hz | Approximate heart rate range |
| 5 Hz | Verify bandwidth |

- **Amplitude**: 50 mV peak
- **Use LEFT/RIGHT** to change frequency
- **Press C** again to exit

Connect an oscilloscope to the DAC outputs and verify the measured amplitude matches the displayed value. Adjust scaling factors if needed.

---

## 📊 Clinical Conditions

| # | Condition        | HR (BPM) | PI (%) | Notch | Description |
|---|-----------------|----------|--------|-------|-------------|
| 0 | Normal          | 60–100   | 2.9–6.1 | 0.18  | Healthy adult |
| 1 | Arrhythmia      | 60–180   | 1.0–5.0 | 0.20  | Irregular RR (CV 15%) |
| 2 | Weak perfusion  | 70–120   | 0.5–2.1 | 0.05  | Low AC, poor perfusion |
| 3 | Vasoconstriction| 65–110   | 0.7–0.8 | 0.05  | Very low PI |
| 4 | Strong perfusion| 60–90    | 7.0–20  | 0.25  | High AC, prominent notch |
| 5 | Vasodilation    | 60–90    | 5.0–10  | 0.25  | Strong diastolic peak |

---

## 📐 Responsive Display

The GUI auto-detects screen resolution and scales all layout elements proportionally:

| Screen | Resolution | Header | Waveform | Footer | Font Scale |
|--------|-----------|--------|----------|--------|------------|
| 7" | 1024×600 | 48px | 516px | 36px | 1.00× |
| 11" | 1366×768 | 61px | 659px | 46px | 1.28× |
| 14" | 1920×1080 | 86px | 930px | 64px | 1.80× |
| 15" | 1920×1080 | 86px | 930px | 64px | 1.80× |
| 24" | 2560×1440 | 115px | 1239px | 86px | 2.40× |
| 27" | 2560×1440 | 115px | 1239px | 86px | 2.40× |

Font sizes are capped at 2.5× to prevent excessively large text on very large displays.

---

## 🔍 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PPG_DRY_RUN` | `0` | Set to `1` to run without hardware |
| `PPG_LOG_ENABLED` | `1` | Set to `0` to disable file logging |

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 👨‍💻 Authors

**HuyNN** — Hardware design, embedded firmware
**VyPT** — Software design, UI/UX

**Institution:** Industrial University of Ho Chi Minh City (IUH)
