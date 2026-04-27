/**
 * @file signal_engine.h
 * @brief PPG signal generation engine with real-time output
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Architecture:
 * - PPG model generates samples at 100 Hz on Core 1
 * - Linear interpolation upsamples to 1 kHz for DAC output
 * - Ring buffer connects generation task to DAC output loop
 * - MCP4725 DAC writes 12-bit values via I2C
 */

#ifndef SIGNAL_ENGINE_H
#define SIGNAL_ENGINE_H

#include <Arduino.h>
#include "config.h"
#include "data/signal_types.h"
#include "models/ppg_model.h"
#include "hw/dac_manager.h"

class SignalEngine {
private:
    // Singleton
    static SignalEngine* instance;

    // Signal state
    SignalInfo currentSignal;

    // PPG model
    PPGModel ppgModel;

    // FreeRTOS
    SemaphoreHandle_t signalMutex;
    TaskHandle_t generationTaskHandle;

    // Private methods
    static void generationTask(void* parameter);
    void prefillBuffer();
    void generateBothSamples();

    // Constructor (private — singleton)
    SignalEngine();

public:
    static SignalEngine* getInstance();

    /**
     * @brief Initialize the signal engine (creates generation task on Core 1)
     * @return true if successful
     */
    bool begin();

    /**
     * @brief Start PPG simulation with given condition
     * @param condition PPG condition index (0–5)
     * @return true if started successfully
     */
    bool startSimulation(uint8_t condition);

    /**
     * @brief Stop the current simulation
     */
    bool stopSimulation();

    /**
     * @brief Pause the current simulation
     */
    bool pauseSimulation();

    /**
     * @brief Resume a paused simulation
     */
    bool resumeSimulation();

    // =========================================================================
    // PARAMETER UPDATES
    // =========================================================================

    /** @brief Update noise level (Type A: immediate) */
    void updateNoiseLevel(float noise);

    /** @brief Update heart rate */
    void updateHeartRate(float hr);

    /** @brief Update perfusion index */
    void updatePerfusionIndex(float pi);

    /** @brief Update SpO2 */
    void updateSpO2(float spo2);

    /** @brief Update respiratory rate */
    void updateRespRate(float rr);

    /** @brief Set pending PPG parameters (Type B: deferred to next beat) */
    void setPPGParameters(const PPGParameters& params);

    /** @brief Change condition (restarts signal) */
    void changeCondition(uint8_t condition);

    // =========================================================================
    // GETTERS
    // =========================================================================

    SignalState getState() const { return currentSignal.state; }
    SignalType getType() const { return currentSignal.type; }
    const PPGParameters& getPPGParams() const { return currentSignal.ppg; }
    PPGModel& getPPGModel() { return ppgModel; }

    /** @brief Get last DAC value written */
    uint16_t getLastDACValue() const;

    /** @brief Get current AC value in mV (for TFT display) */
    float getCurrentACValue() const;

    /** @brief Get performance statistics */
    PerformanceStats getStats() const;
};

#endif // SIGNAL_ENGINE_H
