Here is the English version of the `README.md` file, fully aligned with your PPG‑only simulator (ESP32‑S3, 1.8″ TFT ST7735, dual MCP4725 DACs, 3 buttons, 6 clinical conditions, full respiratory modulations: BW, AM, FM, and auto‑scaling on display).

```markdown
# 🫀 PPG Signal Simulator

**Portable photoplethysmography (PPG) signal generator for clinical training and biomedical equipment validation**

![Version](https://img.shields.io/badge/version-2.0.0-blue)
![Platform](https://img.shields.io/badge/platform-ESP32--S3-green)
![License](https://img.shields.io/badge/license-MIT-orange)

**Group #2:** HuyNN, VyPT  
**Institution:** Industrial University of Ho Chi Minh City (IUH) – Faculty of Electronic Technology  
**Version:** 2.0.0 – PPG‑specialized with full respiratory modulation

---

## 📋 Overview

The PPG Signal Simulator is a portable device that generates synthetic PPG (photoplethysmography) waveforms with physiologically accurate morphology. It outputs the signal via a 12‑bit DAC for connection to patient monitors, oscilloscopes, or data acquisition systems.

The embedded firmware runs on an ESP32‑S3 and synthesises PPG signals using a **3‑component Gaussian sum model**. It simulates 6 clinical conditions and allows real‑time adjustment of key parameters using three push buttons.

### Key Features

- ✅ **Real‑time PPG waveform** – Physiological shape: systolic peak, shallow dicrotic notch, diastolic peak
- ✅ **6 clinical conditions** – Normal, Arrhythmia, Weak perfusion, Vasoconstriction, Strong perfusion, Vasodilation
- ✅ **Full respiratory modulations** – BW (baseline wander), AM (amplitude modulation), FM (frequency modulation / RSA) according to user‑set respiratory rate
- ✅ **1.8″ TFT display** – Sweep‑line waveform plotting with auto‑scaling and numeric readout (HR, PI, SpO₂, RR, condition name)
- ✅ **Dual 12‑bit DAC outputs** – Independent IR and Red channels via two MCP4725 (I2C)
- ✅ **3‑button control** – Mode (cycle edit fields), Up (increase / next), Down (decrease / previous)
- ✅ **Auto‑scaling** – Waveform always fits the 160×128 pixel screen; bounds update every sweep cycle (~3.2 s)

### Key Specifications

| Parameter               | Value                                      |
|------------------------|---------------------------------------------|
| MCU                    | ESP32‑S3‑DevKitC‑1 (dual‑core, 240 MHz)     |
| Display                | TFT ST7735 1.8″ (160×128, SPI)              |
| DAC                    | MCP4725 (12‑bit, I2C, 0–3.3 V) – IR & Red   |
| PPG model rate         | 100 Hz                                      |
| DAC output rate        | 1 kHz (10× linear interpolation)            |
| Push buttons           | 3 (Mode, Up, Down)                          |
| Signal type            | PPG only (6 clinical conditions)            |

---

## 🛠️ Hardware Architecture

### Pin Mapping (ESP32‑S3)

```
ESP32-S3 – PPG Signal Simulator
═══════════════════════════════════════════════════════════════
TFT ST7735 (SPI):
  GPIO11 → TFT_MOSI   (data)
  GPIO12 → TFT_SCLK   (clock)
  GPIO10 → TFT_CS     (chip select)
  GPIO4  → TFT_DC     (data/command)
  GPIO5  → TFT_RST    (reset)

MCP4725 DACs (I2C):
  GPIO8  → I2C_SDA
  GPIO9  → I2C_SCL
  Addresses: 0x60 (IR channel), 0x61 (Red channel)

Push buttons (active LOW, internal pull‑up):
  GPIO14 → BTN_MODE   (cycle edit mode)
  GPIO15 → BTN_UP     (increment / next)
  GPIO16 → BTN_DOWN   (decrement / previous)

Status LED:
  GPIO2  → onboard LED
```

### System Block Diagram

```
                    ┌─────────────────────┐
                    │      ESP32-S3       │
                    │                     │
   TFT ST7735 ◄─────┤ SPI (11,12,10)      │
   (160×128)        │ DC=4, RST=5         │
                    │                     │
   MCP4725 (IR) ◄───┤ I2C (SDA=8, SCL=9) │──► IR Channel (BNC)
   MCP4725 (Red) ◄──┘                     └──► Red Channel (BNC)
                    │                     │
   BTN_MODE ────────┤ GPIO14              │
   BTN_UP ──────────┤ GPIO15              │
   BTN_DOWN ────────┤ GPIO16              │
                    │                     │
                    │ GPIO2 → LED         │
                    └─────────────────────┘
```

---

## 💻 Software Architecture

### Dual‑core FreeRTOS Task Distribution

```
       Core 0 (UI + Control)                Core 1 (Real‑time Generation)
       ════════════════════════             ═════════════════════════════════════════
       loop() @ ~100 Hz                     generationTask() – continuous
       ├── handleButtons()                  ├── PPGModel.generateBothSamples() @ 100 Hz
       ├── updateDisplay()                  ├── Linear interpolation (10×) → 1 kHz
       │   ├── drawWaveform @ 50 Hz         ├── Write to ring buffer (size 1024)
       │   └── updateMetrics @ 4 Hz         └── Write MCP4725 DACs @ 1 kHz
       └── serialHandler.process()
```

### Module Dependency Graph

```
main.cpp
   ├── SignalEngine (signal generation orchestrator)
   │    └── PPGModel (physiological PPG model)
   │         └── DigitalFilters (optional IIR Butterworth filters)
   ├── StateMachine (state management)
   ├── ParamController (parameter validation & clamping)
   ├── TFTDisplay (ST7735 driver)
   ├── ButtonHandler (interrupt‑based button handling)
   └── SerialHandler (debug serial interface)
```

### Folder Structure

```
PPG_Signal_Simulator/
├── include/
│   ├── config.h                    # System configuration, pins, sampling rates
│   ├── data/
│   │   ├── signal_types.h          # Enums, PPGParameters struct
│   │   └── param_limits.h          # Per‑condition parameter ranges
│   ├── core/
│   │   ├── signal_engine.h         # Signal generation engine
│   │   ├── state_machine.h         # System state machine
│   │   ├── param_controller.h      # Parameter validation & clamping
│   │   └── digital_filters.h       # IIR biquad filters
│   ├── models/
│   │   └── ppg_model.h             # PPG waveform synthesis model
│   ├── hw/
│   │   ├── tft_display.h           # ST7735 display driver
│   │   ├── dac_manager.h           # Dual MCP4725 manager
│   │   └── button_handler.h        # ISR‑based button handler
│   └── comm/
│       └── serial_handler.h        # Serial debug interface
├── src/
│   ├── main.cpp                    # Application entry point
│   ├── core/                       # signal_engine.cpp, state_machine.cpp, ...
│   ├── models/ppg_model.cpp        # PPG physiological model (700+ lines)
│   ├── hw/                         # tft_display.cpp, dac_manager.cpp, button_handler.cpp
│   └── comm/serial_handler.cpp
└── platformio.ini                  # PlatformIO build configuration
```

---

## 📈 PPG Signal Model

### 3‑Component Gaussian Sum (Allen 2007)

The PPG waveform is synthesised as a sum of three Gaussian components:

1. **Systolic peak** – Main blood volume pulse (position: 15% of RR cycle)
2. **Dicrotic notch** – Aortic valve closure artifact (position: 28%)
3. **Diastolic peak** – Reflected arterial wave (position: 35%)

```
Ideal PPG morphology (Class 1 – young healthy subject)

      Systolic peak
          ∧
         / \            Diastolic peak
        /   \              ∧
       /     \            / \
      /       \__________/   \________
                ^
           Dicrotic notch
           (very shallow)

      |← systole →|←─ diastole ─→|
      |←───────── RR interval ─────────→|
```

### Physiological Rules

- **Systolic duration is nearly constant** (~300 ms), diastolic duration absorbs HR changes.
- **PI (Perfusion Index)** controls AC amplitude: `AC = PI × 15 mV` (pure AC, 0–150 mV).
- Each condition modifies waveform shape (notch depth, diastolic ratio, etc.) according to clinical tables.

### Respiratory Modulations (BW, AM, FM)

The system implements all three respiratory‑induced variations described by Charlton et al. (2018):

| Modulation | Description | Implementation in code |
|------------|-------------|------------------------|
| **BW (Baseline Wander)** | Baseline slowly oscillates with breathing | `wander = 10 mV × sin(2π×f_resp×t)` added to total signal |
| **AM (Amplitude Modulation)** | Peak‑to‑peak amplitude changes with respiration | `amFactor = 1 + 0.15×sin(2π×f_resp×t)` multiplied with AC amplitude |
| **FM (Frequency Modulation / RSA)** | Instantaneous heart rate varies (increase during inspiration) | RR modified instantaneously: `rrMean × (1 + 0.05×sin(respPhase))` |

User can set **Respiratory Rate (RR)** from 0 to 60 breaths/min via the buttons. The displayed waveform shows clear baseline wander, amplitude fluctuation, and slight peak‑interval variations synced with the chosen RR.

### Signal Processing Pipeline

```
PPGModel (100 Hz) → Linear interpolation (10×) → Ring Buffer (1 kHz) → MCP4725 DACs
       ↑                                                                        ↓
generateBothSamples()                                                      Analog voltages
returns IR & Red                                                          (0–3.3 V each)
```

---

## 📊 Clinical Conditions

| # | Condition          | HR range (BPM) | PI range (%) | Notch depth             | Description                      |
|---|--------------------|----------------|--------------|---------------------    |----------------------------------|
| 0 | Normal             | 60–100         | 2.9–6.1      | Very shallow (0.18)     | Healthy adult waveform           |
| 1 | Arrhythmia         | 60–180         | 1.0–5.0      | Shallow (0.20)          | Irregular RR intervals (CV 15%)  |
| 2 | Weak perfusion     | 70–120         | 0.5–2.1      | Very shallow (0.05)     | Low AC amplitude, poor perfusion |
| 3 | Vasoconstriction   | 65–110         | 0.7–0.8      | Very shallow (0.05)     | Very low PI, flat waveform       |
| 5 | Vasodilation       | 60–90          | 5.0–10       | Shallow–moderate (0.20) | High PI, strong diastolic peak   |

---

## 🖥️ User Interface

### TFT Display Layout (160×128 landscape)

```
┌────────────────────────────────────────────────────────────┐
│ HR:75 BPM  PI:3.0%  SpO2:98%  RR:16        Normal        │ ← Header (20px)
├────────────────────────────────────────────────────────────┤
│                     ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·     │
│      ∧         ∧                                           │
│     / \       / \                                          │ ← Waveform area (98px)
│    /   \_____/   \_____                                    │
│                     ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·     │
├────────────────────────────────────────────────────────────┤
│               < 1: Normal >                                │ ← Footer (10px)
└────────────────────────────────────────────────────────────┘
```

### Button Control Flow

```
MODE (GPIO14)
    ┌───────────┐    ┌─────────┐    ┌──────────┐    ┌─────────┐    ┌──────────┐
    │ Condition │───►│  Edit   │───►│  Edit    │───►│  Edit   │───►│  Edit    │
    │  Select   │    │   HR    │    │   PI     │    │  SpO2   │    │   RR     │
    └─────┬─────┘    └─────────┘    └──────────┘    └─────────┘    └────┬─────┘
          │                                                             │
          └─────────────────────────┬───────────────────────────────────┘
                                    ▼
                            ┌──────────────┐
                            │   Edit       │
                            │   Noise      │
                            └──────────────┘
                         (cycles back to Condition Select)

UP / DOWN (GPIO15, GPIO16):
  - In Condition Select: cycle through 6 conditions (1 → 2 → ... → 6 → 1)
  - In Edit mode: increment/decrement parameter (HR: ±5 BPM, PI: ±0.1%, SpO₂: ±1%, RR: ±1, Noise: ±1%)
```

### State Machine

```
INIT → SELECT_CONDITION → SIMULATING ↔ PAUSED
                              ↓
                        (MODE from CONDITION_SELECT)
                              ↓
                        stop simulation, back to SELECT_CONDITION
```

---

## 🔧 Build & Flash

### Prerequisites

- PlatformIO CLI or IDE
- ESP32‑S3 connected via USB (port `/dev/ttyACM0` or `COMx`)

### Build

```bash
pio run -e esp32_s3
```

### Upload

```bash
pio run -e esp32_s3 --target upload
```

### Serial Monitor

```bash
pio device monitor
```

### Serial Commands (Debug)

| Key | Action                         |
|-----|--------------------------------|
| `h` | Show help                      |
| `i` | System info (heap, CPU, DAC, display) |

---

## 📦 Dependencies

| Library                    | Version    | Purpose                     |
|----------------------------|------------|-----------------------------|
| `bodmer/TFT_eSPI`          | ^2.5.43    | ST7735 display driver       |
| `adafruit/Adafruit MCP4725`| ^2.0.2     | MCP4725 I2C DAC driver      |
| Arduino Framework          | –          | Core HAL for ESP32‑S3       |

---

## 🎯 Quick Start Guide

1. **Power** the ESP32‑S3 (USB‑C or external 5 V).
2. The TFT shows the condition selection screen.
3. Use **UP/DOWN** to choose a condition (1–6), then press **MODE** to start simulation.
4. While simulating:
   - **MODE** cycles edit mode: HR → PI → SpO₂ → RR → Noise → Condition Select.
   - **UP/DOWN** changes the selected parameter.
   - When you cycle back to Condition Select, the simulation stops and returns to the selection screen.
5. **Connect BNC cables** from the IR and Red DAC outputs to an oscilloscope or measurement device to view the live analog PPG signals.

---

## 🧪 Verification Plan

### Automated Test

- Compile successfully with `pio run -e esp32_s3`.

### Manual Verification

1. **Waveform morphology** – On the TFT, the waveform should show a smooth “systolic peak → very shallow notch → diastolic peak”, without a deep cleft.
2. **Respiratory modulations** – Increase the RR (Respiratory Rate) to 20–30 bpm:
   - **BW:** baseline visibly moves up and down.
   - **AM:** peak heights increase and decrease in a breathing rhythm.
   - **FM:** peak intervals expand and contract slightly.
3. **Auto‑scaling** – Suddenly change PI (e.g., from 3% to 10%). The waveform may clip for at most 3 seconds, then automatically rescales to fit the screen.
4. **Analog output quality** – On an oscilloscope: 0–3.3 V, clean PPG pulses, proper timing, no distortion.

---

## 📄 License

This project is licensed under the **MIT License** – see the [LICENSE](LICENSE) file for details.

---

## 👨‍💻 Authors
**Specialised PPG simulator – IUH group #2**

- **HuyNN** – Hardware design, PCB design, embedded firmware
- **VyPT** – Software design, application development, UI/UX design

**Institution:** Industrial University of Ho Chi Minh City (IUH) – Faculty of Electronic Technology  
**Version:** 2.0.0 – PPG‑dedicated with full respiratory modulation modelling