/**
 * @file digital_filters.h
 * @brief Módulo de filtrado digital para señales biomédicas (ECG, PPG, EMG)
 * @version 1.0.0
 * @date 09 Enero 2026
 * 
 * FILTROS IMPLEMENTADOS:
 * - Butterworth paso bajo (2º orden)
 * - Butterworth paso alto (2º orden)
 * - Butterworth pasa-banda (4º orden = 2 biquads cascada)
 * - Notch 50/60 Hz (elimina interferencia de red eléctrica)
 * 
 * REFERENCIAS:
 * [1] Tompkins WJ. "Biomedical Digital Signal Processing." Prentice Hall, 1993.
 * [2] Pan J, Tompkins WJ. "A Real-Time QRS Detection Algorithm."
 *     IEEE Trans Biomed Eng. 1985;32(3):230-236.
 * [3] SENIAM recommendations for sEMG filtering.
 * 
 * IMPLEMENTACIÓN:
 * - Estructura biquad IIR Direct Form II Transposed (estabilidad numérica)
 * - Coeficientes precalculados para frecuencias de muestreo comunes
 * - Optimizado para ESP32 (punto flotante de precisión simple)
 */

#ifndef DIGITAL_FILTERS_H
#define DIGITAL_FILTERS_H

#include <Arduino.h>

// ============================================================================
// CONSTANTES DE FILTRADO
// ============================================================================

// Frecuencias de muestreo soportadas
#define FILTER_FS_500    500.0f    // Hz - ECG típico
#define FILTER_FS_1000   1000.0f   // Hz - EMG típico
#define FILTER_FS_250    250.0f    // Hz - PPG típico

// Frecuencias de corte estándar para señales biomédicas
#define ECG_HIGHPASS_FC  0.5f      // Hz - elimina baseline wander
#define ECG_LOWPASS_FC   40.0f     // Hz - elimina ruido muscular/HF
#define ECG_NOTCH_FC     60.0f     // Hz - interferencia de red (USA)

#define PPG_HIGHPASS_FC  0.5f      // Hz - elimina DC drift
#define PPG_LOWPASS_FC   8.0f      // Hz - señal PPG (hasta 4ª armónica)

#define EMG_HIGHPASS_FC  20.0f     // Hz - elimina artefactos movimiento
#define EMG_LOWPASS_FC   450.0f    // Hz - contenido EMG útil

// ============================================================================
// ESTRUCTURA BIQUAD (Second-Order Section)
// ============================================================================
/**
 * @brief Estructura para una sección biquad IIR
 * 
 * Función de transferencia:
 *   H(z) = (b0 + b1*z^-1 + b2*z^-2) / (1 + a1*z^-1 + a2*z^-2)
 * 
 * Direct Form II Transposed para mejor estabilidad numérica.
 */
struct BiquadSection {
    // Coeficientes (normalizados, a0 = 1)
    float b0, b1, b2;   // Numerador
    float a1, a2;       // Denominador (sin a0)
    
    // Estados internos
    float w1, w2;       // Memoria del filtro
    
    // Constructor por defecto
    BiquadSection() : b0(1), b1(0), b2(0), a1(0), a2(0), w1(0), w2(0) {}
    
    // Reset estados
    void reset() {
        w1 = 0.0f;
        w2 = 0.0f;
    }
    
    // Procesar una muestra
    float process(float input) {
        float output = b0 * input + w1;
        w1 = b1 * input - a1 * output + w2;
        w2 = b2 * input - a2 * output;
        return output;
    }
};

// ============================================================================
// CLASE DigitalFilter - FILTRO BIQUAD GENÉRICO
// ============================================================================
/**
 * @brief Filtro digital biquad configurable
 * 
 * Soporta hasta 4 secciones biquad en cascada para filtros de orden alto.
 */
class DigitalFilter {
public:
    static const int MAX_SECTIONS = 4;
    
private:
    BiquadSection sections[MAX_SECTIONS];
    int numSections;
    bool enabled;
    
public:
    DigitalFilter();
    
    // Configuración
    void setCoefficients(int section, float b0, float b1, float b2, float a1, float a2);
    void setNumSections(int n);
    void setEnabled(bool en) { enabled = en; }
    bool isEnabled() const { return enabled; }
    
    // Procesamiento
    float process(float input);
    void reset();
    
    // Getters
    int getNumSections() const { return numSections; }
};

// ============================================================================
// CLASE NotchFilter - FILTRO NOTCH PARA INTERFERENCIA DE RED
// ============================================================================
/**
 * @brief Filtro notch IIR de 2º orden para eliminar 50/60 Hz
 * 
 * Diseño: Notch con Q configurable
 * - Q alto (30-50): muesca estrecha, mínima distorsión de fase
 * - Q bajo (5-10): muesca ancha, mejor rechazo pero más distorsión
 * 
 * Ref: Tompkins 1993, Cap. 3
 */
class NotchFilter {
private:
    BiquadSection biquad;
    float centerFreq;
    float sampleRate;
    float qFactor;
    bool enabled;
    
    void calculateCoefficients();
    
public:
    NotchFilter();
    
    // Configuración
    void configure(float fc, float fs, float Q = 30.0f);
    void setEnabled(bool en) { enabled = en; }
    bool isEnabled() const { return enabled; }
    
    // Procesamiento
    float process(float input);
    void reset();
    
    // Getters
    float getCenterFreq() const { return centerFreq; }
    float getQFactor() const { return qFactor; }
};

// ============================================================================
// CLASE LowpassFilter - BUTTERWORTH PASO BAJO 2º ORDEN
// ============================================================================
/**
 * @brief Filtro paso bajo Butterworth de 2º orden
 * 
 * Características:
 * - Respuesta maximalmente plana en banda de paso
 * - Atenuación -12 dB/octava
 * - Sin rizado (Butterworth)
 */
class LowpassFilter {
private:
    BiquadSection biquad;
    float cutoffFreq;
    float sampleRate;
    bool enabled;
    
    void calculateCoefficients();
    
public:
    LowpassFilter();
    
    // Configuración
    void configure(float fc, float fs);
    void setEnabled(bool en) { enabled = en; }
    bool isEnabled() const { return enabled; }
    
    // Procesamiento
    float process(float input);
    void reset();
    
    // Getters
    float getCutoffFreq() const { return cutoffFreq; }
};

// ============================================================================
// CLASE HighpassFilter - BUTTERWORTH PASO ALTO 2º ORDEN
// ============================================================================
/**
 * @brief Filtro paso alto Butterworth de 2º orden
 * 
 * Aplicaciones:
 * - Eliminar baseline wander en ECG (fc = 0.5 Hz)
 * - Eliminar DC offset en PPG
 * - Eliminar artefactos de movimiento en EMG (fc = 20 Hz)
 */
class HighpassFilter {
private:
    BiquadSection biquad;
    float cutoffFreq;
    float sampleRate;
    bool enabled;
    
    void calculateCoefficients();
    
public:
    HighpassFilter();
    
    // Configuración
    void configure(float fc, float fs);
    void setEnabled(bool en) { enabled = en; }
    bool isEnabled() const { return enabled; }
    
    // Procesamiento
    float process(float input);
    void reset();
    
    // Getters
    float getCutoffFreq() const { return cutoffFreq; }
};

// ============================================================================
// CLASE BandpassFilter - BUTTERWORTH PASA-BANDA 4º ORDEN
// ============================================================================
/**
 * @brief Filtro pasa-banda Butterworth de 4º orden (2 biquads en cascada)
 * 
 * Aplicaciones:
 * - ECG: 0.5-40 Hz (Pan-Tompkins)
 * - EMG: 20-450 Hz (SENIAM)
 * - PPG: 0.5-8 Hz
 */
class BandpassFilter {
private:
    BiquadSection biquadHP;  // Sección paso alto
    BiquadSection biquadLP;  // Sección paso bajo
    float lowCutoff;
    float highCutoff;
    float sampleRate;
    bool enabled;
    
    void calculateCoefficients();
    
public:
    BandpassFilter();
    
    // Configuración
    void configure(float fcLow, float fcHigh, float fs);
    void setEnabled(bool en) { enabled = en; }
    bool isEnabled() const { return enabled; }
    
    // Procesamiento
    float process(float input);
    void reset();
    
    // Getters
    float getLowCutoff() const { return lowCutoff; }
    float getHighCutoff() const { return highCutoff; }
};

// ============================================================================
// CLASE SignalFilterChain - CADENA DE FILTROS PARA SEÑALES BIOMÉDICAS
// ============================================================================
/**
 * @brief Cadena completa de filtrado para una señal biomédica
 * 
 * Pipeline típico:
 *   Input → Highpass → Lowpass → Notch → Output
 * 
 * Configurable para ECG, PPG o EMG con presets.
 */
class SignalFilterChain {
public:
    enum class SignalType {
        ECG,
        PPG,
        EMG
    };
    
private:
    HighpassFilter highpass;
    LowpassFilter lowpass;
    NotchFilter notch;
    
    SignalType signalType;
    float sampleRate;
    bool filteringEnabled;
    
public:
    SignalFilterChain();
    
    // Configuración por preset
    void configureForECG(float fs = 500.0f, float notchFreq = 60.0f);
    void configureForPPG(float fs = 250.0f, float notchFreq = 60.0f);
    void configureForEMG(float fs = 1000.0f, float notchFreq = 60.0f);
    
    // Configuración manual
    void setHighpassCutoff(float fc);
    void setLowpassCutoff(float fc);
    void setNotchFreq(float fc, float Q = 30.0f);
    void setSampleRate(float fs);
    
    // Control de filtros individuales
    void enableHighpass(bool en);
    void enableLowpass(bool en);
    void enableNotch(bool en);
    void enableAll(bool en);
    
    // Procesamiento
    float process(float input);
    void reset();
    
    // Estado
    bool isFilteringEnabled() const { return filteringEnabled; }
    void setFilteringEnabled(bool en) { filteringEnabled = en; }
    SignalType getSignalType() const { return signalType; }
    
    // Acceso a filtros individuales
    HighpassFilter& getHighpass() { return highpass; }
    LowpassFilter& getLowpass() { return lowpass; }
    NotchFilter& getNotch() { return notch; }
};

#endif // DIGITAL_FILTERS_H
