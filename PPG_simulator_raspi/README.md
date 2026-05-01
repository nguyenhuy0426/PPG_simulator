# 🫀 PPG Signal Simulator — Raspberry Pi 4

**Portable photoplethysmography (PPG) signal generator for clinical training and biomedical equipment validation**

![Version](https://img.shields.io/badge/version-3.0.0-blue)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%204-green)
![Language](https://img.shields.io/badge/language-Python%203.10+-orange)
![License](https://img.shields.io/badge/license-MIT-yellow)

**Group #2:** HuyNN, VyPT
**Institution:** Industrial University of Ho Chi Minh City (IUH) — Faculty of Electronic Technology
**Version:** 3.0.0 — Python port for Raspberry Pi 4 with dual waveform HDMI display

---

## 📋 Overview

Python port of the ESP32-S3 PPG Signal Simulator firmware for **Raspberry Pi 4**. Generates synthetic PPG waveforms using a 3-component Gaussian sum model (Allen 2007) and outputs via dual 12-bit DACs. Features a premium full-screen GUI on a 7-inch HDMI display with dual-channel (IR/Red) waveform visualization.

### Key Features

- ✅ **Real-time dual-channel PPG waveform** — IR (green) and Red channels displayed simultaneously
- ✅ **6 clinical conditions** — Normal, Arrhythmia, Weak perfusion, Vasoconstriction, Strong perfusion, Vasodilation
- ✅ **Full respiratory modulations** — BW (baseline wander), AM (amplitude modulation), FM (RSA)
- ✅ **7-inch HDMI display** — Premium dark-theme GUI (1024×600) with auto-scaling waveforms
- ✅ **Dual 12-bit DAC outputs** — IR and Red channels via two MCP4725 (I2C)
- ✅ **Potentiometer + MODE button** — Real-time parameter control via Grove Base Hat ADC
- ✅ **Mouse & keyboard control** — Full parameter adjustment from the UI
- ✅ **Dry-run mode** — Run on any Linux PC without Raspberry Pi hardware
- ✅ **Config persistence** — Parameters saved to JSON, restored on reboot
- ✅ **Debug logging** — Configurable logging to `/tmp/ppg_simulator.log`

### Key Specifications

| Parameter               | Value                                           |
|------------------------|-------------------------------------------------|
| Platform               | Raspberry Pi 4 (Ubuntu 24.04 LTS)               |
| Display                | 7-inch HDMI (1024×600)                           |
| DAC                    | MCP4725 (12-bit, I2C) × 2 — IR & Red channels   |
| ADC                    | Grove Base Hat (12-bit, I2C STM32)               |
| PPG model rate         | 100 Hz                                           |
| DAC output rate        | 1 kHz (10× linear interpolation)                 |
| Controls               | 1 MODE button (GPIO17) + 1 potentiometer (5 kΩ)  |
| Signal type            | PPG only (6 clinical conditions)                 |
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
  HDMI → 7-inch screen (1024×600)
```

### System Block Diagram

```
                    ┌─────────────────────┐
                    │   Raspberry Pi 4    │
                    │                     │
   7" HDMI ◄───────┤ HDMI                │
   (1024×600)      │                     │
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
│   ├── Keyboard input                ├── Linear interpolation (10×) → 1 kHz
│   └── Mouse scroll                  ├── Ring buffer fill (1024 samples)
├── handle_inputs()                   └── MCP4725 DAC write @ 1 kHz
│   ├── MODE button (GPIO/keyboard)
│   └── POT (ADC/keyboard/mouse)
├── update_display()
│   ├── IR waveform @ 50 Hz
│   ├── Red waveform @ 50 Hz
│   └── Metrics text @ 4 Hz
└── config auto-save on exit
```

### Module Dependency Graph

```
main.py
   ├── SignalEngine (signal generation orchestrator)
   │    ├── PPGModel (physiological PPG model)
   │    │    └── digital_filters (optional IIR Butterworth filters)
   │    └── DACManager (dual MCP4725 driver)
   ├── StateMachine (state management)
   ├── ADCReader (Grove Base Hat potentiometer)
   ├── ButtonHandler (GPIO MODE button)
   ├── PygameDisplay (HDMI GUI)
   ├── config_store (JSON persistence)
   └── logger (debug logging)
```

### Folder Structure

```
PPG_simulator_raspi/
├── main.py                      # Application entry point
├── config.py                    # System configuration, pins, sampling rates
├── config_store.py              # JSON config persistence
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── CLAUDE.md                    # Architecture guide
├── models/
│   └── ppg_model.py             # PPG waveform synthesis model
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
│   └── pygame_display.py        # Full-screen Pygame GUI
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
| `Q` / `ESC` | Quit |

---

## 📈 PPG Signal Model

### 3-Component Gaussian Sum (Allen 2007)

1. **Systolic peak** — Main blood volume pulse (position: 15% of RR cycle)
2. **Dicrotic notch** — Aortic valve closure artifact (position: 28%)
3. **Diastolic peak** — Reflected arterial wave (position: 35%)

### Respiratory Modulations

| Modulation | Description | Implementation |
|------------|-------------|----------------|
| **BW** | Baseline slowly oscillates with breathing | `wander = 4 mV × sin(respPhase)` |
| **AM** | Peak amplitude changes with respiration | `amFactor = 1 + 0.25×sin(respPhase)` |
| **FM/RSA** | Heart rate varies with breathing | `rr × (1 + 0.05×sin(respPhase))` |

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
