/**
 * @file main.cpp
 * @brief PPG Signal Simulator — Main application
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Hardware: ESP32-S3 + 1.8" TFT ST7735 (SPI) + MCP4725 DAC (I2C) + 3 Buttons
 *
 * Architecture:
 *   Core 0 (loop): UI handling, button polling, TFT display updates
 *   Core 1 (task): Real-time PPG signal generation + DAC output
 *
 * Button controls:
 *   BTN_MODE  (GPIO14): Cycle through edit modes (Condition → HR → PI → Noise)
 *   BTN_UP    (GPIO15): Increment parameter / next condition
 *   BTN_DOWN  (GPIO16): Decrement parameter / previous condition
 */

#include <Arduino.h>
#include <Wire.h>

// Configuration
#include "config.h"
#include "data/signal_types.h"
#include "data/param_limits.h"

// Core modules
#include "core/signal_engine.h"
#include "core/state_machine.h"
#include "core/param_controller.h"

// Hardware drivers
#include "hw/tft_display.h"
#include "hw/dac_manager.h"
#include "hw/button_handler.h"

// Communication
#include "comm/serial_handler.h"

// ============================================================================
// GLOBAL OBJECTS
// ============================================================================
SignalEngine* engine = nullptr;
StateMachine stateMachine;
ParamController paramController;
SerialHandler serialHandler(Serial);

// ============================================================================
// PPG CONDITION NAMES
// ============================================================================
static const char* conditionNames[] = {
    "Normal",
    "Arrhythmia",
    "Weak Perf.",
    "Vasocnstr.",
    "Strong Perf.",
    "Vasodilat."
};

// ============================================================================
// TIMING VARIABLES
// ============================================================================
static uint32_t lastMetricsUpdate = 0;
static uint32_t lastWaveformUpdate = 0;

// ============================================================================
// FORWARD DECLARATIONS
// ============================================================================
void onStateChange(SystemState oldState, SystemState newState);
void handleInputs();
void updateDisplay();
void startSimulationWithCondition(uint8_t condition);

// ============================================================================
// SETUP
// ============================================================================
void setup() {
    // --- Serial ---
    Serial.begin(115200);
    delay(500);
    Serial.println("\n========================================");
    Serial.println("  PPG Signal Simulator v" FIRMWARE_VERSION);
    Serial.println("  " FIRMWARE_DATE);
    Serial.println("========================================\n");

    // --- I2C Bus ---
    Serial.println("[INIT] Starting I2C bus...");
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
    Wire.setClock(400000);  // 400 kHz fast mode for MCP4725
    Serial.printf("[INIT] I2C: SDA=GPIO%d, SCL=GPIO%d @ 400kHz\n", I2C_SDA_PIN, I2C_SCL_PIN);

    // --- Dual MCP4725 DACs ---
    Serial.println("[INIT] Starting Dual MCP4725 DACs...");
    if (!dacManager.begin()) {
        Serial.println("[INIT] ERROR: Dual DACs not initialized! Check wiring.");
        Serial.println("[INIT] Continuing without DAC...");
    }

    // --- TFT Display ---
    Serial.println("[INIT] Starting TFT display...");
    tftDisplay.begin();
    tftDisplay.updateMetrics(0, 0, 0, 0, "Initializing...");

    // --- Inputs (Mode Button + Potentiometer) ---
    Serial.println("[INIT] Starting button handler...");
    buttons.begin();

    // --- Status LED ---
    pinMode(LED_STATUS_PIN, OUTPUT);
    digitalWrite(LED_STATUS_PIN, HIGH);  // LED on during init

    // --- Signal Engine ---
    Serial.println("[INIT] Starting signal engine...");
    engine = SignalEngine::getInstance();
    if (!engine->begin()) {
        Serial.println("[INIT] ERROR: Signal engine failed to start!");
        while (true) { delay(1000); }  // Halt
    }

    // --- State Machine ---
    stateMachine.setStateChangeCallback(onStateChange);

    // --- Serial Handler ---
    serialHandler.begin();
    serialHandler.printHelp();

    // --- Complete initialization ---
    Serial.println("\n[INIT] ✓ All systems ready!");
    Serial.println("[INIT] Starting PPG simulation with Normal condition...\n");

    // Auto-start with Normal condition
    stateMachine.processEvent(SystemEvent::INIT_COMPLETE);
    startSimulationWithCondition(0);  // Normal

    digitalWrite(LED_STATUS_PIN, LOW);  // LED off = running
}

// ============================================================================
// MAIN LOOP (Core 0)
// ============================================================================
void loop() {
    // --- Handle button presses ---
    handleInputs();

    // --- Update TFT display ---
    updateDisplay();

    // --- Process serial commands ---
    serialHandler.process();

    // Small yield to prevent watchdog
    delay(1);
}

// ============================================================================
// HELPER FOR FLOAT MAPPING
// ============================================================================
float mapf(float x, float in_min, float in_max, float out_min, float out_max) {
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min;
}

// ============================================================================
// INPUT HANDLING (Button + Potentiometer)
// ============================================================================
void handleInputs() {
    SystemState state = stateMachine.getState();
    UIEditMode editMode = stateMachine.getEditMode();

    // --- MODE BUTTON ---
    if (buttons.wasModePressed()) {
        Serial.println("[BTN] Mode pressed");

        if (state == SystemState::SELECT_CONDITION) {
            // Start simulation with selected condition
            startSimulationWithCondition(stateMachine.getSelectedCondition());
            stateMachine.processEvent(SystemEvent::START_SIMULATION);

        } else if (state == SystemState::SIMULATING) {
            // Cycle edit mode
            stateMachine.processEvent(SystemEvent::BTN_MODE_PRESS);
            UIEditMode newMode = stateMachine.getEditMode();
            Serial.printf("[BTN] Edit mode: %s\n", StateMachine::editModeToString(newMode));

            // If cycled back to CONDITION_SELECT, it means we want to stop
            if (newMode == UIEditMode::CONDITION_SELECT) {
                engine->stopSimulation();
                stateMachine.processEvent(SystemEvent::STOP);
                tftDisplay.clearWaveform();
            }

        } else if (state == SystemState::PAUSED) {
            // Resume
            engine->resumeSimulation();
            stateMachine.processEvent(SystemEvent::RESUME);
        }
    }

    // --- POTENTIOMETER POLLING ---
    uint16_t potRaw = buttons.getPotValue();
    
    // In SELECT_CONDITION state: map to condition index
    if (state == SystemState::SELECT_CONDITION) {
        uint8_t cond = (uint8_t)mapf(potRaw, 0, 4095, 0, (float)(uint8_t)PPGCondition::COUNT);
        if (cond >= (uint8_t)PPGCondition::COUNT) cond = (uint8_t)PPGCondition::COUNT - 1;
        if (cond != stateMachine.getSelectedCondition()) {
            stateMachine.setSelectedCondition(cond);
            tftDisplay.showConditionSelect(conditionNames[cond], cond);
            Serial.printf("[POT] Condition: %d (%s)\n", cond, conditionNames[cond]);
        }
    } 
    // In SIMULATING state: map to current edit mode parameter
    else if (state == SystemState::SIMULATING) {
        PPGParameters p = engine->getPPGParams();
        PPGLimits lim = getPPGLimits(p.condition);
        
        switch (editMode) {
            case UIEditMode::CONDITION_SELECT: {
                uint8_t cond = (uint8_t)mapf(potRaw, 0, 4095, 0, (float)(uint8_t)PPGCondition::COUNT);
                if (cond >= (uint8_t)PPGCondition::COUNT) cond = (uint8_t)PPGCondition::COUNT - 1;
                if (cond != stateMachine.getSelectedCondition()) {
                    stateMachine.setSelectedCondition(cond);
                    engine->changeCondition(cond);
                    tftDisplay.clearWaveform();
                    Serial.printf("[POT] Condition → %s\n", conditionNames[cond]);
                }
                break;
            }
            case UIEditMode::EDIT_HR: {
                float newHR = round(mapf(potRaw, 0, 4095, lim.heartRate.min, lim.heartRate.max));
                if (abs(newHR - p.heartRate) > 0.5f) {
                    engine->updateHeartRate(newHR);
                }
                break;
            }
            case UIEditMode::EDIT_PI: {
                float newPI = round(mapf(potRaw, 0, 4095, lim.perfusionIndex.min, lim.perfusionIndex.max) * 10.0f) / 10.0f;
                if (abs(newPI - p.perfusionIndex) > 0.05f) {
                    engine->updatePerfusionIndex(newPI);
                }
                break;
            }
            case UIEditMode::EDIT_SPO2: {
                float newSpO2 = round(mapf(potRaw, 0, 4095, lim.spO2.min, lim.spO2.max));
                if (abs(newSpO2 - p.spO2) > 0.5f) {
                    engine->updateSpO2(newSpO2);
                }
                break;
            }
            case UIEditMode::EDIT_RR: {
                float newRR = round(mapf(potRaw, 0, 4095, lim.respRate.min, lim.respRate.max));
                if (abs(newRR - p.respRate) > 0.5f) {
                    engine->updateRespRate(newRR);
                }
                break;
            }
            case UIEditMode::EDIT_NOISE: {
                float newNoise = round(mapf(potRaw, 0, 4095, 0.0f, 0.10f) * 100.0f) / 100.0f;
                if (abs(newNoise - p.noiseLevel) > 0.005f) {
                    engine->updateNoiseLevel(newNoise);
                }
                break;
            }
            default: break;
        }
    }
}

// ============================================================================
// DISPLAY UPDATE
// ============================================================================
void updateDisplay() {
    uint32_t now = millis();
    SystemState state = stateMachine.getState();

    // --- Waveform update (50 Hz) ---
    if (now - lastWaveformUpdate >= WAVEFORM_UPDATE_MS) {
        lastWaveformUpdate = now;

        if (state == SystemState::SIMULATING && engine->getState() == SignalState::RUNNING) {
            float acValue = engine->getCurrentACValue();
            const float AC_MAX = 150.0f;  // Max AC for PI~10%
            tftDisplay.drawWaveformPoint(acValue, AC_MAX);
        }
    }

    // --- Metrics update (4 Hz) ---
    if (now - lastMetricsUpdate >= METRICS_UPDATE_MS) {
        lastMetricsUpdate = now;

        if (state == SystemState::SIMULATING || state == SystemState::PAUSED) {
            PPGParameters p = engine->getPPGParams();
            uint8_t cond = stateMachine.getSelectedCondition();
            tftDisplay.updateMetrics(p.heartRate, p.perfusionIndex, p.spO2, p.respRate, conditionNames[cond]);

            // Update footer based on edit mode
            UIEditMode mode = stateMachine.getEditMode();
            switch (mode) {
                case UIEditMode::CONDITION_SELECT:
                    tftDisplay.showConditionSelect(conditionNames[cond], cond);
                    break;
                case UIEditMode::EDIT_HR: {
                    PPGLimits lim = getPPGLimits(p.condition);
                    tftDisplay.showParamEdit("HR", p.heartRate, lim.heartRate.min, lim.heartRate.max);
                    break;
                }
                case UIEditMode::EDIT_PI: {
                    PPGLimits lim = getPPGLimits(p.condition);
                    tftDisplay.showParamEdit("PI", p.perfusionIndex, lim.perfusionIndex.min, lim.perfusionIndex.max);
                    break;
                }
                case UIEditMode::EDIT_SPO2: {
                    PPGLimits lim = getPPGLimits(p.condition);
                    tftDisplay.showParamEdit("SpO2", p.spO2, lim.spO2.min, lim.spO2.max);
                    break;
                }
                case UIEditMode::EDIT_RR: {
                    PPGLimits lim = getPPGLimits(p.condition);
                    tftDisplay.showParamEdit("RR", p.respRate, lim.respRate.min, lim.respRate.max);
                    break;
                }
                case UIEditMode::EDIT_NOISE:
                    tftDisplay.showParamEdit("Noise", p.noiseLevel * 100.0f, 0.0f, 10.0f);
                    break;
                default: break;
            }

        } else if (state == SystemState::SELECT_CONDITION) {
            uint8_t cond = stateMachine.getSelectedCondition();
            tftDisplay.updateMetrics(0, 0, 0, 0, conditionNames[cond]);
            tftDisplay.showConditionSelect(conditionNames[cond], cond);
        }
    }
}

// ============================================================================
// START SIMULATION
// ============================================================================
void startSimulationWithCondition(uint8_t condition) {
    Serial.printf("[SIM] Starting PPG: %s\n", conditionNames[condition]);
    engine->startSimulation(condition);
    stateMachine.setSelectedCondition(condition);
    stateMachine.setEditMode(UIEditMode::CONDITION_SELECT);
    tftDisplay.clearWaveform();
}

// ============================================================================
// STATE CHANGE CALLBACK
// ============================================================================
void onStateChange(SystemState oldState, SystemState newState) {
    Serial.printf("[STATE] %s → %s\n",
                  StateMachine::stateToString(oldState),
                  StateMachine::stateToString(newState));

    // Update status LED
    switch (newState) {
        case SystemState::SIMULATING:
            digitalWrite(LED_STATUS_PIN, LOW);   // LED off = running normally
            break;
        case SystemState::PAUSED:
            digitalWrite(LED_STATUS_PIN, HIGH);  // LED on = paused
            break;
        case SystemState::SELECT_CONDITION:
            // Blink pattern handled elsewhere if needed
            break;
        default:
            break;
    }
}
