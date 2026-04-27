/**
 * @file ppg_model.cpp
 * @brief PPG model implementation - Physiologically correct
 * @version 1.0.0
 * @date December 18, 2025
 * 
 * Physiological model:
 * - ~constant systole (~300ms), variable diastole (compresses with high HR)
 * - dynamic PI as SINGLE AC amplitude control
 * - Normalized waveform [0,1] with soft modifiers per condition
 * - Dynamic HR within pathology range
 * 
 * References:
 * - Allen J (2007): PPG Base Morphology
 * - Sun X et al. (2024): PI beat-to-beat variability
 * - Cardiovascular physiology: ~constant systole, variable diastole 
 */

#include "models/ppg_model.h"
#include "config.h"
#include <math.h>
#include <esp_random.h>

// ============================================================================
//BUILDER
// ============================================================================
PPGModel::PPGModel() {
    hasPendingParams = false;
    reset();
}

// ============================================================================
//RESET - Allen Base Values ​​2007
// ============================================================================
void PPGModel::reset() {
    phaseInCycle = 0.0f;
    beatCount = 0;
    motionNoise = 0.0f;
    baselineWander = 0.0f;
    
    //Reset Gaussian generator
    gaussHasSpare = false;
    gaussSpare = 0.0f;
    
    //Initial values ​​(updated with initConditionRanges)
    currentHR = 75.0f;
    currentPI = 3.0f;
    currentRR = 60.0f / currentHR;  //0.8s at 75BPM
    
    //Default DC baseline (1500 mV so AC = PI × 15 mV)
    //Formula: PI = (AC/DC) × 100% → AC = PI × DC / 100 = PI × 15 mV
    dcBaseline = 1500.0f;
    lastSampleValue = dcBaseline;
    lastACValue = 0.0f;
    
    lastIRValue = dcBaseline;
    lastRedValue = dcBaseline;
    lastAC_IR = 0.0f;
    lastAC_Red = 0.0f;
    respPhase = 0.0f;
    
    //BASE waveform (Allen 2007) - NO in mV, normalized
    systolicAmplitude = PPG_BASE_SYSTOLIC_AMPL;    // 1.0
    systolicWidth = PPG_SYSTOLIC_WIDTH;             // 0.055
    diastolicAmplitude = PPG_BASE_DIASTOLIC_RATIO; // 0.4
    diastolicWidth = PPG_DIASTOLIC_WIDTH;           // 0.10
    dicroticDepth = PPG_BASE_DICROTIC_DEPTH;        // 0.25
    dicroticWidth = PPG_NOTCH_WIDTH;                // 0.02
    
    //Calculate initial phase times
    systoleFraction = calculateSystoleFraction(currentHR);
    systoleTime = currentRR * 1000.0f * systoleFraction;
    diastoleTime = currentRR * 1000.0f * (1.0f - systoleFraction);
    
    //Variables for real-time measurement
    measuredPeakValue = dcBaseline;
    measuredValleyValue = dcBaseline;
    measuredNotchValue = dcBaseline;
    
    //Tracking within the cycle
    currentCyclePeak = 0.0f;
    currentCycleValley = 99999.0f;
    currentCycleNotch = 99999.0f;
    
    //Simulated time
    simulatedTime_ms = 0.0f;
    lastPeakTime_ms = 0.0f;
    lastValleyTime_ms = 0.0f;
    cycleStartTime_ms = 0.0f;
    previousPhase = 0.0f;
    
    //Initial (model) metrics
    measuredRRInterval_ms = currentRR * 1000.0f;
    measuredSystoleTime_ms = systoleTime;
    measuredDiastoleTime_ms = diastoleTime;
    
    //Initialize digital filtering (disabled by default)
    filterChain.configureForPPG(250.0f, 60.0f);  //250Hz, notch 60Hz
    filterChain.reset();
    filteringEnabled = false;  //Disabled - active user if needed
}

// ============================================================================
//INITIALIZATION OF RANGES BY CONDITION
//Values ​​according to clinical table (4 references)
//PI controls AC amplitude; pathology-adjusted Allen base form
// ============================================================================
void PPGModel::initConditionRanges() {
    switch (params.condition) {
        case PPGCondition::NORMAL:
            //PI: 2.9-6.1%, d/s 0.1-0.4
            //Clear systolic peak; fast upstroke; subtle notch
            condRanges = {
                .hrMin = 60.0f, .hrMax = 120.0f, .hrCV = 0.02f,
                .piMin = 2.9f,  .piMax = 6.1f,   .piCV = 0.10f,
                .systolicAmpl = 1.0f,       //Allen Base
                .diastolicAmpl = 0.3f,      //Allen base (d/s 0.4)
                .dicroticDepth = 0.18f      //Subtle notch ≥20%
            };
            break;
            
        case PPGCondition::ARRHYTHMIA:
            //PI: 1.0-5.0%, variable amplitude
            //irregular heartbeat; scattered average template
            condRanges = {
                .hrMin = 60.0f, .hrMax = 180.0f, .hrCV = 0.15f,
                .piMin = 1.0f,  .piMax = 5.0f,   .piCV = 0.20f,
                .systolicAmpl = 1.0f,       //Allen Base
                .diastolicAmpl = 0.4f,      //Allen Base
                .dicroticDepth = 0.20f      //10-30% variable
            };
            break;
            
        case PPGCondition::WEAK_PERFUSION:
            //PI: 0.5-2.1%, peak attenuated
            //Very reduced AC; absent or faint notch
            condRanges = {
                .hrMin = 70.0f, .hrMax = 120.0f, .hrCV = 0.02f,
                .piMin = 0.5f,  .piMax = 2.1f,   .piCV = 0.15f,
                .systolicAmpl = 1.0f,       //Allen Base
                .diastolicAmpl = 0.3f,      //Reduced (peak attenuated)
                .dicroticDepth = 0.05f      //<10%, absent or faint
            };
            break;
            
        case PPGCondition::VASOCONSTRICTION:
            //PI: 0.7-0.8%, flattened pulse
            //Less pronounced upstroke; faint notch
            condRanges = {
                .hrMin = 65.0f, .hrMax = 110.0f, .hrCV = 0.02f,
                .piMin = 0.7f,  .piMax = 0.8f,   .piCV = 0.10f,
                .systolicAmpl = 1.0f,       //Allen Base
                .diastolicAmpl = 0.25f,     //Reduced (flattened pulse)
                .dicroticDepth = 0.05f      //<10%, faint or non-existent
            };
            break;
            
        case PPGCondition::STRONG_PERFUSION:
            //PI: 7.0-20.0%, prominent vascular reflex
            //Robust signal; prominent notch; high AC
            condRanges = {
                .hrMin = 60.0f, .hrMax = 90.0f, .hrCV = 0.02f,
                .piMin = 7.0f,  .piMax = 20.0f, .piCV = 0.10f,
                .systolicAmpl = 1.0f,       //Allen Base
                .diastolicAmpl = 0.5f,      //Increased (prominent vascular reflex)
                .dicroticDepth = 0.25f      //≥30%, prominent
            };
            break;
            
        case PPGCondition::VASODILATION:
            //PI: 5.0-10.0%, better diastolic filling
            //Taller and wider beak; more marked notch
            condRanges = {
                .hrMin = 60.0f, .hrMax = 90.0f, .hrCV = 0.02f,
                .piMin = 5.0f,  .piMax = 10.0f, .piCV = 0.10f,
                .systolicAmpl = 1.0f,       //Allen Base
                .diastolicAmpl = 0.5f,      //Increased (better diastolic filling)
                .dicroticDepth = 0.25f      //20-40%, more marked
            };
            break;
            
        default:
            condRanges = {
                .hrMin = 60.0f, .hrMax = 120.0f, .hrCV = 0.02f,
                .piMin = 2.9f,  .piMax = 6.1f,   .piCV = 0.10f,
                .systolicAmpl = 1.0f,
                .diastolicAmpl = 0.3f,
                .dicroticDepth = 0.18f
            };
    }
}

// ============================================================================
//PARAMETER SETTINGS
// ============================================================================
void PPGModel::setParameters(const PPGParameters& newParams) {
    params = newParams;
    initConditionRanges();
    applyConditionModifiers();
    
    //Generate initial HR within range
    currentHR = generateDynamicHR();
    currentRR = 60.0f / currentHR;
    
    //Generate initial PI within range
    currentPI = generateDynamicPI();
    
    //Calculate phase times
    systoleFraction = calculateSystoleFraction(currentHR);
    systoleTime = currentRR * 1000.0f * systoleFraction;
    diastoleTime = currentRR * 1000.0f * (1.0f - systoleFraction);
    
    //IMPORTANT: Update measured metrics so they are immediately available
    measuredRRInterval_ms = currentRR * 1000.0f;
    measuredSystoleTime_ms = systoleTime;
    measuredDiastoleTime_ms = diastoleTime;
}

void PPGModel::setPendingParameters(const PPGParameters& newParams) {
    pendingParams = newParams;
    hasPendingParams = true;
}

// ============================================================================
//FORM MODIFIERS BY CONDITION
//Allen Base 2007 adjusted according to pathology
//PI controls AC amplitude; shape and notch according to clinical table
// ============================================================================
void PPGModel::applyConditionModifiers() {
    //Amplitudes according to condition (Allen base, adjusted by pathology)
    systolicAmplitude = condRanges.systolicAmpl;
    diastolicAmplitude = condRanges.diastolicAmpl;
    
    //Notch depth according to clinical table
    dicroticDepth = condRanges.dicroticDepth;
    
    //Widths remain constant (Allen 2007)
    systolicWidth = PPG_SYSTOLIC_WIDTH;
    diastolicWidth = PPG_DIASTOLIC_WIDTH;
    dicroticWidth = PPG_NOTCH_WIDTH;
    
    motionNoise = 0.0f;
}

// ============================================================================
//DYNAMIC HR GENERATION
//Choose random value within the pathology range, then vary with CV
// ============================================================================
float PPGModel::generateDynamicHR() {
    //Random mean value within the condition range
    float hrRange = condRanges.hrMax - condRanges.hrMin;
    float hrBase = condRanges.hrMin + (esp_random() / (float)UINT32_MAX) * hrRange;
    
    //Gaussian variability (sigma = mean * CV)
    float sigma = hrBase * condRanges.hrCV;
    float variation = gaussianRandom(0.0f, sigma);
    float dynamicHR = hrBase + variation;
    
    //Clamp to physiological range
    dynamicHR = constrain(dynamicHR, condRanges.hrMin, condRanges.hrMax);
    
    return dynamicHR;
}

// ============================================================================
//DYNAMIC PI GENERATION
//Ref: Sun X et al. (2024) - PI varies beat to beat
//sigma = meanPI * cvPI
// ============================================================================
float PPGModel::generateDynamicPI() {
    //Random mean value within the condition range
    float piRange = condRanges.piMax - condRanges.piMin;
    float piBase = condRanges.piMin + (esp_random() / (float)UINT32_MAX) * piRange;
    
    //Gaussian variability (sigma = mean * CV)
    float sigma = piBase * condRanges.piCV;
    float variation = gaussianRandom(0.0f, sigma);
    float dynamicPI = piBase + variation;
    
    //Clamp to condition range
    dynamicPI = constrain(dynamicPI, condRanges.piMin, condRanges.piMax);
    
    return dynamicPI;
}

// ============================================================================
//SYSTOLIC FRACTION CALCULATION f(HR)
// 
//Physiology: Systole varies little with HR, diastole absorbs the change
//- Low HR (60) → systole ~30% of the cycle (300ms of 1000ms)
//- High HR (120) → systole ~52% of the cycle (260ms of 500ms)
// 
//Simplified linear model based on physiological data:
//systole_ms ≈ 350 - 0.75 * HR (approximation)
// ============================================================================
float PPGModel::calculateSystoleFraction(float hr) {
    //Systolic duration in ms (varies little: ~250-350ms)
    //Model: decreases slightly with HR
    float systole_ms = PPG_SYSTOLE_BASE_MS - 0.5f * (hr - 60.0f);
    systole_ms = constrain(systole_ms, PPG_SYSTOLE_MIN_MS, PPG_SYSTOLE_MAX_MS);
    
    //RR in ms
    float rr_ms = 60000.0f / hr;
    
    //Systolic fraction
    float fraction = systole_ms / rr_ms;
    
    //Limit to reasonable range (cannot be >60% or <20%)
    fraction = constrain(fraction, 0.20f, 0.60f);
    
    return fraction;
}

// ============================================================================
//RR GENERATION WITH VARIABILITY
// ============================================================================
float PPGModel::generateNextRR() {
    //Use HR from params (set by user or by initial condition)
    //DO NOT override with generateDynamicHR() to respect setHeartRate()
    currentHR = params.heartRate;
    
    //RR = 60/HR
    float rrMean = 60.0f / currentHR;
    
    //Additional beat-to-beat variability
    float rrStd = rrMean * condRanges.hrCV;
    
    //For arrhythmia: occasional ectopic beats
    if (params.condition == PPGCondition::ARRHYTHMIA) {
        if (esp_random() % 100 < 15) {
            rrMean *= 0.7f;  //Premature heartbeat
        }
    }
    
    // FM (Frequency Modulation) / Respiratory Sinus Arrhythmia (RSA)
    // Breathing affects the RR interval. Faster HR during inspiration, slower during expiration.
    float rsaModulation = 0.05f * sinf(respPhase); // +/- 5% RR modulation
    rrMean *= (1.0f + rsaModulation);
    
    float rr = rrMean + gaussianRandom(0.0f, rrStd);
    rr = constrain(rr, 0.3f, 2.0f);  //30-200BPM
    
    //Update phase times
    systoleFraction = calculateSystoleFraction(currentHR);
    systoleTime = rr * 1000.0f * systoleFraction;
    diastoleTime = rr * 1000.0f * (1.0f - systoleFraction);
    
    return rr;
}

// ============================================================================
//PULSE SHAPE - DOUBLE GAUSSIAN MODEL (Allen 2007)
//Returns NORMALIZED form [0, 1]
// ============================================================================
float PPGModel::computePulseShape(float phase) {
    //Normalize phase to 0-1
    phase = fmodf(phase, 1.0f);
    if (phase < 0) phase += 1.0f;
    
    //Systolic peak (main Gaussian)
    float systolic = systolicAmplitude * 
        expf(-powf(phase - PPG_SYSTOLIC_POS, 2) / (2.0f * powf(systolicWidth, 2)));
    
    //Diastolic peak (wave reflection)
    float diastolic = diastolicAmplitude * 
        expf(-powf(phase - PPG_DIASTOLIC_POS, 2) / (2.0f * powf(diastolicWidth, 2)));
    
    //Dicrotic notch (aortic valve closure)
    float notch = dicroticDepth * systolicAmplitude * 
        expf(-powf(phase - PPG_NOTCH_POS, 2) / (2.0f * powf(dicroticWidth, 2)));
    
    //Composite signal
    float pulse = systolic + diastolic - notch;
    
    //NORMALIZE to [0, 1]
    pulse = normalizePulse(pulse);
    
    return pulse;
}

// ============================================================================
//PULSE NORMALIZATION TO [0, 1]
// ============================================================================
float PPGModel::normalizePulse(float rawPulse) {
    //Approximate theoretical range of raw pulse
    //With systolic=1.0, diastolic=0.4, notch=0.25 → max ~1.15, min ~0
    const float PULSE_MIN = 0.0f;
    const float PULSE_MAX = 1.4f;  //Margin for modifiers
    
    float normalized = (rawPulse - PULSE_MIN) / (PULSE_MAX - PULSE_MIN);
    normalized = constrain(normalized, 0.0f, 1.0f);
    
    return normalized;
}

// ============================================================================
//HEARTBEAT DETECTION AND APPLICATION OF PENDING PARAMETERS
// ============================================================================
void PPGModel::detectBeatAndApplyPending() {
    beatCount++;
    
    //Apply pending parameters
    if (hasPendingParams) {
        setParameters(pendingParams);
        hasPendingParams = false;
    }
    
    //Generate new RR (includes dynamic HR update)
    currentRR = generateNextRR();
    
    //Update dynamic PI
    currentPI = generateDynamicPI();
    
    //Update measured metrics based on the model (for immediate display)
    //This ensures that RR and other metrics are available from the first heartbeat
    measuredRRInterval_ms = currentRR * 1000.0f;
}

// ============================================================================
//SAMPLE GENERATION
//Flow: pulseShape[0,1] → AC = PI * scale → signal = DC + pulse * AC
// ============================================================================
float PPGModel::generateSample(float deltaTime) {
    //Advance phase within the cardiac cycle
    phaseInCycle += deltaTime / currentRR;
    
    //New heartbeat upon completion of cycle
    if (phaseInCycle >= 1.0f) {
        phaseInCycle = fmodf(phaseInCycle, 1.0f);
        detectBeatAndApplyPending();
    }
    
    //1. Calculate NORMALIZED pulse shape [0, 1]
    float pulse = computePulseShape(phaseInCycle);
    
    //2. Calculate AC amplitude based ONLY on dynamic PI
    //AC = PI * AC_SCALE_PER_PI (mV)
    float acAmplitude = currentPI * PPG_AC_SCALE_PER_PI;
    
    //3. Pure AC Component (for Nextion Waveform)
    float acValue = pulse * acAmplitude;
    
    //4. End signal: DC + AC
    float signal_mv = dcBaseline + acValue;
    
    //5. Baseline wander (~0.05 Hz)
    baselineWander = fmodf(baselineWander + deltaTime * 0.3f, 2.0f * PI);
    float wanderAmplitude = (dcBaseline > 0) ? 0.002f * dcBaseline : 2.0f;
    signal_mv += wanderAmplitude * sinf(baselineWander);
    
    //6. Gaussian noise proportional to AC
    //noiseLevel is in range 0.0-0.10 (0-10%)
    //Noise proportional to AC amplitude of the signal
    //10% noise = acAmplitude * 0.1 sigma → visible variation
    float noiseAmplitude = params.noiseLevel * acAmplitude;
    signal_mv += gaussianRandom(0.0f, noiseAmplitude);
    
    //Avoid negative values ​​if DC > 0
    if (dcBaseline > 0) {
        signal_mv = fmaxf(signal_mv, 0.0f);
    }
    
    //=== PHASE BASED REAL-TIME MEASUREMENT ===
    //Use simulated time, not micros()
    float deltaTime_ms = deltaTime * 1000.0f;
    simulatedTime_ms += deltaTime_ms;
    
    //Track maximum (peak) in systolic zone (phase 0.10-0.25)
    if (phaseInCycle >= 0.10f && phaseInCycle <= 0.25f) {
        if (signal_mv > currentCyclePeak) {
            currentCyclePeak = signal_mv;
        }
    }
    
    //Track minimum (valley) at the beginning of the cycle (phase 0-0.08)
    if (phaseInCycle <= 0.08f) {
        if (signal_mv < currentCycleValley) {
            currentCycleValley = signal_mv;
        }
    }
    
    //Track dicrotic notch (phase 0.28-0.35)
    if (phaseInCycle >= 0.28f && phaseInCycle <= 0.35f) {
        if (signal_mv < currentCycleNotch) {
            currentCycleNotch = signal_mv;
        }
    }
    
    //Detect end of systole (phase transition > 0.25 from < 0.25)
    if (previousPhase <= 0.25f && phaseInCycle > 0.25f) {
        //Save measured peak
        if (currentCyclePeak > 0.0f) {
            measuredPeakValue = currentCyclePeak;
            
            //Calculate systolic time (from cycle start to peak)
            float peakTime = cycleStartTime_ms + (currentRR * 1000.0f * PPG_SYSTOLIC_POS);
            if (lastValleyTime_ms > 0.0f) {
                measuredSystoleTime_ms = peakTime - lastValleyTime_ms;
            }
            lastPeakTime_ms = peakTime;
        }
    }
    
    //Detect new cycle (wrap-around phase or very low phase after high)
    if (phaseInCycle < previousPhase && previousPhase > 0.5f) {
        //End of previous cycle - save metrics
        if (currentCycleValley < 99999.0f) {
            measuredValleyValue = currentCycleValley;
        }
        if (currentCycleNotch < 99999.0f) {
            measuredNotchValue = currentCycleNotch;
        }
        
        //Calculate RR (time between cycle starts)
        if (cycleStartTime_ms > 0.0f) {
            measuredRRInterval_ms = simulatedTime_ms - cycleStartTime_ms;
        }
        
        //Calculate diastole (from peak to end of cycle)
        if (lastPeakTime_ms > 0.0f && cycleStartTime_ms > 0.0f) {
            measuredDiastoleTime_ms = simulatedTime_ms - lastPeakTime_ms;
        }
        
        //New cycle - reset tracking
        lastValleyTime_ms = simulatedTime_ms;
        cycleStartTime_ms = simulatedTime_ms;
        currentCyclePeak = 0.0f;
        currentCycleValley = 99999.0f;
        currentCycleNotch = 99999.0f;
    }
    
    previousPhase = phaseInCycle;
    
    lastSampleValue = signal_mv;
    lastACValue = acValue;  //Save pure AC component
    
    return signal_mv;
}

// ============================================================================
// DUAL CHANNEL SAMPLE GENERATION
// ============================================================================
void PPGModel::generateBothSamples(float deltaTime, float &outIR, float &outRed) {
    // Advance phase within the cardiac cycle
    phaseInCycle += deltaTime / currentRR;
    
    if (phaseInCycle >= 1.0f) {
        phaseInCycle = fmodf(phaseInCycle, 1.0f);
        detectBeatAndApplyPending();
    }
    
    // Calculate normalized pulse shape [0, 1]
    float pulse = computePulseShape(phaseInCycle);
    
    // SpO2 -> R -> AC_red
    float rValue = (110.0f - params.spO2) / 25.0f;
    float acAmplitudeIR = currentPI * PPG_AC_SCALE_PER_PI;
    float acAmplitudeRed = acAmplitudeIR * rValue;
    
    float acValueIR = pulse * acAmplitudeIR;
    float acValueRed = pulse * acAmplitudeRed;
    
    lastAC_IR = acValueIR;
    lastAC_Red = acValueRed;
    
    // Respiratory modulations (AM and Baseline Wander)
    respPhase += deltaTime * (2.0f * PI * params.respRate / 60.0f);
    respPhase = fmodf(respPhase, 2.0f * PI);
    
    // RIIV (baseline wander)
    baselineWander = fmodf(baselineWander + deltaTime * 0.3f, 2.0f * PI);
    float wanderAmplitude = (dcBaseline > 0) ? 0.002f * dcBaseline : 2.0f;
    float wander = wanderAmplitude * sinf(baselineWander) + 15.0f * sinf(respPhase); // added resp wander
    
    // RIAV (amplitude modulation)
    float amFactor = 1.0f + 0.25f * sinf(respPhase); // 25% modulation
    
    acValueIR *= amFactor;
    acValueRed *= amFactor;
    
    // Track for display (AC + Wander, without massive DC baseline)
    lastDisplay_IR = acValueIR + wander;
    
    float signalIR = dcBaseline + acValueIR + wander;
    float signalRed = dcBaseline + acValueRed + wander;
    
    float noiseAmplitudeIR = params.noiseLevel * acAmplitudeIR;
    float noiseAmplitudeRed = params.noiseLevel * acAmplitudeRed;
    
    signalIR += gaussianRandom(0.0f, noiseAmplitudeIR);
    signalRed += gaussianRandom(0.0f, noiseAmplitudeRed);
    
    if (dcBaseline > 0) {
        signalIR = fmaxf(signalIR, 0.0f);
        signalRed = fmaxf(signalRed, 0.0f);
    }
    
    // Sync with legacy measurement logic
    float deltaTime_ms = deltaTime * 1000.0f;
    simulatedTime_ms += deltaTime_ms;
    
    if (phaseInCycle >= 0.10f && phaseInCycle <= 0.25f) {
        if (signalIR > currentCyclePeak) currentCyclePeak = signalIR;
    }
    if (phaseInCycle <= 0.08f) {
        if (signalIR < currentCycleValley) currentCycleValley = signalIR;
    }
    if (phaseInCycle >= 0.28f && phaseInCycle <= 0.35f) {
        if (signalIR < currentCycleNotch) currentCycleNotch = signalIR;
    }
    if (previousPhase <= 0.25f && phaseInCycle > 0.25f) {
        if (currentCyclePeak > 0.0f) {
            measuredPeakValue = currentCyclePeak;
            float peakTime = cycleStartTime_ms + (currentRR * 1000.0f * PPG_SYSTOLIC_POS);
            if (lastValleyTime_ms > 0.0f) measuredSystoleTime_ms = peakTime - lastValleyTime_ms;
            lastPeakTime_ms = peakTime;
        }
    }
    if (phaseInCycle < previousPhase && previousPhase > 0.5f) {
        if (currentCycleValley < 99999.0f) measuredValleyValue = currentCycleValley;
        if (currentCycleNotch < 99999.0f) measuredNotchValue = currentCycleNotch;
        if (cycleStartTime_ms > 0.0f) measuredRRInterval_ms = simulatedTime_ms - cycleStartTime_ms;
        if (lastPeakTime_ms > 0.0f && cycleStartTime_ms > 0.0f) measuredDiastoleTime_ms = simulatedTime_ms - lastPeakTime_ms;
        lastValleyTime_ms = simulatedTime_ms;
        cycleStartTime_ms = simulatedTime_ms;
        currentCyclePeak = 0.0f;
        currentCycleValley = 99999.0f;
        currentCycleNotch = 99999.0f;
    }
    
    previousPhase = phaseInCycle;
    lastIRValue = signalIR;
    lastRedValue = signalRed;
    
    outIR = signalIR;
    outRed = signalRed;
}

// ============================================================================
//CONVERSION TO DAC
// ============================================================================
//NOTE: The DAC output only contains the AC component of the PPG signal.
//Rationale: The DC component (baseline ~1000 mV) represents the absorption
//constant light and does not provide diagnostic information. The clinical utility
//of the PPG signal resides in the pulsatile component (AC), which reflects:
//- Pulsatile blood volume (waveform)
//- Perfusion index (PI = AC/DC × 100%)
//- Heart rate variability
//By sending only AC to the DAC, the signal is directly comparable to the
//TFT display and facilitates connection to external equipment.
// ============================================================================
uint16_t PPGModel::getDACValue12(float deltaTime) {
    // Generate full sample (updates lastACValue internally)
    generateSample(deltaTime);
    
    // Convert only AC component to 12-bit DAC value
    return acValueToDACValue12(lastACValue);
}

uint16_t PPGModel::voltageToDACValue12(float voltage) {
    // Maps full signal DC+AC to 12-bit DAC range
    float rangeMin = dcBaseline - 200.0f;
    float rangeMax = dcBaseline + 200.0f;
    
    if (dcBaseline == 0.0f) {
        rangeMin = -100.0f;
        rangeMax = 100.0f;
    }
    
    float normalized = (voltage - rangeMin) / (rangeMax - rangeMin);
    normalized = constrain(normalized, 0.0f, 1.0f);
    return (uint16_t)(normalized * 4095.0f);
}

uint16_t PPGModel::acValueToDACValue12(float acValue_mV) {
    // Pure AC component mapping to 12-bit DAC (MCP4725)
    // Formula: PI = (AC / DC) × 100% → AC = PI × DC / 100
    // With DC = 1500 mV: AC = PI × 15 mV
    // PPG AC signal is UNIPOLAR: ranges from 0 (valley) to ~150 mV (systolic peak)
    // where AC_max = PI_max × 15 mV/% ≈ 10% × 15 = 150 mV
    //
    // Scaling for MCP4725 12-bit output:
    // 0 mV   → DAC 0    → 0.0V
    // 150 mV → DAC 4095 → 3.3V
    const float AC_MAX_MV = 150.0f;  // Maximum AC (PI~10%)
    
    float normalized = acValue_mV / AC_MAX_MV;
    normalized = constrain(normalized, 0.0f, 1.0f);
    return (uint16_t)(normalized * 4095.0f);
}

// ============================================================================
//MEASURABLE METRICS
// ============================================================================

float PPGModel::getACAmplitude() const {
    //AC = PI * scale (mV)
    return currentPI * PPG_AC_SCALE_PER_PI;
}

float PPGModel::getDCBaseline() const {
    return dcBaseline;
}

float PPGModel::getSystoleTime() const {
    return systoleTime;
}

float PPGModel::getDiastoleTime() const {
    return diastoleTime;
}

// ============================================================================
//HELPERS
// ============================================================================

float PPGModel::gaussianRandom(float mean, float std) {
    if (gaussHasSpare) {
        gaussHasSpare = false;
        return mean + std * gaussSpare;
    }
    
    float u, v, s;
    do {
        u = (esp_random() / (float)UINT32_MAX) * 2.0f - 1.0f;
        v = (esp_random() / (float)UINT32_MAX) * 2.0f - 1.0f;
        s = u * u + v * v;
    } while (s >= 1.0f || s == 0.0f);
    
    s = sqrtf(-2.0f * logf(s) / s);
    gaussSpare = v * s;
    gaussHasSpare = true;
    
    return mean + std * u * s;
}

bool PPGModel::isInSystole() const {
    return (phaseInCycle < systoleFraction);
}

const char* PPGModel::getConditionName() const {
    switch (params.condition) {
        case PPGCondition::NORMAL: return "Normal";
        case PPGCondition::ARRHYTHMIA: return "Arritmia";
        case PPGCondition::WEAK_PERFUSION: return "Weak Perfusion";
        case PPGCondition::VASOCONSTRICTION: return "Vasoconstriccion";
        case PPGCondition::STRONG_PERFUSION: return "Strong Perfusion";
        case PPGCondition::VASODILATION: return "Vasodilatacion";
        default: return "Desconocido";
    }
}

// ============================================================================
//PURE AC SIGNAL FOR NEXTION WAVEFORM
//Scale the UNIPOLAR AC component to the range 26-255 (floor at 10%)
// ============================================================================
// getWaveformValue() removed — TFT display driver handles its own scaling
// using getLastACValue() directly

// ============================================================================
//METRICS MEASURED IN REAL TIME
//Values ​​obtained from the signal, not from the model variables
// ============================================================================

float PPGModel::getMeasuredHR() const {
    //HR = 60000 / RR_ms
    if (measuredRRInterval_ms > 0) {
        return 60000.0f / measuredRRInterval_ms;
    }
    return currentHR;  //Fallback to model value
}

float PPGModel::getMeasuredRRInterval() const {
    return measuredRRInterval_ms;
}

float PPGModel::getMeasuredACAmplitude() const {
    //AC = peak - valley (mV)
    return measuredPeakValue - measuredValleyValue;
}

float PPGModel::getMeasuredPI() const {
    //PI = (AC/DC) × 100%
    if (dcBaseline > 0) {
        float ac = getMeasuredACAmplitude();
        return (ac / dcBaseline) * 100.0f;
    }
    return currentPI;  //Fallback
}

float PPGModel::getMeasuredSystoleTime() const {
    return measuredSystoleTime_ms;
}

float PPGModel::getMeasuredDiastoleTime() const {
    return measuredDiastoleTime_ms;
}

float PPGModel::getMeasuredNotchDepth() const {
    //Depth = systolic peak - notch trough (mV)
    return measuredPeakValue - measuredNotchValue;
}

// ============================================================================
//DIGITAL FILTERING CONTROL
// ============================================================================

void PPGModel::setNotchFrequency(float freq) {
    filterChain.setNotchFreq(freq, 30.0f);
}

void PPGModel::enableHighpassFilter(bool en) {
    filterChain.enableHighpass(en);
}

void PPGModel::enableLowpassFilter(bool en) {
    filterChain.enableLowpass(en);
}

void PPGModel::enableNotchFilter(bool en) {
    filterChain.enableNotch(en);
}
