/**
 * @file param_controller.h
 * @brief PPG parameter controller with validation and clamping
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Manages PPG parameter updates with condition-specific limits.
 * Supports immediate (Type A) and deferred (Type B) parameter changes.
 */

#ifndef PARAM_CONTROLLER_H
#define PARAM_CONTROLLER_H

#include <Arduino.h>
#include "data/signal_types.h"
#include "data/param_limits.h"

class ParamController {
private:
    PPGParameters currentPPG;

    // Pending parameters (Type B: applied at next beat boundary)
    struct PendingParams {
        bool hasPending = false;
        PPGParameters pendingValue;
        uint32_t requestTime = 0;
    };
    PendingParams pendingPPG;

    // Utility
    static float clamp(float value, float min, float max);

public:
    ParamController();

    /**
     * @brief Set active condition
     * @param condition PPG condition index (0–5)
     */
    void setCondition(uint8_t condition);

    // Type A parameters (immediate application)
    void setNoiseLevel(float noise);
    void setAmplitude(float amplitude);

    // Type B parameters (deferred to next beat)
    void setHeartRate(float hr);
    void setPerfusionIndex(float pi);

    // Apply pending parameters
    bool applyPendingParams();
    bool hasPendingParams() const;

    // Getters
    const PPGParameters& getCurrentParams() const { return currentPPG; }
    PPGLimits getCurrentLimits() const;

    // Validation
    bool validateParams(const PPGParameters& params);

    // Reset to defaults
    void resetToDefaults();
};

#endif // PARAM_CONTROLLER_H
