/**
 * @file emg_model.h
 * @brief Modelo EMG basado en reclutamiento de unidades motoras (sEMG)
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * REFERENCIAS CIENTÍFICAS:
 * 
 * [1] Fuglevand AJ, Winter DA, Patla AE.
 *     "Models of recruitment and rate coding organization in motor-unit pools."
 *     J Neurophysiol. 1993;70(6):2470-2488.
 * 
 * [2] Henneman E, Somjen G, Carpenter DO.
 *     "Functional significance of cell size in spinal motoneurons."
 *     J Neurophysiol. 1965;28:560-580.
 * 
 * [3] De Luca CJ, Hostage EC.
 *     "Relationship between firing rate and recruitment threshold."
 *     J Neurophysiol. 2010;104(2):1034-1046.
 */

#ifndef EMG_MODEL_H
#define EMG_MODEL_H

#include <Arduino.h>
#include "data/signal_types.h"
#include "core/digital_filters.h"

// ============================================================================
// CONSTANTES DEL MODELO - Fuglevand 1993 adaptado para sEMG
// ============================================================================
#define MAX_MOTOR_UNITS     100     // Número de unidades motoras en el pool
#define RMS_BUFFER_SIZE     100     // Ventana de 100ms para cálculo RMS @ 1kHz
#define ENVELOPE_BUFFER_SIZE 30     // Ventana de 30ms para envolvente RMS @ 1kHz
#define EMG_WAVEFORM_GAIN_DEFAULT 5.0f  // Ganancia por defecto para visualización

// Rampa de excitación (simula reclutamiento progresivo de MUs)
#define EXCITATION_RAMP_DURATION 0.10f  // 100ms - tiempo realista de reclutamiento

// ============================================================================
// CONSTANTES DE AMPLITUD - Distribución Exponencial (Fuglevand 1993)
// ============================================================================
// En sEMG las amplitudes se atenúan por el tejido, por eso usamos RR=30 (no 100)
// Rango resultante: 0.05 mV (MUs pequeñas) a ~1.5 mV (MUs grandes)
#define MUAP_AMP_MIN        0.05f   // mV - amplitud mínima (MUs tipo I)
#define MUAP_AMP_RANGE      30.0f   // Factor de rango exponencial (30x para sEMG)

// ============================================================================
// NORMALIZACIÓN MUAP - Mexican Hat Wavelet (Ricker)
// ============================================================================
// El pico de la wavelet (1 - t²/σ²) × exp(-t²/2σ²) ocurre en t = ±σ
// con valor = 2/e ≈ 0.7358, pero para nuestra fórmula centrada el pico es ~0.6065
#define MUAP_PEAK_NORM      0.6065f // Valor analítico del pico para normalización

// ============================================================================
// RANGO DE SALIDA FIJO - JUSTIFICACIÓN CIENTÍFICA (PARTE 1.2)
// ============================================================================
/**
 * RANGO UNIVERSAL: -5.0 a +5.0 mV (pico a pico = 10 mV)
 * 
 * FUENTES CIENTÍFICAS:
 * [1] De Luca CJ. J Appl Biomech. 1997;13:135-163.
 *     → sEMG típico: 50 µV - 5 mV RMS
 *     → MVC: 1-5 mV RMS, picos pueden llegar a ±2-3x el RMS
 * 
 * [2] Merletti R, Parker PA. "Electromyography: Physiology, Engineering."
 *     IEEE Press/Wiley, 2004.
 *     → Amplitud pico-pico sEMG: 0.1-10 mV (range completo)
 *     → 90% de señales clínicas: <5 mV pico
 * 
 * [3] Konrad P. "The ABC of EMG." Noraxon USA Inc., 2005.
 *     → Rango dinámico típico ADC para sEMG: ±5 mV o ±10 mV
 * 
 * Un rango de ±5 mV cubre el 95% de las aplicaciones clínicas de sEMG.
 */
#define EMG_OUTPUT_MIN_MV       -5.0f   // mV - límite inferior fijo (señal cruda)
#define EMG_OUTPUT_MAX_MV        5.0f   // mV - límite superior fijo (señal cruda)
#define EMG_OUTPUT_CENTER_MV     0.0f   // mV - centro (señal bipolar)
#define EMG_RMS_MAX_MV           2.0f   // mV - límite superior envolvente RMS (envelope realista)

// ============================================================================
// PARÁMETROS DE FATIGA MUSCULAR (PARTE 2.1)
// ============================================================================
/**
 * Basado en:
 * - Cifrek M et al. "Surface EMG based muscle fatigue evaluation" (2009)
 * - Sun Y et al. "Analysis of MDF and RMS in fatigue sEMG signals" (2022)
 * - Wang L et al. "Muscle fatigue classification using sEMG" (2021)
 */

// Frecuencia mediana (MDF) - desciende exponencialmente
#define FATIGUE_MDF_INITIAL     95.0f   // Hz - MDF inicial (rango típico EMG)
#define FATIGUE_MDF_FINAL       60.0f   // Hz - MDF final (caída ~37%)
#define FATIGUE_MDF_TAU         10.0f   // s - constante de tiempo decay (rápido)

// Amplitud RMS - DESCIENDE por fatiga periférica (colapso)
#define FATIGUE_RMS_INITIAL     1.5f    // mV - RMS inicial (50% MVC)
#define FATIGUE_RMS_FINAL       0.6f    // mV - RMS final (descenso ~60%)
#define FATIGUE_RMS_TAU         10.0f   // s - constante de tiempo decay (rápido)

// Nivel de fatiga muscular (MFL) - crece linealmente
#define FATIGUE_MFL_DURATION    15.0f   // s - tiempo para MFL = 1.0 (ciclo rápido)

// ============================================================================
// PARÁMETROS DE PROCESAMIENTO DE SEÑAL (PARTE 7.1)
// ============================================================================
// Filtro pasa-banda Butterworth 4º orden (20-450 Hz típico para sEMG)
#define FILTER_CUTOFF_LOW       20.0f   // Hz - elimina artefactos de movimiento
#define FILTER_CUTOFF_HIGH      450.0f  // Hz - elimina ruido de alta frecuencia
#define FILTER_ORDER            2       // Biquad sections (4º orden = 2 SOS)
#define SAMPLE_RATE             1000.0f // Hz - frecuencia de muestreo

// Envolvente (filtro pasa-bajos Butterworth 2º orden, 5 Hz)
#define ENVELOPE_CUTOFF_HZ      5.0f    // Frecuencia de corte para envelope (estándar clínico)

// ============================================================================
// ESTRUCTURA DE UNIDAD MOTORA
// ============================================================================
/**
 * @brief Representa una unidad motora individual
 * 
 * Una unidad motora = 1 motoneurona + todas las fibras musculares que inerva
 */
struct MotorUnit {
    float threshold;            // Umbral de reclutamiento (0-1)
    float amplitude;            // Amplitud del MUAP (mV)
    float baseAmplitude;        // Amplitud base (para restaurar)
    float firingRate;           // Frecuencia de disparo actual (Hz)
    float lastFiringTime;       // Último tiempo de disparo (s)
    float nextFiringTime;       // Próximo tiempo de disparo (s)
    bool isActive;              // Si está reclutada actualmente
};

// ============================================================================
// ESTRUCTURA DE ESTADO DE FATIGA (PARTE 2.2)
// ============================================================================
/**
 * @brief Estado de fatiga muscular para simulación sEMG
 * 
 * Basado en:
 * - Cifrek M et al. "Surface EMG based muscle fatigue evaluation" (2009)
 * - Sun Y et al. "Analysis of MDF and RMS in fatigue sEMG signals" (2022)
 * - Wang L et al. "Muscle fatigue classification using sEMG" (2021)
 */
struct FatigueState {
    float medianFrequency;      // MDF actual (Hz) - desciende
    float rmsDecayFactor;       // Factor multiplicativo de RMS (1.0→0.4)
    float firingRateDecay;      // Decay de frecuencia de disparo (1.0→0.55)
    float muscleFatigueLevel;   // MFL (0-1) - crece linealmente
    float timeInFatigue;        // Tiempo acumulado en fatiga (s)
    bool isActive;              // Si la fatiga está activa
};

// ============================================================================
// ESTRUCTURA DE MÉTRICAS PARA DISPLAY
// ============================================================================
/**
 * @brief Métricas EMG para visualización en tiempo real
 */
struct EMGDisplayMetrics {
    float rmsAmplitude_mV;      // Amplitud RMS en mV
    int activeMotorUnits;       // Número de MUs activas
    float meanFiringRate_Hz;    // Frecuencia promedio de disparo
    float contractionLevel;     // Nivel de contracción (0-100%)
    const char* conditionName;  // Nombre de la condición
};

// ============================================================================
// CLASE EMGModel
// ============================================================================
class EMGModel {
private:
    // Pool de unidades motoras
    MotorUnit motorUnits[MAX_MOTOR_UNITS];
    
    // Estado de excitación
    float currentExcitation;        // Excitación actual (puede variar)
    float baseExcitation;           // Excitación base de la condición
    float targetExcitation;         // Excitación objetivo para rampa
    float excitationRampTime;       // Tiempo transcurrido de rampa (s)
    float accumulatedTime;          // Tiempo acumulado (s)
    
    // Parámetros del usuario
    EMGParameters params;
    
    // Parámetros pendientes (cambio diferido)
    bool hasPendingParams;
    EMGParameters pendingParams;
    
    // Variables para condiciones especiales
    float tremorPhase;              // Fase del temblor (rad)
    float forceVariabilityPhase;    // Fase de variabilidad de fuerza
    FatigueState fatigueState;      // Estado de fatiga muscular (PARTE 2.3)
    
    // Último valor generado (para visualización)
    float lastSampleValue;
    
    // Ganancia para waveform
    float waveformGain;
    
    // Buffer para cálculo de RMS (señal AC cruda - para getRMSAmplitude)
    float rmsBuffer[RMS_BUFFER_SIZE];
    int rmsBufferIndex;
    float rmsSum;
    
    // Buffer para envolvente RMS (señal rectificada - para getProcessedSample)
    float envelopeBuffer[ENVELOPE_BUFFER_SIZE];
    int envelopeBufferIndex;
    float envelopeSum;
    
    // Buffers de procesamiento de señal (PARTE 7.2)
    // Butterworth 4º orden = 2 biquad sections (cada una tiene 2 estados)
    float filterState1[2];  // Estados del primer biquad (x1, y1)
    float filterState2[2];  // Estados del segundo biquad (x2, y2)
    
    // Coeficientes IIR precalculados (pasa-banda 20-450 Hz @ 1kHz)
    // Formato: b0, b1, b2, a1, a2 para cada biquad
    float biquadCoeffs[2][5];
    
    // Filtro suavizante post-bandpass (Butterworth 2º orden @ 100 Hz)
    float smoothingCoeffs[5];          // Coeficientes suavizado
    float smoothingState[2];           // Estados filtro suavizante
    
    // Filtro Butterworth 2º orden para envelope (pasa-bajos 15 Hz)
    float envelopeCoeffs[5];           // Coeficientes: b0, b1, b2, a1, a2
    float envelopeState[2];            // Estados: [x_prev, y_prev]
    float lastProcessedValue;          // Última señal procesada
    
    // Sistema de caché para evitar doble generación (BUG CRÍTICO CORREGIDO)
    float cachedRawSample;             // Última muestra cruda generada
    bool sampleIsCached;               // Flag: ¿hay muestra válida en este tick?
    
    // Estado del generador gaussiano Box-Muller (variables de instancia para reset limpio)
    bool gaussHasSpare;
    float gaussSpare;
    
    // Filtrado digital unificado (interfaz común con ECG/PPG)
    SignalFilterChain filterChain;      // Cadena de filtros HP + LP + Notch
    bool filteringEnabled;              // Control de filtrado adicional
    
    // Métodos privados
    void initializeMotorUnits();
    void resetMotorUnitsToDefault();
    void updateMotorUnitRecruitment();
    float generateMUAP(float timeSinceFiring, float amplitude);
    float gaussianRandom(float mean, float std);
    void applyConditionModifiers();
    void updateRMSBuffer(float sample);
    void updateEnvelopeBuffer(float rectifiedSample);
    float getDefaultExcitation(EMGCondition condition) const;
    
    // Procesamiento de señal (PARTE 7.3)
    void initBiquadCoefficients();      // Inicializa coeficientes Butterworth pasa-banda
    void initSmoothingCoefficients();   // Inicializa filtro suavizante 100 Hz
    void initEnvelopeCoefficients();    // Inicializa coeficientes Butterworth pasa-bajos envelope
    float applyBiquadSection(float input, float* state, const float* coeffs);
    float applyBandpassFilter(float input);
    float applySmoothingFilter(float input);  // Nuevo: suaviza picos post-bandpass
    float applyRectification(float input);
    float applyRMSEnvelope(float input);
    void resetProcessingBuffers();      // Reset buffers al cambiar condición
    
    // Conversión DAC
    uint8_t voltageToDACValue(float voltage) const;
    
public:
    EMGModel();
    
    // Configuración
    void setParameters(const EMGParameters& newParams);
    void setPendingParameters(const EMGParameters& newParams);
    void reset();
    
    // Parámetros Tipo A (aplicación inmediata con validación)
    void setNoiseLevel(float noise);
    void setAmplitude(float amp);
    void setExcitationLevel(float exc);  // Aplica excitación SIN resetear secuencias
    void setWaveformGain(float gain) { waveformGain = constrain(gain, 0.5f, 2.0f); }
    float getWaveformGain() const { return waveformGain; }
    
    // ✅ NUEVO: Método principal de tick (llamar 1 vez por ciclo)
    /**
     * @brief Genera UNA muestra y avanza el modelo
     * @param deltaTime Tiempo desde última muestra (normalmente 0.001f = 1ms)
     * 
     * IMPORTANTE: Llamar EXACTAMENTE una vez por ciclo.
     * getRawSample() y getProcessedSample() usan esta muestra cacheada.
     */
    void tick(float deltaTime);
    
    // ✅ MODIFICADO: Salida CRUDA (sin deltaTime, usa caché)
    /**
     * @brief Obtiene muestra CRUDA cacheada (NO regenera)
     * @return Señal cruda en mV (±5 mV bipolar)
     * 
     * PREREQUISITO: tick(deltaTime) debe haberse llamado antes
     */
    float getRawSample() const;
    
    /**
     * @brief Obtiene DAC de señal CRUDA cacheada
     * @return DAC 0-255 (128 = 0mV centro)
     */
    uint8_t getRawDACValue() const;
    
    // ✅ MODIFICADO: Salida PROCESADA (sin deltaTime, usa caché)
    /**
     * @brief Obtiene muestra PROCESADA cacheada
     * Pipeline: Cruda → Filtro → Rectificación → Envolvente RMS
     * @return Envolvente RMS en mV (0-5 mV unipolar)
     * 
     * PREREQUISITO: tick(deltaTime) debe haberse llamado antes
     */
    float getProcessedSample();
    
    /**
     * @brief Obtiene DAC de señal PROCESADA
     * @return DAC 0-255 (0 = 0mV, 255 = 5mV)
     */
    uint8_t getProcessedDACValue();
    
    // ❌ DEPRECATED: Métodos antiguos (mantener compatibilidad temporal)
    float generateSample(float deltaTime);  // Usar tick() en su lugar
    uint8_t getDACValue(float deltaTime);   // Usar getRawDACValue() en su lugar
    
    // Getters para visualización
    float getCurrentExcitation() const { return currentExcitation; }
    float getCurrentValueMV() const { return lastSampleValue; }
    int getActiveMotorUnits() const;
    float getRMSAmplitude() const;
    float getMeanFiringRate() const;
    float getContractionLevel() const;
    const char* getConditionName() const;
    EMGDisplayMetrics getDisplayMetrics() const;
    
    // Rango de salida (DAC ±5 mV fijo)
    void getOutputRange(float* minMV, float* maxMV) const;
    
    // Getters de fatiga (PARTE 2.3)
    float getFatigueMDF() const { return fatigueState.medianFrequency; }
    float getFatigueRMSFactor() const { return fatigueState.rmsDecayFactor; }
    float getFatigueFRDecay() const { return fatigueState.firingRateDecay; }
    float getFatigueMFL() const { return fatigueState.muscleFatigueLevel; }
    float getFatigueTime() const { return fatigueState.timeInFatigue; }
    bool isFatigueActive() const { return fatigueState.isActive; }
    
    // Getters de parámetros
    EMGCondition getCondition() const { return params.condition; }
    float getNoiseLevel() const { return params.noiseLevel; }
    float getAmplitude() const { return params.amplitude; }
    float getExcitation() const { return currentExcitation; }
    
    // ============================================================================
    // ESCALADO WAVEFORM NEXTION DUAL-CHANNEL (700×380px)
    // ============================================================================
    
    /**
     * @brief Obtiene valor Y para canal 0 (señal cruda bipolar)
     * @return Coordenada Y invertida (0-380), 0=arriba, 380=abajo
     * 
     * Rango: -5mV a +5mV (FIJO)
     * Centro: Y=190 (línea isoeléctrica 0mV)
     * Escala: 1mV/div → 38px
     */
    uint8_t getWaveformValue_Ch0() const;
    
    /**
     * @brief Obtiene valor Y para canal 1 (envelope procesada unipolar)
     * @return Coordenada Y invertida (0-380), 0=arriba, 380=abajo
     * 
     * Rango: 0mV a 2mV (FIJO)
     * Base: Y=380 (baseline 0mV)
     * Escala: 0.5mV/div → 95px
     */
    uint8_t getWaveformValue_Ch1() const;
    
    // ============================================================================
    // SISTEMA DE SECUENCIAS DINÁMICAS
    // ============================================================================
    
    /**
     * @brief Inicia una secuencia predefinida
     * @param sequence Secuencia a ejecutar
     */
    void startSequence(const EMGSequence& sequence);
    
    /**
     * @brief Detiene la secuencia actual (vuelve a modo estático)
     */
    void stopSequence();
    
    /**
     * @brief Verifica si hay secuencia activa
     */
    bool isSequenceActive() const { return sequenceActive; }
    
    /**
     * @brief Obtiene tiempo actual de la secuencia
     */
    float getSequenceTime() const { return sequenceTime; }
    
    /**
     * @brief Obtiene nombre del evento actual
     */
    const char* getCurrentEventName() const;
    
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
    
private:
    // Estado de secuencia
    EMGSequence currentSequence;
    bool sequenceActive;
    float sequenceTime;          // Tiempo dentro de la secuencia (s)
    int currentEventIndex;       // Índice del evento actual
    
    void updateSequence(float deltaTime);  // Actualizar secuencia en tick()
    
    // Validación de parámetros por condición
    float clampExcitationForCondition(float excitation) const;
};

#endif // EMG_MODEL_H
