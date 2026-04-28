/**
 * @file digital_filters.cpp
 * @brief Implementation of digital filters for biomedical signals
 * @version 1.0.0
 * @date 09 January 2026
 * 
 * PRE-CALCULATED COEFFICIENTS:
 * Butterworth coefficients are calculated using the bilinear transformation.
 * For non-standard cutoff frequencies, they are calculated in runtime using
 * the IIR filter design formulas.
 * 
 * REFERENCES:
 * [1] Oppenheim AV, Schafer RW. "Discrete-Time Signal Processing." 3rd ed.
 * [2] scipy.signal.butter() for coefficient checking 
 */

#include "core/digital_filters.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif

// ============================================================================
//DIGITALFILTER - IMPLEMENTATION
// ============================================================================

DigitalFilter::DigitalFilter() : numSections(1), enabled(true) {
    for (int i = 0; i < MAX_SECTIONS; i++) {
        sections[i] = BiquadSection();
    }
}

void DigitalFilter::setCoefficients(int section, float b0, float b1, float b2, float a1, float a2) {
    if (section >= 0 && section < MAX_SECTIONS) {
        sections[section].b0 = b0;
        sections[section].b1 = b1;
        sections[section].b2 = b2;
        sections[section].a1 = a1;
        sections[section].a2 = a2;
    }
}

void DigitalFilter::setNumSections(int n) {
    if (n > 0 && n <= MAX_SECTIONS) {
        numSections = n;
    }
}

float DigitalFilter::process(float input) {
    if (!enabled) return input;
    
    float output = input;
    for (int i = 0; i < numSections; i++) {
        output = sections[i].process(output);
    }
    return output;
}

void DigitalFilter::reset() {
    for (int i = 0; i < MAX_SECTIONS; i++) {
        sections[i].reset();
    }
}

// ============================================================================
//NOTCHFILTER - IMPLEMENTATION
// ============================================================================

NotchFilter::NotchFilter() 
    : centerFreq(60.0f), sampleRate(500.0f), qFactor(30.0f), enabled(true) {
    calculateCoefficients();
}

void NotchFilter::configure(float fc, float fs, float Q) {
    centerFreq = fc;
    sampleRate = fs;
    qFactor = Q;
    calculateCoefficients();
}

/**
 * @brief Calculates IIR notch filter coefficients
 * 
 * Design: 2nd order notch using bilinear transformation
 * 
 * H(s) = (s² + ω₀²) / (s² + (ω₀/Q)s + ω₀²)
 * 
 * Transformed to Z domain with prewarp. 
 */
void NotchFilter::calculateCoefficients() {
    //Normalized frequency with prewarp
    float omega0 = 2.0f * M_PI * centerFreq / sampleRate;
    float alpha = sinf(omega0) / (2.0f * qFactor);
    
    //Notch coefficients
    float b0 = 1.0f;
    float b1 = -2.0f * cosf(omega0);
    float b2 = 1.0f;
    float a0 = 1.0f + alpha;
    float a1 = -2.0f * cosf(omega0);
    float a2 = 1.0f - alpha;
    
    //Normalize by a0
    biquad.b0 = b0 / a0;
    biquad.b1 = b1 / a0;
    biquad.b2 = b2 / a0;
    biquad.a1 = a1 / a0;
    biquad.a2 = a2 / a0;
}

float NotchFilter::process(float input) {
    if (!enabled) return input;
    return biquad.process(input);
}

void NotchFilter::reset() {
    biquad.reset();
}

// ============================================================================
//LOWPASSFILTER - IMPLEMENTATION
// ============================================================================

LowpassFilter::LowpassFilter() 
    : cutoffFreq(40.0f), sampleRate(500.0f), enabled(true) {
    calculateCoefficients();
}

void LowpassFilter::configure(float fc, float fs) {
    cutoffFreq = fc;
    sampleRate = fs;
    calculateCoefficients();
}

/**
 * @brief Calculates 2nd order low pass Butterworth coefficients
 * 
 * Design using bilinear transformation with prewarp:
 * ωa = 2*fs*tan(π*fc/fs)
 * 
 * H(s) = ωa² / (s² + √2*ωa*s + ωa²) [Butterworth 2nd order] 
 */
void LowpassFilter::calculateCoefficients() {
    //Cutoff frequency prewarp
    float wd = 2.0f * M_PI * cutoffFreq / sampleRate;
    float T = 1.0f / sampleRate;
    float wa = (2.0f / T) * tanf(wd * T / 2.0f);
    
    //Normalized Butterworth prototype coefficients
    //H(s) = 1 / (s² + √2*s + 1) scaled to ωa
    float wa2 = wa * wa;
    float sqrt2_wa = 1.41421356f * wa;  //√2 * ωa
    
    //Bilinear transformation: s = (2/T) * (z-1)/(z+1)
    float K = 2.0f * sampleRate;
    float K2 = K * K;
    
    //Common denominator
    float denom = K2 + sqrt2_wa * K + wa2;
    
    //Normalized coefficients
    biquad.b0 = wa2 / denom;
    biquad.b1 = 2.0f * wa2 / denom;
    biquad.b2 = wa2 / denom;
    biquad.a1 = (2.0f * wa2 - 2.0f * K2) / denom;
    biquad.a2 = (K2 - sqrt2_wa * K + wa2) / denom;
}

float LowpassFilter::process(float input) {
    if (!enabled) return input;
    return biquad.process(input);
}

void LowpassFilter::reset() {
    biquad.reset();
}

// ============================================================================
//HIGHPASSFILTER - IMPLEMENTATION
// ============================================================================

HighpassFilter::HighpassFilter() 
    : cutoffFreq(0.5f), sampleRate(500.0f), enabled(true) {
    calculateCoefficients();
}

void HighpassFilter::configure(float fc, float fs) {
    cutoffFreq = fc;
    sampleRate = fs;
    calculateCoefficients();
}

/**
 * @brief Calculates 2nd order high pass Butterworth coefficients
 * 
 * Obtained from the low pass by substitution: s → ωa²/s
 * 
 * H(s) = s² / (s² + √2*ωa*s + ωa²) 
 */
void HighpassFilter::calculateCoefficients() {
    //Cutoff frequency prewarp
    float wd = 2.0f * M_PI * cutoffFreq / sampleRate;
    float T = 1.0f / sampleRate;
    float wa = (2.0f / T) * tanf(wd * T / 2.0f);
    
    //High-pass Butterworth coefficients
    float wa2 = wa * wa;
    float sqrt2_wa = 1.41421356f * wa;
    
    float K = 2.0f * sampleRate;
    float K2 = K * K;
    
    //Common denominator
    float denom = K2 + sqrt2_wa * K + wa2;
    
    //Numerator for high pass: s² → K²*(z-1)²/(z+1)²
    biquad.b0 = K2 / denom;
    biquad.b1 = -2.0f * K2 / denom;
    biquad.b2 = K2 / denom;
    biquad.a1 = (2.0f * wa2 - 2.0f * K2) / denom;
    biquad.a2 = (K2 - sqrt2_wa * K + wa2) / denom;
}

float HighpassFilter::process(float input) {
    if (!enabled) return input;
    return biquad.process(input);
}

void HighpassFilter::reset() {
    biquad.reset();
}

// ============================================================================
//BANDPASSFILTER - IMPLEMENTATION
// ============================================================================

BandpassFilter::BandpassFilter() 
    : lowCutoff(0.5f), highCutoff(40.0f), sampleRate(500.0f), enabled(true) {
    calculateCoefficients();
}

void BandpassFilter::configure(float fcLow, float fcHigh, float fs) {
    lowCutoff = fcLow;
    highCutoff = fcHigh;
    sampleRate = fs;
    calculateCoefficients();
}

/**
 * @brief Calculates coefficients for band-pass (HP + LP in cascade)
 * 
 * Simple implementation: high-pass and low-pass cascade.
 * Each one is Butterworth 2nd order → total 4th order. 
 */
void BandpassFilter::calculateCoefficients() {
    //High Pass (removes low frequencies)
    float wdHP = 2.0f * M_PI * lowCutoff / sampleRate;
    float T = 1.0f / sampleRate;
    float waHP = (2.0f / T) * tanf(wdHP * T / 2.0f);
    
    float waHP2 = waHP * waHP;
    float sqrt2_waHP = 1.41421356f * waHP;
    float K = 2.0f * sampleRate;
    float K2 = K * K;
    
    float denomHP = K2 + sqrt2_waHP * K + waHP2;
    
    biquadHP.b0 = K2 / denomHP;
    biquadHP.b1 = -2.0f * K2 / denomHP;
    biquadHP.b2 = K2 / denomHP;
    biquadHP.a1 = (2.0f * waHP2 - 2.0f * K2) / denomHP;
    biquadHP.a2 = (K2 - sqrt2_waHP * K + waHP2) / denomHP;
    
    //Low pass (removes high frequencies)
    float wdLP = 2.0f * M_PI * highCutoff / sampleRate;
    float waLP = (2.0f / T) * tanf(wdLP * T / 2.0f);
    
    float waLP2 = waLP * waLP;
    float sqrt2_waLP = 1.41421356f * waLP;
    
    float denomLP = K2 + sqrt2_waLP * K + waLP2;
    
    biquadLP.b0 = waLP2 / denomLP;
    biquadLP.b1 = 2.0f * waLP2 / denomLP;
    biquadLP.b2 = waLP2 / denomLP;
    biquadLP.a1 = (2.0f * waLP2 - 2.0f * K2) / denomLP;
    biquadLP.a2 = (K2 - sqrt2_waLP * K + waLP2) / denomLP;
}

float BandpassFilter::process(float input) {
    if (!enabled) return input;
    
    //Cascade: HP first, then LP
    float hp_out = biquadHP.process(input);
    return biquadLP.process(hp_out);
}

void BandpassFilter::reset() {
    biquadHP.reset();
    biquadLP.reset();
}

// ============================================================================
//SIGNALFILTERCHAIN ​​- IMPLEMENTATION
// ============================================================================

SignalFilterChain::SignalFilterChain() 
    : signalType(SignalType::ECG), sampleRate(500.0f), filteringEnabled(true) {
    configureForECG();
}

/**
 * @brief Configures the chain for ECG signals
 * 
 * Configuration based on Pan-Tompkins (1985):
 * - High pass: 0.5 Hz (removes baseline wander)
 * - Low pass: 40 Hz (removes muscle and HF noise)
 * - Notch: 50/60 Hz (network interference) 
 */
void SignalFilterChain::configureForECG(float fs, float notchFreq) {
    signalType = SignalType::ECG;
    sampleRate = fs;
    
    highpass.configure(ECG_HIGHPASS_FC, fs);
    lowpass.configure(ECG_LOWPASS_FC, fs);
    notch.configure(notchFreq, fs, 30.0f);
    
    //Enable all by default
    highpass.setEnabled(true);
    lowpass.setEnabled(true);
    notch.setEnabled(true);
}

/**
 * @brief Configures the chain for PPG signals
 * 
 * PPG has useful content in 0.5-8 Hz:
 * - Fundamental: 0.5-3 Hz (HR 30-180 BPM)
 * - Harmonics: up to 4th harmonic (~8 Hz) 
 */
void SignalFilterChain::configureForPPG(float fs, float notchFreq) {
    signalType = SignalType::PPG;
    sampleRate = fs;
    
    highpass.configure(PPG_HIGHPASS_FC, fs);
    lowpass.configure(PPG_LOWPASS_FC, fs);
    notch.configure(notchFreq, fs, 30.0f);
    
    highpass.setEnabled(true);
    lowpass.setEnabled(true);
    notch.setEnabled(true);
}

/**
 * @brief Configures the chain for EMG signals
 * 
 * Based on SENIAM recommendations:
 * - High Pass: 20 Hz (motion artifacts)
 * - Low Pass: 450 Hz (useful EMG content)
 * - Notch: 50/60 Hz (network interference) 
 */
void SignalFilterChain::configureForEMG(float fs, float notchFreq) {
    signalType = SignalType::EMG;
    sampleRate = fs;
    
    highpass.configure(EMG_HIGHPASS_FC, fs);
    lowpass.configure(EMG_LOWPASS_FC, fs);
    notch.configure(notchFreq, fs, 30.0f);
    
    highpass.setEnabled(true);
    lowpass.setEnabled(true);
    notch.setEnabled(true);
}

void SignalFilterChain::setHighpassCutoff(float fc) {
    highpass.configure(fc, sampleRate);
}

void SignalFilterChain::setLowpassCutoff(float fc) {
    lowpass.configure(fc, sampleRate);
}

void SignalFilterChain::setNotchFreq(float fc, float Q) {
    notch.configure(fc, sampleRate, Q);
}

void SignalFilterChain::setSampleRate(float fs) {
    sampleRate = fs;
    //Reconfigure filters with new sample rate
    highpass.configure(highpass.getCutoffFreq(), fs);
    lowpass.configure(lowpass.getCutoffFreq(), fs);
    notch.configure(notch.getCenterFreq(), fs, notch.getQFactor());
}

void SignalFilterChain::enableHighpass(bool en) {
    highpass.setEnabled(en);
}

void SignalFilterChain::enableLowpass(bool en) {
    lowpass.setEnabled(en);
}

void SignalFilterChain::enableNotch(bool en) {
    notch.setEnabled(en);
}

void SignalFilterChain::enableAll(bool en) {
    highpass.setEnabled(en);
    lowpass.setEnabled(en);
    notch.setEnabled(en);
}

/**
 * @brief Processes a sample through the entire chain
 * 
 * Pipeline: Input → Highpass → Lowpass → Notch → Output 
 */
float SignalFilterChain::process(float input) {
    if (!filteringEnabled) return input;
    
    float output = input;
    
    //Filtering Pipeline
    output = highpass.process(output);
    output = lowpass.process(output);
    output = notch.process(output);
    
    return output;
}

void SignalFilterChain::reset() {
    highpass.reset();
    lowpass.reset();
    notch.reset();
}
