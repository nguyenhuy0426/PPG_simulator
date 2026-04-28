/**
 * @file signal_types.h
 * @brief Signal types and data structures for PPG Signal Simulator
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Defines PPG conditions, parameters, system states, and common structures.
 */

#ifndef SIGNAL_TYPES_H
#define SIGNAL_TYPES_H

#include <Arduino.h>

// ============================================================================
// SIGNAL TYPE (PPG only)
// ============================================================================
enum class SignalType : uint8_t {
    NONE = 0,
    PPG  = 1
};

// ============================================================================
// SIGNAL STATE
// ============================================================================
enum class SignalState : uint8_t {
    STOPPED = 0,
    RUNNING = 1,
    PAUSED  = 2,
    ERROR   = 3
};

// ============================================================================
// PPG CONDITIONS (6 clinical conditions)
// ============================================================================
enum class PPGCondition : uint8_t {
    NORMAL              = 0,
    ARRHYTHMIA          = 1,
    WEAK_PERFUSION      = 2,
    VASOCONSTRICTION    = 3,
    STRONG_PERFUSION    = 4,
    VASODILATION        = 5,
    
    COUNT               = 6     // Total number of conditions
};

// ============================================================================
// PPG PARAMETERS
// ============================================================================
struct PPGParameters {
    PPGCondition condition = PPGCondition::NORMAL;
    float heartRate = 75.0f;            // BPM (40–180)
    float perfusionIndex = 3.0f;        // PI % (0.5–20)
    float noiseLevel = 0.0f;            // 0.0–0.10 (0–10%)
    float dicroticNotch = 0.25f;        // Notch depth (0.0–1.0)
    float amplification = 1.0f;         // Waveform gain (0.5–2.0)
};

// ============================================================================
// SYSTEM STATE MACHINE
// ============================================================================
enum class SystemState : uint8_t {
    INIT                = 0,
    SELECT_CONDITION    = 1,    // User selects PPG condition
    SIMULATING          = 2,    // Active signal generation
    PAUSED              = 3,    // Simulation paused
    ERROR               = 4
};

// ============================================================================
// SYSTEM EVENTS
// ============================================================================
enum class SystemEvent : uint8_t {
    INIT_COMPLETE = 0,
    
    // Button events
    BTN_MODE_PRESS,             // Mode button pressed
    BTN_UP_PRESS,               // Up button pressed
    BTN_DOWN_PRESS,             // Down button pressed
    
    // Simulation control
    SELECT_CONDITION,           // param = condition index (0–5)
    START_SIMULATION,
    PAUSE,
    RESUME,
    STOP,
    
    // Error
    ERROR_OCCURRED
};

// ============================================================================
// UI EDIT MODE (what parameter the buttons control)
// ============================================================================
enum class UIEditMode : uint8_t {
    CONDITION_SELECT = 0,       // Up/Down selects condition
    EDIT_HR          = 1,       // Up/Down adjusts heart rate
    EDIT_PI          = 2,       // Up/Down adjusts perfusion index
    EDIT_NOISE       = 3,       // Up/Down adjusts noise level
    
    COUNT            = 4        // Total number of modes
};

// ============================================================================
// SIGNAL INFO STRUCTURE
// ============================================================================
struct SignalInfo {
    SignalType type = SignalType::NONE;
    SignalState state = SignalState::STOPPED;
    PPGParameters ppg;
    uint32_t sampleCount = 0;
    uint32_t lastUpdateTime = 0;
};

// ============================================================================
// PERFORMANCE STATISTICS
// ============================================================================
struct PerformanceStats {
    uint32_t isrCount;
    uint32_t isrMaxTime;
    uint32_t bufferUnderruns;
    uint16_t bufferLevel;
    uint32_t freeHeap;
};

#endif // SIGNAL_TYPES_H
