# 🫀 PPG Signal Simulator — Raspberry Pi 4

**Portable photoplethysmography (PPG) signal generator for clinical training and biomedical equipment validation**

![Version](https://img.shields.io/badge/version-4.0.0-blue)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%204-green)
![Language](https://img.shields.io/badge/language-Python%203.10+-orange)
![License](https://img.shields.io/badge/license-MIT-yellow)

**Group #2:** HuyNN, VyPT
**Institution:** Industrial University of Ho Chi Minh City (IUH) — Faculty of Electronic Technology
**Version:** 4.0.0 — CustomTkinter Migration with Sidebar Navigation & Dataset Recording

---

## 📋 Overview

Python port of the ESP32-S3 PPG Signal Simulator firmware for **Raspberry Pi 4**. Generates synthetic PPG waveforms using a 3-component Gaussian sum model (Allen 2007) with Beer-Lambert law for accurate SpO₂-dependent Red/IR ratio. Outputs via dual 12-bit DACs.

Featuring a modern **CustomTkinter** UI, this version introduces a structured navigation layout, real-time waveform recording to a dedicated dataset folder, and a playback viewer for historical data analysis.

### Key Features

- ✅ **CustomTkinter GUI** — Professional sidebar-based navigation (Pathology, Calibration, Playback).
- ✅ **Real-time Recording** — Save PPG waveform segments to `dataset/data_N.csv` with a confirmation dialog.
- ✅ **Playback Mode** — Browse and visualize recorded datasets directly within the app.
- ✅ **Beer-Lambert law physics** — Accurate R = (110 − SpO₂) / 25 for Red/IR amplitude ratio.
- ✅ **6 clinical conditions** — Normal, Arrhythmia, Weak perfusion, Vasoconstriction, Strong perfusion, Vasodilation.
- ✅ **Calibration mode** — Dedicated tab for sine wave output (adjustable freq/amp) for hardware verification.
- ✅ **Dual 12-bit DAC outputs** — IR and Red channels via two MCP4725 (I2C).
- ✅ **Config persistence** — Parameters saved to JSON, restored on reboot.
- ✅ **Dry-run mode** — Run on any Linux PC without Raspberry Pi hardware.

### Key Specifications

| Parameter               | Value                                           |
|------------------------|-------------------------------------------------|
| Platform               | Raspberry Pi 4 (Ubuntu 24.04 LTS)               |
| UI Library             | CustomTkinter                                   |
| DAC                    | MCP4725 (12-bit, I2C) × 2 — IR & Red channels   |
| Model Rate             | 100 Hz                                          |
| DAC Rate               | 1 kHz (10× linear interpolation)                |
| Data Recording         | CSV format, saved to `dataset/`                 |
| DAC Voltage Range      | 0–3.3V linear (0 V → 0, 3.3 V → 4095)           |

---

## 🛠️ Hardware Architecture

### Pin Mapping (Raspberry Pi 4, BCM numbering)

```
MCP4725 DACs (I2C Bus 1):
  GPIO2 (pin 3)   → I2C1_SDA
  GPIO3 (pin 5)   → I2C1_SCL
  Addresses: 0x60 (IR channel), 0x61 (Red channel)

Display:
  HDMI → Any screen (auto-detect resolution)
```

---

## 💻 Software Architecture

### Folder Structure

```
PPG_simulator_raspi/
├── main.py                      # Application entry point
├── config.py                    # Constants & Styles
├── config_store.py              # JSON config persistence
├── core/
│   ├── signal_engine.py         # Signal generation thread + DAC output
│   ├── csv_logger.py            # Dataset recording logic
│   └── state_machine.py         # System state machine
├── models/
│   └── ppg_model.py             # PPG physiological model logic
├── ui/
│   ├── ctk_app.py               # Main CustomTkinter Application
│   └── frames/
│       ├── pathology_frame.py   # Main simulation & sliders
│       ├── calibration_frame.py # Sine wave generator
│       └── playback_frame.py    # Data file browser & viewer
└── dataset/                     # Folder where recordings are stored
```

---

## 🔧 Installation & Setup

### 1. Prerequisites
- Raspberry Pi 4 with Ubuntu 24.04 LTS
- I2C enabled (`sudo raspi-config`)
- CustomTkinter installed: `pip install customtkinter`

### 2. Run the simulator

```bash
# On Raspberry Pi (Hardware mode)
python3 main.py

# On any Linux PC (Dry-run mode)
python3 main.py --dry-run
```

---

## 🎯 Mode Guide

### 🧬 Pathology Mode
The default mode for simulating clinical conditions. Adjust Heart Rate, SpO2, Respiratory Rate, and Perfusion Index using the on-screen sliders.
- **Recording**: Click "Start Recording" to begin capturing data. Click "Stop" to trigger a save confirmation. Files are saved as `data_1.csv`, `data_2.csv`, etc., in the `dataset` folder.

### 📐 Calibration Mode
Outputs a pure sine wave on both DAC channels.
- Adjust **Frequency** (1–10 Hz) and **Amplitude** (mV) using the sliders to verify DAC and oscilloscope performance.

### 🔄 Playback Mode
Review previously recorded data.
- Select a file from the sidebar list.
- The waveform will be plotted, and the original physiological parameters will be displayed at the top.

---

## 📈 PPG Signal Model

The simulator uses a 3-component Gaussian sum model to represent the systolic peak, dicrotic notch, and diastolic peak. Red/IR amplitude ratio is calculated based on SpO2 using the Beer-Lambert law: `R = (110 − SpO2) / 25`.

---

## 👨‍💻 Authors

**HuyNN** — Hardware design, embedded firmware  
**VyPT** — Software design, UI/UX

**Institution:** Industrial University of Ho Chi Minh City (IUH)
