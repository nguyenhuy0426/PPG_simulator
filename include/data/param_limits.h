/**
 * @file param_limits.h
 * @brief Parameter limits for PPG signal conditions
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Defines physiological parameter ranges per PPG condition.
 * Used by ParamController for validation and clamping.
 */

#ifndef PARAM_LIMITS_H
#define PARAM_LIMITS_H

#include "signal_types.h"

// ============================================================================
// PARAMETER RANGE STRUCTURE
// ============================================================================
struct ParamRange {
    float min;
    float max;
    float defaultVal;
};

// ============================================================================
// PPG LIMITS STRUCTURE
// ============================================================================
struct PPGLimits {
    ParamRange heartRate;
    ParamRange perfusionIndex;
    ParamRange noiseLevel;
    ParamRange dicroticNotch;
    ParamRange amplification;
};

// ============================================================================
// PPG LIMITS BY CONDITION
// ============================================================================
inline PPGLimits getPPGLimits(PPGCondition condition) {
    switch (condition) {
        case PPGCondition::NORMAL:
            return {
                .heartRate      = {60.0f,  100.0f, 75.0f},
                .perfusionIndex = {2.9f,   6.1f,   3.0f},
                .noiseLevel     = {0.0f,   0.10f,  0.0f},
                .dicroticNotch  = {0.15f,  0.35f,  0.25f},
                .amplification  = {0.5f,   2.0f,   1.0f}
            };
            
        case PPGCondition::ARRHYTHMIA:
            return {
                .heartRate      = {60.0f,  180.0f, 80.0f},
                .perfusionIndex = {1.0f,   5.0f,   2.5f},
                .noiseLevel     = {0.0f,   0.10f,  0.0f},
                .dicroticNotch  = {0.10f,  0.30f,  0.20f},
                .amplification  = {0.5f,   2.0f,   1.0f}
            };
            
        case PPGCondition::WEAK_PERFUSION:
            return {
                .heartRate      = {70.0f,  120.0f, 90.0f},
                .perfusionIndex = {0.5f,   2.1f,   1.0f},
                .noiseLevel     = {0.0f,   0.10f,  0.0f},
                .dicroticNotch  = {0.0f,   0.10f,  0.05f},
                .amplification  = {0.5f,   2.0f,   1.0f}
            };
            
        case PPGCondition::VASOCONSTRICTION:
            return {
                .heartRate      = {65.0f,  110.0f, 80.0f},
                .perfusionIndex = {0.5f,   0.8f,   0.7f},
                .noiseLevel     = {0.0f,   0.10f,  0.0f},
                .dicroticNotch  = {0.0f,   0.10f,  0.05f},
                .amplification  = {0.5f,   2.0f,   1.0f}
            };
            
        case PPGCondition::STRONG_PERFUSION:
            return {
                .heartRate      = {60.0f,  90.0f,  70.0f},
                .perfusionIndex = {7.0f,   20.0f,  10.0f},
                .noiseLevel     = {0.0f,   0.10f,  0.0f},
                .dicroticNotch  = {0.25f,  0.45f,  0.35f},
                .amplification  = {0.5f,   2.0f,   1.0f}
            };
            
        case PPGCondition::VASODILATION:
            return {
                .heartRate      = {60.0f,  90.0f,  65.0f},
                .perfusionIndex = {5.0f,   10.0f,  7.0f},
                .noiseLevel     = {0.0f,   0.10f,  0.0f},
                .dicroticNotch  = {0.20f,  0.40f,  0.30f},
                .amplification  = {0.5f,   2.0f,   1.0f}
            };
            
        default:
            return {
                .heartRate      = {60.0f,  100.0f, 75.0f},
                .perfusionIndex = {2.9f,   6.1f,   3.0f},
                .noiseLevel     = {0.0f,   0.10f,  0.0f},
                .dicroticNotch  = {0.15f,  0.35f,  0.25f},
                .amplification  = {0.5f,   2.0f,   1.0f}
            };
    }
}

// ============================================================================
// HR/PI STEP VALUES FOR BUTTON CONTROL
// ============================================================================
#define HR_STEP             5.0f    // BPM per button press
#define PI_STEP             0.5f    // % per button press
#define NOISE_STEP          0.01f   // 1% per button press

#endif // PARAM_LIMITS_H
