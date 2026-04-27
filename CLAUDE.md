# CLAUDE.md — PPG Signal Simulator Architecture Guide

> **AI-generated documentation for the PPG Signal Simulator firmware.**
> This file provides complete context for understanding, modifying, and extending the codebase.

---

## 1. Project Overview

**PPG Signal Simulator** is an ESP32-S3 firmware that generates realistic photoplethysmography (PPG) signals. It synthesizes analog PPG waveforms with physiologically accurate morphology across 6 clinical conditions and outputs them via dual 12-bit DACs for connection to external monitoring equipment.

### Key Specifications

| Feature | Value |
|---------|-------|
| MCU | ESP32-S3-DevKitC-1 (Dual-core, 240 MHz) |
| Display | 1.8" TFT ST7735 (160×128, SPI) |
| DAC Output | Dual MCP4725 (12-bit, I2C, 0–3.3V) |
| Controls | 1 MODE button + 1 potentiometer (5 kΩ) |
| Signal | PPG (Dual-channel Red/IR, 6 conditions) |
| Model Rate | 100 Hz |
| DAC Rate | 1 kHz |
| Architecture | Dual-core FreeRTOS |

---

## 2. Hardware Interface

### Pin Assignments

```
ESP32-S3 Pin Map
═══════════════════════════════════════
TFT Display (SPI — ST7735 1.8"):
  GPIO11 → TFT_MOSI (data)
  GPIO12 → TFT_SCLK (clock)
  GPIO10 → TFT_CS   (chip select)
  GPIO4  → TFT_DC   (data/command)
  GPIO5  → TFT_RST  (reset)

MCP4725 DACs (I2C):
  GPIO8  → I2C_SDA
  GPIO9  → I2C_SCL
  Address: 0x60 (IR Channel)
  Address: 0x61 (Red Channel)

Push Button (Active LOW, internal pull-up):
  GPIO7  → BTN_MODE  (cycle edit modes)

Potentiometer (5 kΩ, analog input):
  GPIO15 → POT_PIN   (parameter adjustment via 12-bit ADC)

Status LED:
  GPIO2  → Onboard LED
```

### Hardware Schematic (Logical)

```
                   ┌─────────────────┐
                   │    ESP32-S3     │
                   │                 │
    TFT ST7735 ◄───┤ SPI (11,12,10) │
    (160×128)      │     DC=4,RST=5 │
                   │                 │
    Dual MCP4725 ◄─┤ I2C (SDA=8,    │──► Dual Analog Out (Red/IR)
    (12-bit)       │      SCL=9)    │    0–3.3V PPG Signals
                   │                 │
    BTN_MODE ──────┤ GPIO7          │
    POT (5 kΩ) ────┤ GPIO15 (ADC)   │
                   │                 │
                   │ GPIO2 → LED     │
                   └─────────────────┘
```

---

## 3. Software Architecture

### Dual-Core Task Distribution

```
Core 0 (UI + Control)              Core 1 (Real-time Generation)
═══════════════════                ═══════════════════════════
loop() @ ~100 Hz                   generationTask() - continuous
├── handleInputs()                 ├── PPGModel.generateBothSamples() @ 100 Hz
│   ├── MODE button (ISR)          ├── Linear Interpolation → 1 kHz
│   └── POT analogRead + EMA      ├── Ring Buffer fill
├── updateDisplay()                └── MCP4725 DAC write @ 1 kHz
│   ├── TFT waveform @ 50 Hz
│   └── Metrics text @ 4 Hz
└── serialHandler.process()
```

### Module Dependency Graph

```mermaid
graph TD
    MAIN["main.cpp"] --> SM["StateMachine"]
    MAIN --> SE["SignalEngine"]
    MAIN --> PC["ParamController"]
    MAIN --> TFT["TFTDisplay"]
    MAIN --> BTN["ButtonHandler"]
    MAIN --> SH["SerialHandler"]

    SE --> PPG["PPGModel"]
    SE --> DAC["DACManager"]
    PPG --> DF["DigitalFilters"]
    PPG --> ST["signal_types.h"]
    PC --> PL["param_limits.h"]
    PL --> ST
    SM --> ST
```

---

## 4. Source Code Structure

```
BioSignalSimulatorPro/
├── include/
│   ├── config.h                    # System config, pins, sampling rates
│   ├── data/
│   │   ├── signal_types.h          # PPG types, enums, state machine
│   │   └── param_limits.h          # Per-condition parameter ranges
│   ├── core/
│   │   ├── signal_engine.h         # Signal generation orchestrator
│   │   ├── state_machine.h         # System state machine
│   │   ├── param_controller.h      # Parameter validation & clamping
│   │   └── digital_filters.h       # Biquad IIR filter chains
│   ├── models/
│   │   └── ppg_model.h             # PPG waveform synthesis model
│   ├── hw/
│   │   ├── tft_display.h           # TFT ST7735 display driver
│   │   ├── dac_manager.h           # Dual MCP4725 DAC manager
│   │   └── button_handler.h        # MODE button ISR + POT handler
│   └── comm/
│       └── serial_handler.h        # Serial debug interface
├── src/
│   ├── main.cpp                    # Application entry point
│   ├── core/
│   │   ├── signal_engine.cpp
│   │   ├── state_machine.cpp
│   │   ├── param_controller.cpp
│   │   └── digital_filters.cpp
│   ├── models/
│   │   └── ppg_model.cpp           # PPG physiological model (700+ lines)
│   ├── hw/
│   │   ├── tft_display.cpp
│   │   ├── dac_manager.cpp
│   │   └── button_handler.cpp
│   └── comm/
│       └── serial_handler.cpp
└── platformio.ini                  # Build configuration
```

---

## 5. Signal Generation Pipeline

### PPG Model (ppg_model.cpp)

The PPG model generates physiologically accurate waveforms using a **3-component Gaussian decomposition**:

1. **Systolic peak** — Primary blood volume pulse (position: 15% of RR cycle)
2. **Dicrotic notch** — Aortic valve closure artifact (position: 28%)
3. **Diastolic peak** — Reflected arterial wave (position: 35%)

```
PPG Waveform Components:

    Systolic Peak
        ∧
       / \        Diastolic Peak
      /   \         ∧
     /     \       / \
    /       \_____/   \
   /           ^       \
  /        Dicrotic     \
            Notch
|←systole→|←──diastole──────→|
|←────── RR interval ───────→|
```

### Key Physiological Rules

- **Systole duration is ~constant** (~300ms), diastole absorbs HR changes
- **Dual-Channel (SpO2)**: Generates synchronized Red and IR signals. SpO2 determines the physiological R-ratio (`R = (110 - SpO2) / 25`), which controls the relative AC/DC amplitude between channels.
- **Respiratory Rate (RR)**: Breathing artifacts are dynamically modeled with:
  - **BW (Baseline Wander)**: `4 mV × sin(respPhase)` — subtle DC oscillation.
  - **AM (Amplitude Modulation)**: 25% peak-to-peak modulation of AC amplitude.
  - **FM (Frequency Modulation)**: Respiratory Sinus Arrhythmia (RSA) varying RR-interval by ±5%.
- Each condition modifies waveform shape parameters (notch depth, diastolic ratio, etc.)
- **HR and PI have beat-to-beat variability** via Gaussian random (CV% configurable)

### Sampling Pipeline

```
PPGModel (100 Hz) → Linear Interpolation (10×) → Dual Ring Buffers (1 kHz) → DACManager (2× MCP4725)
    ↑                                                                      ↓
generateBothSamples()                                               3.3V analog out
returns Red/IR values                                               (0–4095, 12-bit)
```

---

## 6. Clinical Conditions

| # | Condition | HR Range | PI Range | Notch | Description |
|---|-----------|----------|----------|-------|-------------|
| 0 | Normal | 60–100 | 2.9–6.1% | 0.15–0.35 | Healthy PPG waveform |
| 1 | Arrhythmia | 60–180 | 1.0–5.0% | 0.10–0.30 | Irregular RR intervals (high CV) |
| 2 | Weak Perfusion | 70–120 | 0.5–2.1% | 0.0–0.10 | Low AC amplitude, poor perfusion |
| 3 | Vasoconstriction | 65–110 | 0.5–0.8% | 0.0–0.10 | Very low PI, flat waveform |
| 4 | Strong Perfusion | 60–90 | 7.0–20% | 0.25–0.45 | High AC amplitude, prominent notch |
| 5 | Vasodilation | 60–90 | 5.0–10% | 0.20–0.40 | Moderate-high PI, strong diastole |

---

## 7. User Interface

### TFT Display Layout (160×128 landscape)

```
┌──────────────────────────────────────────┐
│ HR:75 PI:3.0% O2:98 RR:16               │ ← Header (auto-formatting)
├──────────────────────────────────────────┤
│                                          │
│  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  │ Grid lines
│          ∧         ∧                     │
│         / \       / \                    │ Auto-scaled Waveform
│        /   \_____/   \_____              │ (Dynamic 1-sweep min/max mapping)
│  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  │
│                                          │
├──────────────────────────────────────────┤
│ < 1: Normal >                            │ ← Footer (10px)
└──────────────────────────────────────────┘
```

### Control Flow

```
┌──────────────────────────────────────────────────────────┐
│                    MODE BUTTON (GPIO7)                    │
│  ┌──────────┐    ┌──────────┐    ┌─────────┐    ┌─────┐│
│  │ Condition│───►│  Edit HR │───►│ Edit PI │───►│SpO2 ││
│  │  Select  │    │  (BPM)   │    │   (%)   │    │ (%) ││
│  └────┬─────┘    └──────────┘    └─────────┘    └──┬──┘│
│       │              ┌──────────┐    ┌──────────┐  │    │
│       │              │  Edit RR │◄───│  Edit    │──┘    │
│       │              │  (BPM)   │    │  Noise   │       │
│       │              └────┬─────┘    └──────────┘       │
│       └───────────────────┘                              │
│                      (cycles)                            │
├──────────────────────────────────────────────────────────┤
│ POTENTIOMETER (GPIO15, 5 kΩ):                            │
│   Continuously maps ADC (0–4095) to the active           │
│   parameter's full range.                                │
│   In Condition Select: selects one of 6 conditions       │
│   In Edit mode: smoothly adjusts the parameter           │
└──────────────────────────────────────────────────────────┘
```

### State Machine

```mermaid
stateDiagram-v2
    [*] --> INIT
    INIT --> SELECT_CONDITION : INIT_COMPLETE
    SELECT_CONDITION --> SIMULATING : BTN_MODE / START
    SIMULATING --> SIMULATING : BTN_MODE (cycle edit mode)
    SIMULATING --> SELECT_CONDITION : STOP (mode cycles back)
    SIMULATING --> PAUSED : PAUSE
    PAUSED --> SIMULATING : BTN_MODE / RESUME
    PAUSED --> SELECT_CONDITION : STOP
```

---

## 8. Key Data Structures

### PPGParameters
```cpp
struct PPGParameters {
    PPGCondition condition;     // 0-5 (Normal, Arrhythmia, ...)
    float heartRate;            // BPM (40–180)
    float perfusionIndex;       // PI % (0.5–20)
    float noiseLevel;           // 0.0–0.10 (0–10%)
    float dicroticNotch;        // Notch depth (0.0–1.0)
    float amplification;        // Waveform gain (0.5–2.0)
    float spO2;                 // SpO2 % (80–100)
    float respRate;             // Respiratory rate (0–60 BPM)
};
```

### UIEditMode
```cpp
enum class UIEditMode {
    CONDITION_SELECT,   // POT selects PPG condition
    EDIT_HR,            // POT adjusts heart rate
    EDIT_PI,            // POT adjusts perfusion index
    EDIT_SPO2,          // POT adjusts SpO2
    EDIT_RR,            // POT adjusts respiratory rate
    EDIT_NOISE          // POT adjusts noise level
};
```

---

## 9. Build & Flash

### Prerequisites
- PlatformIO CLI or IDE
- ESP32-S3 connected via USB (port: `/dev/ttyACM0`)

### Build
```bash
pio run -e esp32_s3
```

### Flash
```bash
pio run -e esp32_s3 --target upload
```

### Monitor Serial
```bash
pio device monitor
```

### Serial Commands
| Key | Action |
|-----|--------|
| `h` | Show help |
| `i` | System info (heap, CPU, DAC, display) |

---

## 10. Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| `adafruit/Adafruit ST7735` | ^1.11.0 | TFT display driver (ST7735) |
| `adafruit/Adafruit GFX` | ^1.12.6 | Graphics primitives |
| `adafruit/Adafruit MCP4725` | ^2.0.2 | I2C DAC driver |
| Arduino Framework | - | Core HAL for ESP32-S3 |

---

## 11. Design Decisions

1. **MCP4725 DAC writes in task, not ISR** — I2C is not ISR-safe. The generation task on Core 1 handles both sample generation and DAC output at ~1 kHz via polling with `micros()`.

2. **12-bit DAC resolution** — MCP4725 provides 4096 levels (0.806 mV/step) vs. the ESP32 internal DAC's 256 levels (12.9 mV/step). This gives 16× finer voltage resolution.

3. **Sweep-line waveform rendering** — The TFT display uses a sweep approach (like an oscilloscope) rather than scrolling. New data overwrites old data left-to-right, with an erase cursor 2 pixels ahead.

4. **Potentiometer with EMA filter** — The 5 kΩ potentiometer is read via `analogRead()` on GPIO15 and filtered with an Exponential Moving Average (alpha=0.2) to suppress analog noise and prevent UI flickering. The ADC value (0–4095) is mapped to the active parameter's full range using `mapf()`.

5. **Button debouncing in ISR** — The single MODE button uses `millis()` comparison within the ISR for 200ms debounce. This avoids the need for a separate debounce task while keeping the main loop clean.

6. **Condition mapping uses 0..COUNT range** — To ensure all 6 conditions are accessible, the pot maps to `[0, COUNT)` and clamps at `COUNT-1`, giving each condition an equal ~682-value zone.

---

## 12. Extending the System

### Adding a new PPG condition
1. Add entry to `PPGCondition` enum in `signal_types.h`
2. Add limits in `getPPGLimits()` in `param_limits.h`
3. Add condition ranges in `initConditionRanges()` in `ppg_model.cpp`
4. Add condition name string in `getConditionName()` in `ppg_model.cpp`
5. Add name to `conditionNames[]` array in `main.cpp`
6. Update `PPGCondition::COUNT`

### Adding a new adjustable parameter
1. Add field to `PPGParameters` struct
2. Add `UIEditMode::EDIT_NEW_PARAM` enum value
3. Add limits to `PPGLimits` struct in `param_limits.h`
4. Add potentiometer mapping case in `handleInputs()` in `main.cpp`
5. Add display rendering in `updateDisplay()` in `main.cpp`
