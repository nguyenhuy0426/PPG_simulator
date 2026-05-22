/**
 * @file digital_filters.cpp
 * @brief Implementación de filtros digitales para señales biomédicas
 * @version 1.0.0
 * @date 09 Enero 2026
 * 
 * COEFICIENTES PRECALCULADOS:
 * Los coeficientes Butterworth se calculan usando la transformación bilineal.
 * Para frecuencias de corte no estándar, se calculan en runtime usando
 * las fórmulas de diseño de filtros IIR.
 * 
 * REFERENCIAS:
 * [1] Oppenheim AV, Schafer RW. "Discrete-Time Signal Processing." 3rd ed.
 * [2] scipy.signal.butter() para verificación de coeficientes
 */

#include "core/digital_filters.h"
#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846f
#endif

// ============================================================================
// DIGITALFILTER - IMPLEMENTACIÓN
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
// NOTCHFILTER - IMPLEMENTACIÓN
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
 * @brief Calcula coeficientes del filtro notch IIR
 * 
 * Diseño: Notch de 2º orden usando transformación bilineal
 * 
 * H(s) = (s² + ω₀²) / (s² + (ω₀/Q)s + ω₀²)
 * 
 * Transformada a dominio Z con prewarp.
 */
void NotchFilter::calculateCoefficients() {
    // Frecuencia normalizada con prewarp
    float omega0 = 2.0f * M_PI * centerFreq / sampleRate;
    float alpha = sinf(omega0) / (2.0f * qFactor);
    
    // Coeficientes del notch
    float b0 = 1.0f;
    float b1 = -2.0f * cosf(omega0);
    float b2 = 1.0f;
    float a0 = 1.0f + alpha;
    float a1 = -2.0f * cosf(omega0);
    float a2 = 1.0f - alpha;
    
    // Normalizar por a0
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
// LOWPASSFILTER - IMPLEMENTACIÓN
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
 * @brief Calcula coeficientes Butterworth paso bajo de 2º orden
 * 
 * Diseño usando transformación bilineal con prewarp:
 * ωa = 2*fs*tan(π*fc/fs)
 * 
 * H(s) = ωa² / (s² + √2*ωa*s + ωa²)  [Butterworth 2º orden]
 */
void LowpassFilter::calculateCoefficients() {
    // Prewarp de la frecuencia de corte
    float wd = 2.0f * M_PI * cutoffFreq / sampleRate;
    float T = 1.0f / sampleRate;
    float wa = (2.0f / T) * tanf(wd * T / 2.0f);
    
    // Coeficientes del prototipo Butterworth normalizado
    // H(s) = 1 / (s² + √2*s + 1) escalado a ωa
    float wa2 = wa * wa;
    float sqrt2_wa = 1.41421356f * wa;  // √2 * ωa
    
    // Transformación bilineal: s = (2/T) * (z-1)/(z+1)
    float K = 2.0f * sampleRate;
    float K2 = K * K;
    
    // Denominador común
    float denom = K2 + sqrt2_wa * K + wa2;
    
    // Coeficientes normalizados
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
// HIGHPASSFILTER - IMPLEMENTACIÓN
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
 * @brief Calcula coeficientes Butterworth paso alto de 2º orden
 * 
 * Se obtiene del paso bajo mediante sustitución: s → ωa²/s
 * 
 * H(s) = s² / (s² + √2*ωa*s + ωa²)
 */
void HighpassFilter::calculateCoefficients() {
    // Prewarp de la frecuencia de corte
    float wd = 2.0f * M_PI * cutoffFreq / sampleRate;
    float T = 1.0f / sampleRate;
    float wa = (2.0f / T) * tanf(wd * T / 2.0f);
    
    // Coeficientes Butterworth paso alto
    float wa2 = wa * wa;
    float sqrt2_wa = 1.41421356f * wa;
    
    float K = 2.0f * sampleRate;
    float K2 = K * K;
    
    // Denominador común
    float denom = K2 + sqrt2_wa * K + wa2;
    
    // Numerador para paso alto: s² → K²*(z-1)²/(z+1)²
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
// BANDPASSFILTER - IMPLEMENTACIÓN
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
 * @brief Calcula coeficientes para pasa-banda (HP + LP en cascada)
 * 
 * Implementación simple: cascada de paso alto y paso bajo.
 * Cada uno es Butterworth 2º orden → total 4º orden.
 */
void BandpassFilter::calculateCoefficients() {
    // Paso alto (elimina frecuencias bajas)
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
    
    // Paso bajo (elimina frecuencias altas)
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
    
    // Cascada: HP primero, luego LP
    float hp_out = biquadHP.process(input);
    return biquadLP.process(hp_out);
}

void BandpassFilter::reset() {
    biquadHP.reset();
    biquadLP.reset();
}

// ============================================================================
// SIGNALFILTERCHAIN - IMPLEMENTACIÓN
// ============================================================================

SignalFilterChain::SignalFilterChain() 
    : signalType(SignalType::ECG), sampleRate(500.0f), filteringEnabled(true) {
    configureForECG();
}

/**
 * @brief Configura la cadena para señales ECG
 * 
 * Configuración basada en Pan-Tompkins (1985):
 * - Paso alto: 0.5 Hz (elimina baseline wander)
 * - Paso bajo: 40 Hz (elimina ruido muscular y HF)
 * - Notch: 50/60 Hz (interferencia de red)
 */
void SignalFilterChain::configureForECG(float fs, float notchFreq) {
    signalType = SignalType::ECG;
    sampleRate = fs;
    
    highpass.configure(ECG_HIGHPASS_FC, fs);
    lowpass.configure(ECG_LOWPASS_FC, fs);
    notch.configure(notchFreq, fs, 30.0f);
    
    // Habilitar todos por defecto
    highpass.setEnabled(true);
    lowpass.setEnabled(true);
    notch.setEnabled(true);
}

/**
 * @brief Configura la cadena para señales PPG
 * 
 * PPG tiene contenido útil en 0.5-8 Hz:
 * - Fundamental: 0.5-3 Hz (HR 30-180 BPM)
 * - Armónicos: hasta 4ª armónica (~8 Hz)
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
 * @brief Configura la cadena para señales EMG
 * 
 * Basado en recomendaciones SENIAM:
 * - Paso alto: 20 Hz (artefactos de movimiento)
 * - Paso bajo: 450 Hz (contenido EMG útil)
 * - Notch: 50/60 Hz (interferencia de red)
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
    // Reconfigurar filtros con nueva frecuencia de muestreo
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
 * @brief Procesa una muestra a través de la cadena completa
 * 
 * Pipeline: Input → Highpass → Lowpass → Notch → Output
 */
float SignalFilterChain::process(float input) {
    if (!filteringEnabled) return input;
    
    float output = input;
    
    // Pipeline de filtrado
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
