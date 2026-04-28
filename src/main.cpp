/**
 * @file main.cpp
 * @brief PPG Signal Simulator — Main application
 * @version 2.0.0
 * @date 25 April 2026
 *
* Hardware: ESP32-S3 + 1.3" I2C OLED Display (SH1106) + MCP4725 DAC (I2C) *

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
#include "hw/mcp4725_dac.h"
#include "hw/button_handler.h"

// Communication
#include "comm/serial_handler.h"
#include "comm/ble_manager.h"

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
void handleButtons();
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

    // --- MCP4725 DAC ---
    Serial.println("[INIT] Starting MCP4725 DAC...");
    if (!ppgDAC.begin(MCP4725_I2C_ADDR)) {
        Serial.println("[INIT] ERROR: MCP4725 DAC not found! Check wiring.");
        Serial.println("[INIT] Continuing without DAC...");
    }

    // --- TFT Display ---
    Serial.println("[INIT] Starting TFT display...");
    tftDisplay.begin();
    tftDisplay.updateMetrics(0, 0, "Initializing...");

    // --- Buttons ---
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

    // --- BLE Manager ---
    bleManager.begin();

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
    handleButtons();

    // --- Update TFT display ---
    updateDisplay();

    // --- Process serial commands ---
    serialHandler.process();

    // --- Process BLE status/commands ---
    bleManager.process();

    // Small yield to prevent watchdog
    delay(1);
}

// ============================================================================
// BUTTON HANDLING
// ============================================================================
void handleButtons() {
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

    // --- UP BUTTON ---
    if (buttons.wasUpPressed()) {
        Serial.println("[BTN] Up pressed");

        if (state == SystemState::SELECT_CONDITION) {
            stateMachine.processEvent(SystemEvent::BTN_UP_PRESS);
            uint8_t cond = stateMachine.getSelectedCondition();
            Serial.printf("[BTN] Condition: %d (%s)\n", cond, conditionNames[cond]);

        } else if (state == SystemState::SIMULATING) {
            switch (editMode) {
                case UIEditMode::CONDITION_SELECT: {
                    // Next condition (live change)
                    uint8_t cond = stateMachine.getSelectedCondition();
                    cond = (cond + 1) % (uint8_t)PPGCondition::COUNT;
                    stateMachine.setSelectedCondition(cond);
                    engine->changeCondition(cond);
                    tftDisplay.clearWaveform();
                    Serial.printf("[BTN] Condition → %s\n", conditionNames[cond]);
                    break;
                }
                case UIEditMode::EDIT_HR: {
                    PPGParameters p = engine->getPPGParams();
                    PPGLimits lim = getPPGLimits(p.condition);
                    float newHR = min(p.heartRate + HR_STEP, lim.heartRate.max);
                    engine->updateHeartRate(newHR);
                    Serial.printf("[BTN] HR → %.0f BPM\n", newHR);
                    break;
                }
                case UIEditMode::EDIT_PI: {
                    PPGParameters p = engine->getPPGParams();
                    PPGLimits lim = getPPGLimits(p.condition);
                    float newPI = min(p.perfusionIndex + PI_STEP, lim.perfusionIndex.max);
                    engine->updatePerfusionIndex(newPI);
                    Serial.printf("[BTN] PI → %.1f%%\n", newPI);
                    break;
                }
                case UIEditMode::EDIT_NOISE: {
                    PPGParameters p = engine->getPPGParams();
                    float newNoise = min(p.noiseLevel + NOISE_STEP, 0.10f);
                    engine->updateNoiseLevel(newNoise);
                    Serial.printf("[BTN] Noise → %.0f%%\n", newNoise * 100.0f);
                    break;
                }
                default: break;
            }
        }
    }

    // --- DOWN BUTTON ---
    if (buttons.wasDownPressed()) {
        Serial.println("[BTN] Down pressed");

        if (state == SystemState::SELECT_CONDITION) {
            stateMachine.processEvent(SystemEvent::BTN_DOWN_PRESS);
            uint8_t cond = stateMachine.getSelectedCondition();
            Serial.printf("[BTN] Condition: %d (%s)\n", cond, conditionNames[cond]);

        } else if (state == SystemState::SIMULATING) {
            switch (editMode) {
                case UIEditMode::CONDITION_SELECT: {
                    uint8_t cond = stateMachine.getSelectedCondition();
                    if (cond == 0) cond = (uint8_t)PPGCondition::COUNT - 1;
                    else cond--;
                    stateMachine.setSelectedCondition(cond);
                    engine->changeCondition(cond);
                    tftDisplay.clearWaveform();
                    Serial.printf("[BTN] Condition → %s\n", conditionNames[cond]);
                    break;
                }
                case UIEditMode::EDIT_HR: {
                    PPGParameters p = engine->getPPGParams();
                    PPGLimits lim = getPPGLimits(p.condition);
                    float newHR = max(p.heartRate - HR_STEP, lim.heartRate.min);
                    engine->updateHeartRate(newHR);
                    Serial.printf("[BTN] HR → %.0f BPM\n", newHR);
                    break;
                }
                case UIEditMode::EDIT_PI: {
                    PPGParameters p = engine->getPPGParams();
                    PPGLimits lim = getPPGLimits(p.condition);
                    float newPI = max(p.perfusionIndex - PI_STEP, lim.perfusionIndex.min);
                    engine->updatePerfusionIndex(newPI);
                    Serial.printf("[BTN] PI → %.1f%%\n", newPI);
                    break;
                }
                case UIEditMode::EDIT_NOISE: {
                    PPGParameters p = engine->getPPGParams();
                    float newNoise = max(p.noiseLevel - NOISE_STEP, 0.0f);
                    engine->updateNoiseLevel(newNoise);
                    Serial.printf("[BTN] Noise → %.0f%%\n", newNoise * 100.0f);
                    break;
                }
                default: break;
            }
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
            
            // Send waveform over BLE
            bleManager.sendWaveformSample(acValue);
        }
        
        // Render current buffer to OLED display
        tftDisplay.renderFrame();
    }

    // --- Metrics update (4 Hz) ---
    if (now - lastMetricsUpdate >= METRICS_UPDATE_MS) {
        lastMetricsUpdate = now;

        if (state == SystemState::SIMULATING || state == SystemState::PAUSED) {
            PPGParameters p = engine->getPPGParams();
            uint8_t cond = stateMachine.getSelectedCondition();
            tftDisplay.updateMetrics(p.heartRate, p.perfusionIndex, conditionNames[cond]);

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
                case UIEditMode::EDIT_NOISE:
                    tftDisplay.showParamEdit("Noise", p.noiseLevel * 100.0f, 0.0f, 10.0f);
                    break;
                default: break;
            }

        } else if (state == SystemState::SELECT_CONDITION) {
            uint8_t cond = stateMachine.getSelectedCondition();
            tftDisplay.updateMetrics(0, 0, conditionNames[cond]);
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
