/**
 * @file param_controller.cpp
 * @brief PPG parameter controller implementation
 * @version 2.0.0
 * @date 25 April 2026
 */

#include "core/param_controller.h"

// ============================================================================
// CONSTRUCTOR
// ============================================================================
ParamController::ParamController() {
    resetToDefaults();
}

// ============================================================================
// SET CONDITION
// ============================================================================
void ParamController::setCondition(uint8_t condition) {
    PPGParameters pending = currentPPG;
    pending.condition = static_cast<PPGCondition>(condition);

    // Re-clamp parameters to new condition limits
    PPGLimits newLimits = getPPGLimits(pending.condition);
    pending.heartRate = clamp(pending.heartRate, newLimits.heartRate.min, newLimits.heartRate.max);
    pending.perfusionIndex = clamp(pending.perfusionIndex, newLimits.perfusionIndex.min, newLimits.perfusionIndex.max);
    pending.dicroticNotch = clamp(pending.dicroticNotch, newLimits.dicroticNotch.min, newLimits.dicroticNotch.max);

    pendingPPG.hasPending = true;
    pendingPPG.pendingValue = pending;
    pendingPPG.requestTime = millis();
}

// ============================================================================
// TYPE A PARAMETERS (IMMEDIATE)
// ============================================================================
void ParamController::setNoiseLevel(float noise) {
    noise = clamp(noise, 0.0f, 0.10f);
    currentPPG.noiseLevel = noise;
}

void ParamController::setAmplitude(float amplitude) {
    float ampFactor = clamp(amplitude / 100.0f, 0.5f, 2.0f);
    currentPPG.amplification = ampFactor;
}

// ============================================================================
// TYPE B PARAMETERS (DEFERRED)
// ============================================================================
void ParamController::setHeartRate(float hr) {
    PPGLimits limits = getPPGLimits(currentPPG.condition);
    PPGParameters pending = currentPPG;
    pending.heartRate = clamp(hr, limits.heartRate.min, limits.heartRate.max);
    pendingPPG.hasPending = true;
    pendingPPG.pendingValue = pending;
    pendingPPG.requestTime = millis();
}

void ParamController::setPerfusionIndex(float pi) {
    PPGLimits limits = getPPGLimits(currentPPG.condition);
    PPGParameters pending = currentPPG;
    pending.perfusionIndex = clamp(pi, limits.perfusionIndex.min, limits.perfusionIndex.max);
    pendingPPG.hasPending = true;
    pendingPPG.pendingValue = pending;
    pendingPPG.requestTime = millis();
}

// ============================================================================
// APPLY PENDING PARAMETERS
// ============================================================================
bool ParamController::applyPendingParams() {
    if (pendingPPG.hasPending) {
        currentPPG = pendingPPG.pendingValue;
        pendingPPG.hasPending = false;
        return true;
    }
    return false;
}

bool ParamController::hasPendingParams() const {
    return pendingPPG.hasPending;
}

// ============================================================================
// GETTERS
// ============================================================================
PPGLimits ParamController::getCurrentLimits() const {
    return getPPGLimits(currentPPG.condition);
}

// ============================================================================
// VALIDATION
// ============================================================================
bool ParamController::validateParams(const PPGParameters& params) {
    PPGLimits limits = getPPGLimits(params.condition);
    if (params.heartRate < limits.heartRate.min || params.heartRate > limits.heartRate.max) return false;
    if (params.noiseLevel < 0.0f || params.noiseLevel > 0.10f) return false;
    if (params.perfusionIndex < limits.perfusionIndex.min || params.perfusionIndex > limits.perfusionIndex.max) return false;
    if (params.dicroticNotch < limits.dicroticNotch.min || params.dicroticNotch > limits.dicroticNotch.max) return false;
    return true;
}

// ============================================================================
// RESET TO DEFAULTS
// ============================================================================
void ParamController::resetToDefaults() {
    currentPPG = PPGParameters();
    pendingPPG.hasPending = false;
}

// ============================================================================
// UTILITY
// ============================================================================
float ParamController::clamp(float value, float min, float max) {
    if (value < min) return min;
    if (value > max) return max;
    return value;
}
