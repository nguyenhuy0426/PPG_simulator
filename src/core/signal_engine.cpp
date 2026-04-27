/**
 * @file signal_engine.cpp
 * @brief PPG signal generation engine implementation
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Generation pipeline:
 *   PPG Model (100 Hz) → Interpolation → Ring Buffer (1 kHz) → MCP4725 DAC
 */

#include "core/signal_engine.h"
#include "config.h"
#include "hw/dac_manager.h"

// ============================================================================
// SINGLETON
// ============================================================================
SignalEngine* SignalEngine::instance = nullptr;

// ============================================================================
// BUFFERS IN FAST RAM
// ============================================================================
DRAM_ATTR static uint16_t signalBufferIR[SIGNAL_BUFFER_SIZE];
DRAM_ATTR static uint16_t signalBufferRed[SIGNAL_BUFFER_SIZE];
DRAM_ATTR static float displayBufferIR[SIGNAL_BUFFER_SIZE];
DRAM_ATTR static volatile uint16_t bufferReadIndex = 0;
DRAM_ATTR static volatile uint16_t bufferWriteIndex = 0;
DRAM_ATTR static volatile uint32_t isrCount = 0;
DRAM_ATTR static volatile uint32_t bufferUnderruns = 0;

// Timing and interpolation variables
static uint32_t lastModelTick_us = 0;
static uint16_t currentModelSampleIR = DAC_CENTER_VALUE;
static uint16_t currentModelSampleRed = DAC_CENTER_VALUE;
static uint16_t previousModelSampleIR = DAC_CENTER_VALUE;
static uint16_t previousModelSampleRed = DAC_CENTER_VALUE;
static float currentModelValueIR_MV = 0.0f;
static float previousModelValueIR_MV = 0.0f;
static uint16_t interpolationCounter = 0;

// DAC output timing
static uint32_t lastDACWrite_us = 0;
static const uint32_t DAC_WRITE_INTERVAL_US = 1000000 / FS_TIMER_HZ; // 1000 us = 1 kHz

// ============================================================================
// CONSTRUCTOR
// ============================================================================
SignalEngine::SignalEngine() {
    currentSignal.type = SignalType::NONE;
    currentSignal.state = SignalState::STOPPED;

    signalMutex = xSemaphoreCreateMutex();
    generationTaskHandle = nullptr;
}

SignalEngine* SignalEngine::getInstance() {
    if (instance == nullptr) {
        instance = new SignalEngine();
    }
    return instance;
}

// ============================================================================
// INITIALIZATION
// ============================================================================
bool SignalEngine::begin() {
    DEBUG_PRINTLN("[SignalEngine] Initializing...");

    // Set DAC to center
    dacManager.setValues(DAC_CENTER_VALUE, DAC_CENTER_VALUE);

    // Create generation task on Core 1
    BaseType_t taskCreated = xTaskCreatePinnedToCore(
        generationTask,
        "SignalGen",
        STACK_SIZE_SIGNAL,
        this,
        TASK_PRIORITY_SIGNAL,
        &generationTaskHandle,
        CORE_SIGNAL_GENERATION
    );

    if (taskCreated != pdPASS) {
        DEBUG_PRINTLN("[SignalEngine] ERROR: Could not create task");
        return false;
    }

    DEBUG_PRINTLN("[SignalEngine] Initialized successfully");
    return true;
}

// ============================================================================
// SIMULATION CONTROL
// ============================================================================
bool SignalEngine::startSimulation(uint8_t condition) {
    Serial.printf("[SignalEngine] Starting PPG simulation, condition=%d\n", condition);

    if (xSemaphoreTake(signalMutex, portMAX_DELAY) == pdTRUE) {
        // Stop current if running
        if (currentSignal.state == SignalState::RUNNING) {
            currentSignal.state = SignalState::STOPPED;
        }

        // Reset buffers and timing
        bufferReadIndex = 0;
        bufferWriteIndex = 0;
        isrCount = 0;
        bufferUnderruns = 0;
        lastModelTick_us = micros();
        currentModelSampleIR = DAC_CENTER_VALUE;
        currentModelSampleRed = DAC_CENTER_VALUE;
        previousModelSampleIR = DAC_CENTER_VALUE;
        previousModelSampleRed = DAC_CENTER_VALUE;
        currentModelValueIR_MV = 0.0f;
        previousModelValueIR_MV = 0.0f;
        interpolationCounter = 0;

        // Configure signal
        currentSignal.type = SignalType::PPG;
        currentSignal.sampleCount = 0;
        currentSignal.lastUpdateTime = millis();

        // Reset and configure PPG model
        ppgModel.reset();
        yield();
        PPGParameters params;
        params.condition = (PPGCondition)condition;
        ppgModel.setParameters(params);
        currentSignal.ppg = params;
        yield();

        Serial.printf("[PPG] Condition: %d (%s)\n", condition, ppgModel.getConditionName());

        // Pre-fill buffer
        prefillBuffer();

        currentSignal.state = SignalState::RUNNING;
        lastDACWrite_us = micros();

        xSemaphoreGive(signalMutex);
        return true;
    }
    return false;
}

bool SignalEngine::stopSimulation() {
    if (xSemaphoreTake(signalMutex, portMAX_DELAY) == pdTRUE) {
        currentSignal.state = SignalState::STOPPED;
        currentSignal.type = SignalType::NONE;
        dacManager.setValues(DAC_CENTER_VALUE, DAC_CENTER_VALUE);
        xSemaphoreGive(signalMutex);
        return true;
    }
    return false;
}

bool SignalEngine::pauseSimulation() {
    if (currentSignal.state == SignalState::RUNNING) {
        currentSignal.state = SignalState::PAUSED;
        return true;
    }
    return false;
}

bool SignalEngine::resumeSimulation() {
    if (currentSignal.state == SignalState::PAUSED) {
        currentSignal.state = SignalState::RUNNING;
        return true;
    }
    return false;
}

// ============================================================================
// GENERATION TASK (Core 1)
// ============================================================================
void SignalEngine::generationTask(void* parameter) {
    SignalEngine* engine = (SignalEngine*)parameter;

    lastModelTick_us = micros();
    interpolationCounter = 0;

    while (true) {
        if (engine->currentSignal.state == SignalState::RUNNING) {
            uint32_t now_us = micros();

            // --- Generate new PPG model sample at MODEL_SAMPLE_RATE_PPG ---
            if (now_us - lastModelTick_us >= MODEL_TICK_US_PPG) {
                lastModelTick_us = now_us;

                // Save previous sample for interpolation
                previousModelSampleIR = currentModelSampleIR;
                previousModelSampleRed = currentModelSampleRed;
                previousModelValueIR_MV = currentModelValueIR_MV;

                // Generate new PPG samples
                float sampleIR_mV, sampleRed_mV;
                engine->ppgModel.generateBothSamples(MODEL_DT_PPG, sampleIR_mV, sampleRed_mV);
                
                float dcBaseline = engine->ppgModel.getDCBaseline();
                const float MAX_AC_AMPLITUDE = 150.0f; // Approx max AC variation
                
                // Map to 12-bit DAC values
                currentModelSampleIR = dacManager.ppgSampleToDACValue(sampleIR_mV, dcBaseline, MAX_AC_AMPLITUDE);
                currentModelSampleRed = dacManager.ppgSampleToDACValue(sampleRed_mV, dcBaseline, MAX_AC_AMPLITUDE);
                
                currentModelValueIR_MV = engine->ppgModel.getLastDisplay_IR();

                // Reset interpolation counter
                interpolationCounter = 0;
            }

            // --- Fill ring buffer with interpolated samples ---
            uint16_t readIdx = bufferReadIndex;
            uint16_t writeIdx = bufferWriteIndex;
            uint16_t available = (readIdx - writeIdx - 1 + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE;

            while (available > 0) {
                // Linear interpolation
                float t = (float)interpolationCounter / (float)UPSAMPLE_RATIO_PPG;
                int32_t interpolatedIR = previousModelSampleIR +
                    (int32_t)((int32_t)currentModelSampleIR - (int32_t)previousModelSampleIR) * t;
                int32_t interpolatedRed = previousModelSampleRed +
                    (int32_t)((int32_t)currentModelSampleRed - (int32_t)previousModelSampleRed) * t;
                    
                float interpolatedIR_MV = previousModelValueIR_MV +
                    (currentModelValueIR_MV - previousModelValueIR_MV) * t;

                // Clamp to 12-bit range
                if (interpolatedIR < 0) interpolatedIR = 0;
                if (interpolatedIR > 4095) interpolatedIR = 4095;
                if (interpolatedRed < 0) interpolatedRed = 0;
                if (interpolatedRed > 4095) interpolatedRed = 4095;

                // Write to buffers
                signalBufferIR[writeIdx] = (uint16_t)interpolatedIR;
                signalBufferRed[writeIdx] = (uint16_t)interpolatedRed;
                displayBufferIR[writeIdx] = interpolatedIR_MV; // For TFT display
                
                writeIdx = (writeIdx + 1) % SIGNAL_BUFFER_SIZE;
                bufferWriteIndex = writeIdx;
                available--;
                engine->currentSignal.sampleCount++;

                // Advance interpolation
                interpolationCounter++;
                if (interpolationCounter >= UPSAMPLE_RATIO_PPG) {
                    interpolationCounter = 0;
                    previousModelValueIR_MV = currentModelValueIR_MV;
                }
            }

            // --- Write to MCP4725 DAC at ~1 kHz ---
            if (now_us - lastDACWrite_us >= DAC_WRITE_INTERVAL_US) {
                lastDACWrite_us = now_us;

                if (bufferReadIndex != bufferWriteIndex) {
                    uint16_t outIR = signalBufferIR[bufferReadIndex];
                    uint16_t outRed = signalBufferRed[bufferReadIndex];
                    bufferReadIndex = (bufferReadIndex + 1) % SIGNAL_BUFFER_SIZE;

                    // Write to dual external DACs via I2C
                    dacManager.setValues(outIR, outRed);
                    isrCount++;
                } else {
                    bufferUnderruns++;
                }
            }
        }

        // Small delay to avoid saturating CPU
        vTaskDelay(1);
    }
}

// ============================================================================
// PARAMETER UPDATES
// ============================================================================
void SignalEngine::updateNoiseLevel(float noise) {
    noise = constrain(noise, 0.0f, 0.10f);
    currentSignal.ppg.noiseLevel = noise;
    ppgModel.setNoiseLevel(noise);
}

void SignalEngine::updateHeartRate(float hr) {
    ppgModel.setHeartRate(hr);
    currentSignal.ppg.heartRate = hr;
}

void SignalEngine::updatePerfusionIndex(float pi) {
    ppgModel.setPerfusionIndex(pi);
    currentSignal.ppg.perfusionIndex = pi;
}

void SignalEngine::updateSpO2(float spo2) {
    currentSignal.ppg.spO2 = spo2;
    // SpO2 logic is processed at generation inside PPGModel
}

void SignalEngine::updateRespRate(float rr) {
    currentSignal.ppg.respRate = rr;
    // RR logic is processed at generation inside PPGModel
}

void SignalEngine::setPPGParameters(const PPGParameters& params) {
    ppgModel.setPendingParameters(params);
}

void SignalEngine::changeCondition(uint8_t condition) {
    // Restart simulation with new condition
    if (currentSignal.state == SignalState::RUNNING ||
        currentSignal.state == SignalState::PAUSED) {
        startSimulation(condition);
    }
}

// ============================================================================
// BUFFER PRE-FILL
// ============================================================================
void SignalEngine::prefillBuffer() {
    float dcBaseline = ppgModel.getDCBaseline();
    for (int i = 0; i < SIGNAL_BUFFER_SIZE / 2; i++) {
        signalBufferIR[i] = dacManager.ppgSampleToDACValue(dcBaseline, dcBaseline, 150.0f);
        signalBufferRed[i] = signalBufferIR[i];
        displayBufferIR[i] = 0.0f;
    }
    bufferWriteIndex = SIGNAL_BUFFER_SIZE / 2;
}

// ============================================================================
// GETTERS
// ============================================================================
uint16_t SignalEngine::getLastDACValue() const {
    return dacManager.isReady() ? DAC_CENTER_VALUE : 0; // Legacy or unused now
}

float SignalEngine::getCurrentACValue() const {
    uint16_t readIdx = (bufferReadIndex - 1 + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE;
    return displayBufferIR[readIdx];
}

PerformanceStats SignalEngine::getStats() const {
    PerformanceStats stats;
    stats.isrCount = isrCount;
    stats.isrMaxTime = 0;
    stats.bufferUnderruns = bufferUnderruns;
    stats.bufferLevel = (bufferWriteIndex - bufferReadIndex + SIGNAL_BUFFER_SIZE) % SIGNAL_BUFFER_SIZE;
    stats.freeHeap = ESP.getFreeHeap();
    return stats;
}
