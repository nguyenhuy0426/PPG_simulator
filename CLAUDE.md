# CLAUDE.md — PPG Signal Simulator (Raspberry Pi 4) Architecture Guide

> **AI-generated architecture documentation for the PPG Signal Simulator.**
> Migrated to CustomTkinter for modern sidebar-based navigation and data management.

---

## 1. Project Overview

**PPG Signal Simulator** is a Python application for Raspberry Pi 4 that generates realistic dual-channel PPG signals. It synthesizes IR and Red PPG waveforms using a 3-component Gaussian model and outputs them via dual MCP4725 DACs. The UI uses **CustomTkinter** for a professional desktop-style experience with sidebar navigation.

### Key Specifications

| Feature | Value |
|---------|-------|
| Platform | Raspberry Pi 4 (Ubuntu 24.04 LTS) |
| Language | Python 3.10+ |
| UI Framework | CustomTkinter (sidebar navigation) |
| Display | Auto-detect HDMI resolution |
| DAC | Dual MCP4725 (12-bit, I2C) |
| Model Rate | 100 Hz |
| DAC Rate | 1 kHz |
| Architecture | Multi-threaded (Main UI + Signal Generation) |
| Data Storage | CSV recording with playback support |

---

## 2. Hardware Interface

### Pin Assignments (BCM)

```
Raspberry Pi 4 Pin Map
═══════════════════════════════════════
MCP4725 DACs (I2C Bus 1):
  GPIO2 → SDA, GPIO3 → SCL
  0x60 = IR Channel, 0x61 = Red Channel

Display:
  HDMI → Auto-detect resolution
```

---

## 3. Software Architecture

### Threading & Loop Model

```
Main Thread (CustomTkinter)        Background Thread (daemon)
═══════════════════════════        ═════════════════════════════════
app.mainloop()                     signal_engine._generation_loop()
├── .after(20ms) polling loop      ├── PPGModel @ 100 Hz
├── Sidebar navigation switching   ├── 10× interpolation → 1 kHz
├── Waveform Canvas rendering      ├── Ring buffer (1024)
└── Modal dialogs (Save/Cancel)    └── MCP4725 DAC writes
```

### Module Dependency

```
main.py (Entry point)
├── core/signal_engine.py        Generation thread + DAC orchestrator
│   ├── models/ppg_model.py      3-Gaussian PPG physiological model
│   └── hw/dac_manager.py        Dual MCP4725 driver
├── core/csv_logger.py           Dynamic recording to dataset/ folder
├── ui/ctk_app.py                Main Window (Navigation & Sidebar)
│   ├── ui/frames/pathology_frame.py    Main simulation & sliders
│   ├── ui/frames/calibration_frame.py  Sine wave output
│   └── ui/frames/playback_frame.py     Data review & plotting
└── config_store.py              JSON persistence (config.json)
```

---

## 4. Signal Generation Pipeline

```
PPGModel (100 Hz) → 10× Interpolation → Ring Buffer (1 kHz) → DACManager (2× MCP4725)
     ↑                                                            ↓
generate_both_samples()                                    0–3.3V analog
returns IR, Red, display_IR                                (0–4095, 12-bit)
```

### Signal Levels (Volts, default PI=3.0)

| Component | Value |
|-----------|-------|
| DC baseline | 0.5 V |
| AC peak (PI=3.0) | 2.8 V |
| Signal range | 0.5 V (valley) to 3.3 V (systolic peak) |
| DAC mapping | 0 V → 0, 3.3 V → 4095 |

---

## 5. Data Management

### Recording Workflow
- **Start**: Creates `dataset/temp_recording.csv`.
- **Stop**: Triggers a confirmation modal.
- **Save**: Renames temp file to `data_N.csv` in `dataset/`.
- **Discard**: Deletes the temp file.

### Playback Mode
- Scans `dataset/` for CSV files.
- Loads IR/Red raw data and original parameters.
- Static plotting on the `PlaybackFrame` canvas.

---

## 6. Build & Run

```bash
# Prerequisites
pip install customtkinter

# Run (hardware)
python3 main.py

# Run (dry-run)
python3 main.py --dry-run
```

---

## 7. Design Decisions

1. **Switch to CustomTkinter**: Replaced Pygame to allow for structured navigation (sidebar), better widget management (sliders/buttons), and native-feeling file browsing.
2. **Canvas-based Waveforms**: Used `CTkCanvas` with optimized line coordinate updates to maintain smooth 50Hz rendering without the overhead of Matplotlib.
3. **Dynamic Logging**: Shifted from a single `data.csv` to a `dataset/` directory with auto-incrementing files to support multiple recording sessions.
4. **Calibration Mode**: Implemented a standalone frame to output pure sine waves, bypassing the complex PPG model for DAC verification.

---

## 8. Data Logging Architecture

- **Frequency**: Data is captured at ~50 Hz during simulation.
- **Fields saved**: `IR_Raw`, `RED_Raw`, `HR_BPM`, `SpO2_%`, `RR_BPM`, `PI_%`, `Condition`.
