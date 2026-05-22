/**
 * @file ppg_model.h
 * @brief Modelo PPG con doble gaussiana y 6 condiciones clínicas
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Modelo fisiológico de fotopletismografía:
 * - Sístole ~constante, diástole variable (se comprime con HR alto)
 * - PI dinámico como ÚNICO control de amplitud AC
 * - Forma de onda normalizada [0,1] con modificadores suaves por condición
 * 
 * Flujo del modelo:
 *   Patología → HR,PI (dinámicos dentro de rango) → RR=60/HR
 *   → systole_time=f(HR), diastole_time=RR-systole
 *   → pulseShape normalizado [0,1] → AC=PI*scale → signal=DC+pulse*AC
 * 
 * Referencias:
 * - Allen J. Physiol Meas. 2007: Descripción morfológica cualitativa PPG
 * - Sun X et al. 2024: PI variabilidad latido a latido
 * - Fisiología cardiovascular: sístole ~constante, diástole variable
 * - Parámetros numéricos: ajustados empíricamente
 */

#ifndef PPG_MODEL_H
#define PPG_MODEL_H

#include <Arduino.h>
#include "../data/signal_types.h"
#include "../core/digital_filters.h"

// ============================================================================
// CONSTANTES BASE DEL MODELO PPG (Ajustadas empíricamente)
// Estructura de 3 componentes basada en descripción morfológica de Allen 2007
// ============================================================================

// --- Posiciones temporales (fracción del ciclo RR) ---
#define PPG_SYSTOLIC_POS    0.15f   // Pico sistólico: ~15% del ciclo
#define PPG_NOTCH_POS       0.30f   // Muesca dicrótica: ~30% (cierre válvula aórtica)
#define PPG_DIASTOLIC_POS   0.40f   // Pico diastólico: ~40% (onda reflejada)

// --- Anchos gaussianos (desviación estándar normalizada) ---
#define PPG_SYSTOLIC_WIDTH  0.055f  // σ sistólico
#define PPG_DIASTOLIC_WIDTH 0.10f   // σ diastólico (más ancho)
#define PPG_NOTCH_WIDTH     0.02f   // σ muesca (evento valvular rápido)

// --- Amplitudes BASE normalizadas (ajustadas empíricamente) ---
#define PPG_BASE_SYSTOLIC_AMPL   1.0f    // Amplitud sistólica base (referencia)
#define PPG_BASE_DIASTOLIC_RATIO 0.4f    // Ratio diastólico/sistólico
#define PPG_BASE_DICROTIC_DEPTH  0.25f   // Profundidad muesca base

// --- Escalado AC ---
// Fórmula clínica: PI = (AC / DC) × 100%
// Despejando:      AC = PI × DC / 100
// Con DC = 1500 mV (1.5V):
//                  AC = PI × 1500 / 100 = PI × 15 mV
// Ejemplos: PI=3% → AC=45mV, PI=10% → AC=150mV
#define PPG_AC_SCALE_PER_PI  15.0f  // = DC / 100 = 1500 / 100

// --- Duración sistólica (fisiología: ~constante, ~300ms en reposo) ---
// La sístole varía poco con HR; la diástole absorbe el cambio
#define PPG_SYSTOLE_BASE_MS  300.0f  // Duración sistólica base en ms
#define PPG_SYSTOLE_MIN_MS   250.0f  // Mínimo a HR muy alto
#define PPG_SYSTOLE_MAX_MS   350.0f  // Máximo a HR muy bajo

// ============================================================================
// ESTRUCTURA PARA RANGOS DE CONDICIÓN (según tabla rangos_clinicos.md)
// ============================================================================
struct ConditionRanges {
    // Rangos dinámicos
    float hrMin, hrMax;       // Rango HR (BPM)
    float hrCV;               // Coeficiente variación HR (<10% normal, >10% arritmia)
    float piMin, piMax;       // Rango PI (%)
    float piCV;               // Coeficiente variación PI
    // Valores de forma (estructura 3-componentes, ajustados por patología)
    float systolicAmpl;       // Amplitud sistólica (base 1.0)
    float diastolicAmpl;      // Amplitud diastólica (base 0.4, ratio d/s)
    float dicroticDepth;      // Profundidad muesca dicrótica
};

// ============================================================================
// CLASE PPGModel
// ============================================================================
class PPGModel {
private:
    // Estado temporal
    float phaseInCycle;         // Fase actual (0-1)
    float currentRR;            // Intervalo RR actual (segundos)
    uint32_t beatCount;
    
    // Estado para generador gaussiano (Box-Muller)
    bool gaussHasSpare;
    float gaussSpare;
    
    // Parámetros de forma de onda (normalizados, NO en mV)
    float systolicAmplitude;    // Escala sistólica (base 1.0)
    float systolicWidth;        // σ sistólico
    float diastolicAmplitude;   // Escala diastólica (base 0.4)
    float diastolicWidth;       // σ diastólico
    float dicroticDepth;        // Profundidad muesca (base 0.25)
    float dicroticWidth;        // σ muesca
    
    // Parámetros de entrada
    PPGParameters params;
    
    // Parámetros pendientes (Tipo B)
    bool hasPendingParams;
    PPGParameters pendingParams;
    
    // Variables para artefactos
    float motionNoise;
    float baselineWander;
    
    // Último valor de muestra generado
    float lastSampleValue;
    float lastACValue;          // Último valor AC (sin DC)
    
    // HR y PI dinámicos (valor actual dentro del rango de patología)
    float currentHR;            // HR instantáneo (BPM)
    float currentPI;            // PI instantáneo (%)
    
    // Rangos de la condición actual
    ConditionRanges condRanges;
    
    // === VARIABLES PARA MEDICIÓN EN TIEMPO REAL ===
    // Valores medidos en cada ciclo
    float measuredPeakValue;        // Valor del pico sistólico medido (mV)
    float measuredValleyValue;      // Valor del valle (inicio pulso) medido (mV)
    float measuredNotchValue;       // Valor de la muesca dicrótica medida (mV)
    
    // Tracking de máximos/mínimos dentro del ciclo actual
    float currentCyclePeak;         // Máximo en ciclo actual
    float currentCycleValley;       // Mínimo en ciclo actual
    float currentCycleNotch;        // Mínimo en zona de muesca
    
    // Tiempo simulado acumulado (ms)
    float simulatedTime_ms;         // Tiempo total simulado
    float lastPeakTime_ms;          // Tiempo del último pico (simulado)
    float lastValleyTime_ms;        // Tiempo del último valle (simulado)
    float cycleStartTime_ms;        // Inicio del ciclo actual
    
    // Métricas medidas
    float measuredRRInterval_ms;    // Intervalo RR medido (ms)
    float measuredSystoleTime_ms;   // Tiempo sistólico medido (ms)
    float measuredDiastoleTime_ms;  // Tiempo diastólico medido (ms)
    
    // Estado de fase anterior
    float previousPhase;            // Fase anterior para detectar transiciones
    
    // Tiempos de fase calculados
    float systoleTime;          // Duración sístole (ms) - ~constante
    float diastoleTime;         // Duración diástole (ms) - variable
    float systoleFraction;      // Fracción del ciclo para sístole
    
    // DC baseline configurable
    float dcBaseline;           // Nivel DC en mV (0 = señal AC pura)
    
    // Filtrado digital
    SignalFilterChain filterChain;      // Cadena de filtros HP + LP + Notch
    bool filteringEnabled;              // Control de filtrado
    
    // Métodos privados
    void initConditionRanges();                 // Inicializa rangos según condición
    float generateDynamicHR();                  // HR dentro del rango con variabilidad
    float generateDynamicPI();                  // PI dentro del rango con variabilidad
    float calculateSystoleFraction(float hr);   // f(HR) → fracción sistólica
    float generateNextRR();
    float gaussianRandom(float mean, float std);
    float computePulseShape(float phase);       // Retorna forma normalizada [0,1]
    float normalizePulse(float rawPulse);       // Normaliza a [0,1]
    void applyConditionModifiers();
    void detectBeatAndApplyPending();
    
    // Conversión
    uint8_t voltageToDACValue(float voltage);
    uint8_t acValueToDACValue(float acValue_mV);  // Solo componente AC para DAC
    
public:
    PPGModel();
    
    // Configuración
    void setParameters(const PPGParameters& newParams);
    void setPendingParameters(const PPGParameters& newParams);
    void reset();
    
    // =========================================================================
    // PARAMETROS AJUSTABLES DESDE SLIDERS NEXTION
    // =========================================================================
    // HR: 40-180 BPM - Solo cambia duracion del ciclo, no forma de onda
    void setHeartRate(float hr) { 
        hr = constrain(hr, 40.0f, 180.0f);
        params.heartRate = hr;
        currentHR = hr;
        currentRR = 60.0f / hr;
        systoleFraction = calculateSystoleFraction(hr);
        systoleTime = currentRR * 1000.0f * systoleFraction;
        diastoleTime = currentRR * 1000.0f * (1.0f - systoleFraction);
    }
    
    // PI: 0.5-20% - Modula amplitud AC, no toca posicion de pico ni muesca
    void setPerfusionIndex(float pi) {
        pi = constrain(pi, 0.5f, 20.0f);
        params.perfusionIndex = pi;
        currentPI = pi;
    }
    
    // Noise: 0-1 - Ruido gaussiano proporcional a AC
    void setNoiseLevel(float noise) { 
        params.noiseLevel = constrain(noise, 0.0f, 1.0f); 
    }
    
    // Alias para compatibilidad
    void setAmplitude(float amp) { setPerfusionIndex(amp); }
    
    // Configuracion de baseline
    void setDCBaseline(float dc) { dcBaseline = dc; }
    float getDCBaselineConfig() const { return dcBaseline; }
    
    // Generación
    float generateSample(float deltaTime);
    uint8_t getDACValue(float deltaTime);
    
    // Getters
    float getCurrentHeartRate() const { return currentHR; }
    float getCurrentRRInterval() const { return currentRR * 1000.0f; } // ms
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
    
    // Métricas calculadas (del modelo)
    float getACAmplitude() const;      // AC en mV (PI * scale)
    float getDCBaseline() const;       // DC en mV actual
    float getSystoleTime() const;      // Duración sístole en ms (modelo)
    float getDiastoleTime() const;     // Duración diástole en ms (modelo)
    float getSystoleFraction() const { return systoleFraction; }
    
    // === SEÑAL AC PURA (para Nextion Waveform) ===
    float getLastACValue() const { return lastACValue; }  // Señal sin DC
    uint8_t getWaveformValue() const;                     // Escalado a 0-255
    
    // === MÉTRICAS MEDIDAS EN TIEMPO REAL ===
    // (medidas de la señal, no de las variables del modelo)
    float getMeasuredHR() const;           // HR medido desde RR real (BPM)
    float getMeasuredRRInterval() const;   // Intervalo RR medido (ms)
    float getMeasuredACAmplitude() const;  // AC medido: pico - valle (mV)
    float getMeasuredPI() const;           // PI medido: AC/DC × 100 (%)
    float getMeasuredSystoleTime() const;  // Sístole medida (ms)
    float getMeasuredDiastoleTime() const; // Diástole medida (ms)
    float getMeasuredNotchDepth() const;   // Profundidad muesca medida (mV)
    
    // =========================================================================
    // CONTROL DE FILTRADO DIGITAL
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