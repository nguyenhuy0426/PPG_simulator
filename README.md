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
- ✅ **Physiological Couplings** — Real-time HR → amplitude attenuation and SpO₂ → dicrotic notch fading.
- ✅ **Beer-Lambert law physics** — Accurate R = (110 − SpO₂) / 25 for Red/IR amplitude ratio.
- ✅ **Clinical Perfusion Index (PI)** — Strict mathematical mapping: `AC = PI * DC / 100` at a `1.5V` DC baseline for high-fidelity sensor testing.
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

## 📈 PPG Signal Model & Physiological Synthesis

The simulator synthesizes realistic dual-channel (IR & Red) photoplethysmography (PPG) waveforms by modeling cardiac and respiratory physiology with clinical precision:

### 1. Waveform Shape (Allen 2007)
A 3-component Gaussian sum model represents the physiological pressure-pulse cycle:
$$\text{pulse}(t) = \text{systolic\_gaussian}(t) + \text{diastolic\_gaussian}(t) - \text{dicrotic\_notch\_gaussian}(t)$$

aligned with the reference C++ physiological models:
- **Systolic Peak**: $\mu = 0.15$, $\sigma = 0.055$ (Sharp systolic rise and peak)
- **Dicrotic Notch**: $\mu = 0.30$, $\sigma = 0.020$ (Rapid closing of the aortic valve)
- **Diastolic Peak**: $\mu = 0.40$, $\sigma = 0.100$ (Pressure wave reflection from lower body)

### 2. Clinical Perfusion Index (PI) Scaling
To guarantee compatibility with medical-grade pulse oximeters, the model implements the strict clinical definition of the Perfusion Index:
$$\text{PI} = \frac{\text{AC}}{\text{DC}} \times 100\% \implies \text{AC} = \text{PI} \times \frac{\text{DC}}{100}$$

- **DC Baseline**: Set to $1.5\text{V}$ representing static tissue, venous, and baseline arterial light absorption.
- **AC Pulsatile Amplitude**: Scaled at exactly $0.015\text{V}$ per $\text{PI}\%$.
  - At $\text{PI} = 3\%$, $\text{AC} = 45\text{mV}$.
  - At $\text{PI} = 10\%$, $\text{AC} = 150\text{mV}$.
This ensures that the output signal represents physiologically accurate ratios for external sensor calibration.

### 3. SpO₂ Modulation (Beer-Lambert Law)
The amplitude ratio of the Red and Infrared channels ($R$-ratio) is dynamically derived using empirical calibration coefficients:
$$R = \frac{110 - \text{SpO}_2}{25}$$
$$\text{AC}_{\text{Red}} = \text{AC}_{\text{IR}} \times R$$

### 4. Advanced Physiological Couplings
- **Heart Rate $\to$ Amplitude Coupling**: Real-time vasoconstriction and stroke volume reduction under elevated heart rate. AC amplitudes undergo a $-3.2\%$ attenuation per $10\text{ BPM}$ increase above $60\text{ BPM}$ (physiological limit $\ge 70\%$).
- **Hypoxia $\to$ Vasoconstriction Coupling**: When $\text{SpO}_2$ drops below $94\%$, sympathetic activation is simulated by fading out the dicrotic notch (simulating loss of arterial elasticity and increased vascular resistance). The notch depth is reduced by up to $60\%$ at severe hypoxia ($\text{SpO}_2 \le 84\%$).

### 5. Respiratory Modulations (Charlton 2018)
- **Baseline Wander (BW / RIIV)**: Respiratory-induced intensity variation up to $0.4\%$ of the DC baseline.
- **Amplitude Modulation (AM / RIAV)**: Respiratory-induced amplitude variation ($\pm25\%$) matching the chest cavity's mechanical pressure changes.
- **Frequency Modulation (FM / RIFV / RSA)**: Respiratory sinus arrhythmia (±5% cardiac interval modulation).

---

## 👨‍💻 Authors

**HuyNN** — Hardware design, embedded firmware  
**VyPT** — Software design, UI/UX

**Institution:** Industrial University of Ho Chi Minh City (IUH)
