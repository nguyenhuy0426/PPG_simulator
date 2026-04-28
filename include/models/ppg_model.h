/**
 * @file ppg_model.h
 * @brief PPG model with double Gaussian and 6 clinical conditions
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Physiological photoplethysmography model:
 * - Systole ~constant, diastole variable (compresses with high HR)
 * - Dynamic PI as ONLY AC amplitude control
 * - Normalized waveform [0,1] with smooth modifiers per condition
 *
 * Model flow:
 *   Pathology → HR,PI (dynamic within range) → RR=60/HR
 *   → systole_time=f(HR), diastole_time=RR-systole
 *   → pulseShape normalized [0,1] → AC=PI*scale → signal=DC+pulse*AC
 *
 * References:
 * - Allen J. Physiol Meas. 2007: Qualitative morphological description PPG
 * - Sun X et al. 2024: PI beat-to-beat variability
 * - Cardiovascular physiology: ~constant systole, variable diastole
 * - Numerical parameters: empirically adjusted
 */

#ifndef PPG_MODEL_H
#define PPG_MODEL_H

#include <Arduino.h>
#include "../data/signal_types.h"
#include "../core/digital_filters.h"

// ============================================================================
// PPG MODEL BASE CONSTANTS (Empirically adjusted)
// 3-component structure based on Allen 2007 morphological description
// ============================================================================

// --- Temporal positions (fraction of RR cycle) ---
#define PPG_SYSTOLIC_POS    0.15f   // Systolic peak: ~15% of cycle
#define PPG_NOTCH_POS       0.30f   // Dicrotic notch: ~30% (aortic valve closure)
#define PPG_DIASTOLIC_POS   0.40f   // Diastolic peak: ~40% (reflected wave)

// --- Gaussian widths (normalized standard deviation) ---
#define PPG_SYSTOLIC_WIDTH  0.055f  // Systolic σ
#define PPG_DIASTOLIC_WIDTH 0.10f   // Diastolic σ (wider)
#define PPG_NOTCH_WIDTH     0.02f   // Notch σ (fast valvular event)

// --- Normalized BASE amplitudes (empirically adjusted) ---
#define PPG_BASE_SYSTOLIC_AMPL   1.0f    // Systolic base amplitude (reference)
#define PPG_BASE_DIASTOLIC_RATIO 0.4f    // Diastolic/systolic ratio
#define PPG_BASE_DICROTIC_DEPTH  0.25f   // Base notch depth

// --- AC scaling ---
// Clinical formula: PI = (AC / DC) × 100%
// Rearranging:      AC = PI × DC / 100
// With DC = 1500 mV (1.5V):
//                   AC = PI × 1500 / 100 = PI × 15 mV
// Examples: PI=3% → AC=45mV, PI=10% → AC=150mV
#define PPG_AC_SCALE_PER_PI  15.0f  // = DC / 100 = 1500 / 100

// --- Systolic duration (physiology: ~constant, ~300ms at rest) ---
// Systole varies little with HR; diastole absorbs the change
#define PPG_SYSTOLE_BASE_MS  300.0f  // Base systolic duration in ms
#define PPG_SYSTOLE_MIN_MS   250.0f  // Minimum at very high HR
#define PPG_SYSTOLE_MAX_MS   350.0f  // Maximum at very low HR

// ============================================================================
// CONDITION RANGES STRUCTURE (per clinical condition)
// ============================================================================
struct ConditionRanges {
    // Dynamic ranges
    float hrMin, hrMax;       // HR range (BPM)
    float hrCV;               // HR coefficient of variation (<10% normal, >10% arrhythmia)
    float piMin, piMax;       // PI range (%)
    float piCV;               // PI coefficient of variation
    // Waveform shape values (3-component structure, adjusted by pathology)
    float systolicAmpl;       // Systolic amplitude (base 1.0)
    float diastolicAmpl;      // Diastolic amplitude (base 0.4, d/s ratio)
    float dicroticDepth;      // Dicrotic notch depth
};

// ============================================================================
// PPGModel CLASS
// ============================================================================
class PPGModel {
private:
    // Temporal state
    float phaseInCycle;         // Current phase (0-1)
    float currentRR;            // Current RR interval (seconds)
    uint32_t beatCount;

    // Gaussian generator state (Box-Muller)
    bool gaussHasSpare;
    float gaussSpare;

    // Waveform shape parameters (normalized, NOT in mV)
    float systolicAmplitude;    // Systolic scale (base 1.0)
    float systolicWidth;        // Systolic σ
    float diastolicAmplitude;   // Diastolic scale (base 0.4)
    float diastolicWidth;       // Diastolic σ
    float dicroticDepth;        // Notch depth (base 0.25)
    float dicroticWidth;        // Notch σ

    // Input parameters
    PPGParameters params;

    // Pending parameters (Type B)
    bool hasPendingParams;
    PPGParameters pendingParams;

    // Artifact variables
    float motionNoise;
    float baselineWander;

    // Last generated sample value
    float lastSampleValue;
    float lastACValue;          // Last AC value (without DC)

    // Dynamic HR and PI (current value within pathology range)
    float currentHR;            // Instantaneous HR (BPM)
    float currentPI;            // Instantaneous PI (%)

    // Current condition ranges
    ConditionRanges condRanges;

    // === REAL-TIME MEASUREMENT VARIABLES ===
    // Values measured each cycle
    float measuredPeakValue;        // Measured systolic peak value (mV)
    float measuredValleyValue;      // Measured valley (pulse start) value (mV)
    float measuredNotchValue;       // Measured dicrotic notch value (mV)

    // Max/min tracking within current cycle
    float currentCyclePeak;         // Current cycle maximum
    float currentCycleValley;       // Current cycle minimum
    float currentCycleNotch;        // Minimum in notch zone

    // Accumulated simulated time (ms)
    float simulatedTime_ms;         // Total simulated time
    float lastPeakTime_ms;          // Time of last peak (simulated)
    float lastValleyTime_ms;        // Time of last valley (simulated)
    float cycleStartTime_ms;        // Current cycle start

    // Measured metrics
    float measuredRRInterval_ms;    // Measured RR interval (ms)
    float measuredSystoleTime_ms;   // Measured systolic time (ms)
    float measuredDiastoleTime_ms;  // Measured diastolic time (ms)

    // Previous phase state
    float previousPhase;            // Previous phase for transition detection

    // Calculated phase times
    float systoleTime;          // Systole duration (ms) - ~constant
    float diastoleTime;         // Diastole duration (ms) - variable
    float systoleFraction;      // Fraction of cycle for systole

    // Configurable DC baseline
    float dcBaseline;           // DC level in mV (0 = pure AC signal)

    // Digital filtering
    SignalFilterChain filterChain;      // Filter chain HP + LP + Notch
    bool filteringEnabled;              // Filtering control

    // Private methods
    void initConditionRanges();                 // Initialize ranges by condition
    float generateDynamicHR();                  // HR within range with variability
    float generateDynamicPI();                  // PI within range with variability
    float calculateSystoleFraction(float hr);   // f(HR) → systolic fraction
    float generateNextRR();
    float gaussianRandom(float mean, float std);
    float computePulseShape(float phase);       // Returns normalized shape [0,1]
    float normalizePulse(float rawPulse);       // Normalizes to [0,1]
    void applyConditionModifiers();
    void detectBeatAndApplyPending();

    // Conversion (12-bit for MCP4725)
    uint16_t voltageToDACValue12(float voltage);
    uint16_t acValueToDACValue12(float acValue_mV);

public:
    PPGModel();

    // Configuration
    void setParameters(const PPGParameters& newParams);
    void setPendingParameters(const PPGParameters& newParams);
    void reset();

    // =========================================================================
    // ADJUSTABLE PARAMETERS (via button controls)
    // =========================================================================
    // HR: 40-180 BPM — Only changes cycle duration, not waveform shape
    void setHeartRate(float hr) {
        hr = constrain(hr, 40.0f, 180.0f);
        params.heartRate = hr;
        currentHR = hr;
        currentRR = 60.0f / hr;
        systoleFraction = calculateSystoleFraction(hr);
        systoleTime = currentRR * 1000.0f * systoleFraction;
        diastoleTime = currentRR * 1000.0f * (1.0f - systoleFraction);
    }

    // PI: 0.5-20% — Modulates AC amplitude, does not affect peak or notch position
    void setPerfusionIndex(float pi) {
        pi = constrain(pi, 0.5f, 20.0f);
        params.perfusionIndex = pi;
        currentPI = pi;
    }

    // Noise: 0-1 — Gaussian noise proportional to AC
    void setNoiseLevel(float noise) {
        params.noiseLevel = constrain(noise, 0.0f, 1.0f);
    }

    // Alias for compatibility
    void setAmplitude(float amp) { setPerfusionIndex(amp); }

    // DC baseline configuration
    void setDCBaseline(float dc) { dcBaseline = dc; }
    float getDCBaselineConfig() const { return dcBaseline; }

    // Generation
    float generateSample(float deltaTime);
    uint16_t getDACValue12(float deltaTime);    // 12-bit DAC value (MCP4725)

    // Getters
    float getCurrentHeartRate() const { return currentHR; }
    float getCurrentRRInterval() const { return currentRR * 1000.0f; }  // ms
    uint32_t getBeatCount() const { return beatCount; }
    float getPerfusionIndex() const { return currentPI; }
    bool isInSystole() const;
    PPGCondition getCondition() const { return params.condition; }
    const char* getConditionName() const;
    float getNoiseLevel() const { return params.noiseLevel; }
    float getCurrentPI() const { return currentPI; }
    float getAmplification() const { return params.amplification; }
    void setWaveformGain(float gain) { params.amplification = constrain(gain, 0.5f, 2.0f); }
    float getWaveformGain() const { return params.amplification; }
    const PPGParameters& getParameters() const { return params; }

    // Calculated metrics (from model)
    float getACAmplitude() const;       // AC in mV (PI * scale)
    float getDCBaseline() const;        // Current DC in mV
    float getSystoleTime() const;       // Systole duration in ms (model)
    float getDiastoleTime() const;      // Diastole duration in ms (model)
    float getSystoleFraction() const { return systoleFraction; }

    // === Pure AC signal (for TFT waveform display) ===
    float getLastACValue() const { return lastACValue; }

    // === REAL-TIME MEASURED METRICS ===
    // (measured from signal, not from model variables)
    float getMeasuredHR() const;            // HR measured from real RR (BPM)
    float getMeasuredRRInterval() const;    // Measured RR interval (ms)
    float getMeasuredACAmplitude() const;   // Measured AC: peak - valley (mV)
    float getMeasuredPI() const;            // Measured PI: AC/DC × 100 (%)
    float getMeasuredSystoleTime() const;   // Measured systole (ms)
    float getMeasuredDiastoleTime() const;  // Measured diastole (ms)
    float getMeasuredNotchDepth() const;    // Measured notch depth (mV)

    // =========================================================================
    // DIGITAL FILTERING CONTROL
    // =========================================================================
    void setFilteringEnabled(bool enable) { filteringEnabled = enable; }
    bool isFilteringEnabled() const { return filteringEnabled; }
    void setNotchFrequency(float freq);
    void enableHighpassFilter(bool en);
    void enableLowpassFilter(bool en);
    void enableNotchFilter(bool en);
    SignalFilterChain& getFilterChain() { return filterChain; }
};

#endif // PPG_MODEL_H