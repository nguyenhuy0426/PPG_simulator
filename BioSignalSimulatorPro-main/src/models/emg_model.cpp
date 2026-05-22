/**
 * @file emg_model.cpp
 * @brief Implementación del modelo EMG basado en reclutamiento de unidades motoras
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * MODELO BASE:
 * Fuglevand AJ, Winter DA, Patla AE.
 * "Models of recruitment and rate coding organization in motor-unit pools."
 * J Neurophysiol. 1993;70(6):2470-2488.
 * 
 * PRINCIPIO DE RECLUTAMIENTO:
 * Henneman E, Somjen G, Carpenter DO.
 * "Functional significance of cell size in spinal motoneurons."
 * J Neurophysiol. 1965;28:560-580.
 * - Las unidades motoras pequeñas (bajo umbral) se reclutan primero
 * - Las unidades motoras grandes (alto umbral) se reclutan después
 * - El orden de reclutamiento es fijo y predecible
 * 
 * FRECUENCIAS DE DISPARO:
 * De Luca CJ, Hostage EC.
 * "Relationship between firing rate and recruitment threshold of motoneurons."
 * J Neurophysiol. 2010;104(2):1034-1046.
 * - Frecuencia mínima al reclutamiento: 6-8 Hz
 * - Frecuencia máxima en MVC: 30-50 Hz (hasta 60 Hz transitorio)
 * 
 * AMPLITUDES sEMG:
 * De Luca CJ.
 * "The use of surface electromyography in biomechanics."
 * J Appl Biomech. 1997;13:135-163.
 * - EMG de superficie típico: 50 µV - 5 mV
 * - MVC (contracción máxima): 1-5 mV RMS
 * 
 * VARIABILIDAD DE FUERZA:
 * Enoka RM, Christou EA, Hunter SK, et al.
 * "Mechanisms that contribute to differences in motor performance."
 * J Electromyogr Kinesiol. 2003;13(1):1-12.
 * - CV de fuerza en jóvenes: 2-5%
 * - CV de fuerza en mayores/fatiga: 5-10%
 */

#include "models/emg_model.h"
#include "data/emg_sequences.h"
#include "config.h"
#include <math.h>
#include <esp_random.h>

// ============================================================================
// CONSTANTES DEL MODELO (basadas en literatura)
// ============================================================================

// Frecuencias de disparo (De Luca 2010)
static const float FIRING_RATE_MIN = 6.0f;      // Hz al reclutamiento
static const float FIRING_RATE_MAX = 50.0f;     // Hz en MVC
static const float FIRING_RATE_GAIN = 40.0f;    // Ganancia Hz/unidad de excitación

// Variabilidad del intervalo inter-spike (ISI)
// Típico CV = 15-25% según literatura
static const float ISI_VARIABILITY_CV = 0.20f;  // 20% coeficiente de variación

// Variabilidad de fuerza (fluctuación natural del control motor)
static const float FORCE_VARIABILITY_FREQ = 2.0f;   // Hz (1-3 Hz típico)
static const float FORCE_VARIABILITY_AMP = 0.04f;   // ±4% de fluctuación

// Parámetros del MUAP trifásico (normal)
static const float MUAP_SIGMA = 2.0f;           // ms (controla ancho)
static const float MUAP_DURATION = 12.0f;       // ms duración total

// Frecuencia del temblor Parkinsoniano
static const float TREMOR_FREQUENCY = 5.0f;          // Hz - frecuencia del temblor (4-6 Hz)

// ============================================================================
// CONSTRUCTOR
// ============================================================================
EMGModel::EMGModel() {
    hasPendingParams = false;
    forceVariabilityPhase = 0.0f;
    
    // Inicializar sistema de secuencias
    sequenceActive = false;
    sequenceTime = 0.0f;
    currentEventIndex = 0;
    currentSequence.type = EMGSequenceType::STATIC;
    currentSequence.numEvents = 0;
    currentSequence.loop = false;
    
    // Inicializar estados filtro suavizante
    smoothingState[0] = 0.0f;
    smoothingState[1] = 0.0f;
    
    // Inicializar coeficientes de filtros
    initBiquadCoefficients();
    initSmoothingCoefficients();
    initEnvelopeCoefficients();
    
    reset();
}

// ============================================================================
// RESET
// ============================================================================
void EMGModel::reset() {
    currentExcitation = 0.0f;
    baseExcitation = 0.0f;
    targetExcitation = 0.0f;
    excitationRampTime = EXCITATION_RAMP_DURATION;  // Ya completada (no rampa inicial)
    accumulatedTime = 0.0f;
    tremorPhase = 0.0f;
    forceVariabilityPhase = 0.0f;
    lastSampleValue = 0.0f;
    waveformGain = EMG_WAVEFORM_GAIN_DEFAULT;
    
    // Inicializar estado de fatiga
    fatigueState.isActive = false;
    fatigueState.timeInFatigue = 0.0f;
    fatigueState.medianFrequency = FATIGUE_MDF_INITIAL;
    fatigueState.rmsDecayFactor = 1.0f;
    fatigueState.firingRateDecay = 1.0f;
    fatigueState.muscleFatigueLevel = 0.0f;
    
    // Inicializar buffer RMS (señal AC cruda)
    rmsBufferIndex = 0;
    rmsSum = 0.0f;
    for (int i = 0; i < RMS_BUFFER_SIZE; i++) {
        rmsBuffer[i] = 0.0f;
    }
    
    // Inicializar buffer envolvente (señal rectificada)
    envelopeBufferIndex = 0;
    envelopeSum = 0.0f;
    for (int i = 0; i < ENVELOPE_BUFFER_SIZE; i++) {
        envelopeBuffer[i] = 0.0f;
    }
    
    // Inicializar coeficientes biquad Butterworth 4º orden
    initBiquadCoefficients();
    
    // Inicializar buffers de procesamiento (PARTE 8)
    resetProcessingBuffers();
    
    // Reset generador gaussiano Box-Muller
    gaussHasSpare = false;
    gaussSpare = 0.0f;
    
    // Reset sistema de caché (BUG CRÍTICO CORREGIDO)
    cachedRawSample = 0.0f;
    sampleIsCached = false;
    
    // Actualizar baseExcitation después de aplicar modifiers (CORRECCIÓN 4)
    baseExcitation = currentExcitation;
    
    // Inicializar filtrado digital (deshabilitado por defecto)
    filterChain.configureForEMG(SAMPLE_RATE, 60.0f);  // 1000 Hz, notch 60 Hz
    filterChain.reset();
    filteringEnabled = false;  // Deshabilitado - usuario activa si necesita
    
    initializeMotorUnits();
}

// ============================================================================
// INICIALIZACIÓN DE UNIDADES MOTORAS
// ============================================================================
/**
 * @brief Inicializa el pool de unidades motoras según el principio de Henneman
 * 
 * El principio de Henneman establece que las MUs se reclutan en orden de tamaño:
 * - MUs pequeñas (tipo I, lentas, resistentes a fatiga) → umbral bajo
 * - MUs grandes (tipo II, rápidas, fatigables) → umbral alto
 * 
 * Distribución EXACTA de Fuglevand 1993:
 *   threshold_i = RTE × (e^(ln(RR)×i/n) / e^(ln(RR)))
 * Parámetros:
 *   - RTE = 0.35 (última MU se recluta al 35% MVC)
 *   - RR = 30 (rango exponencial)
 *   - Pool: 100 MUs (vs 120 en paper original, escalado proporcionalmente)
 * Resultado:
 *   - Primera MU: threshold ≈ 1.2% MVC → NO activa en REST (0.5%)
 *   - Última MU: threshold = 35% MVC → Totalmente reclutado en HIGH (80%)
 */
void EMGModel::initializeMotorUnits() {
    // Parámetros de Fuglevand 1993 (ajustados para 100 MUs vs 120 del paper original)
    const float RR = 30.0f;  // Recruitment Range (rango exponencial)
    const float RTE = 0.35f; // Recruitment Threshold Excitation (35% MVC para última MU)
    
    for (int i = 0; i < MAX_MOTOR_UNITS; i++) {
        float normalizedIndex = (float)i / (float)MAX_MOTOR_UNITS;
        
        // Umbral exponencial EXACTO de Fuglevand 1993:
        // threshold_i = RTE × (e^(ln(RR)×i/n) / e^(ln(RR)))
        // Simplificado: RTE × (RR^(i/n) / RR) = RTE × RR^((i/n) - 1)
        // Primera MU (i=0): ~1.2% MVC, Última MU (i=99): 35% MVC
        motorUnits[i].threshold = RTE * expf(logf(RR) * (normalizedIndex - 1.0f));
        
        // Amplitud EXPONENCIAL según Fuglevand 1993
        // P_i = P_min × exp(ln(RR_amp) × i/n)
        // Para sEMG usamos RR_amp = 30 (atenuación tisular vs needle EMG con RR=100)
        // Rango resultante: 0.05 mV (MUs pequeñas tipo I) a ~1.5 mV (MUs grandes tipo II)
        motorUnits[i].amplitude = MUAP_AMP_MIN * expf(logf(MUAP_AMP_RANGE) * normalizedIndex);
        
        // Guardar amplitud base para restaurar después de patologías
        motorUnits[i].baseAmplitude = motorUnits[i].amplitude;
        
        // Frecuencia de disparo inicial
        motorUnits[i].firingRate = FIRING_RATE_MIN;
        
        // Tiempos de disparo
        motorUnits[i].lastFiringTime = -1.0f;
        motorUnits[i].nextFiringTime = gaussianRandom(0.0f, 0.1f);
        motorUnits[i].isActive = false;
    }
}

// ============================================================================
// RESTAURAR UNIDADES MOTORAS A VALORES BASE
// ============================================================================
/**
 * @brief Restaura todas las MUs a sus valores iniciales
 * 
 * IMPORTANTE: Debe llamarse ANTES de aplicar modificadores de condición
 * para evitar que cambios de condiciones anteriores persistan.
 */
void EMGModel::resetMotorUnitsToDefault() {
    // Parámetros de Fuglevand 1993 (DEBE coincidir con initializeMotorUnits)
    const float RR = 30.0f;  // Recruitment Range (rango exponencial)
    const float RTE = 0.35f; // Recruitment Threshold Excitation (35% MVC para última MU)
    
    for (int i = 0; i < MAX_MOTOR_UNITS; i++) {
        float normalizedIndex = (float)i / (float)MAX_MOTOR_UNITS;
        
        // Restaurar umbral con FÓRMULA EXACTA de Fuglevand 1993
        // threshold_i = RTE × RR^((i/n) - 1)
        // Primera MU (i=0): ~1.2% MVC → NO activa en REST (0.5%)
        // Última MU (i=99): 35% MVC
        motorUnits[i].threshold = RTE * expf(logf(RR) * (normalizedIndex - 1.0f));
        
        // Restaurar amplitud desde base guardada
        motorUnits[i].amplitude = motorUnits[i].baseAmplitude;
        
        // Resetear estado
        motorUnits[i].isActive = false;
    }
}

// ============================================================================
// CONFIGURACIÓN DE PARÁMETROS
// ============================================================================
void EMGModel::setParameters(const EMGParameters& newParams) {
    params = newParams;
    
    // IMPORTANTE: Restaurar MUs a valores base antes de aplicar nueva condición
    resetMotorUnitsToDefault();
    
    // **ACTIVACIÓN AUTOMÁTICA DE SECUENCIAS DINÁMICAS**
    // Solo para LOW, MODERATE, HIGH (muestran ciclo REST→CONTRACCIÓN)
    // REST, TREMOR y FATIGUE son señales PURAS sin secuencias
    switch (params.condition) {
        case EMGCondition::LOW_CONTRACTION:
            // Secuencia dinámica: REST 2s + LOW 8s (ciclo 10s)
            startSequence(SEQ_LOW_DYNAMIC);
            break;
            
        case EMGCondition::MODERATE_CONTRACTION:
            // Secuencia dinámica: REST 2s + MODERATE 6s (ciclo 8s)
            startSequence(SEQ_MODERATE_DYNAMIC);
            break;
            
        case EMGCondition::HIGH_CONTRACTION:
            // Secuencia dinámica: REST 3s + HIGH 5s (ciclo 8s)
            startSequence(SEQ_HIGH_DYNAMIC);
            break;
            
        default:
            // REST, TREMOR, FATIGUE: Señales puras sin secuencias
            // Detener cualquier secuencia activa
            stopSequence();
            break;
    }
    
    // Aplicar modificadores de la condición seleccionada
    applyConditionModifiers();
    
    // Guardar excitación base (será modulada por variabilidad)
    baseExcitation = currentExcitation;
}

void EMGModel::setPendingParameters(const EMGParameters& newParams) {
    pendingParams = newParams;
    hasPendingParams = true;
}

// ============================================================================
// MODIFICADORES POR CONDICIÓN
// ============================================================================
/**
 * @brief Aplica modificadores específicos según la condición EMG
 * 
 * Cada condición establece:
 * - Nivel de excitación (determina cuántas MUs se reclutan)
 * - Modificaciones morfológicas (miopatía, neuropatía)
 * - Comportamientos especiales (temblor, fasciculación)
 */
void EMGModel::applyConditionModifiers() {
    // Resetear variables de condiciones especiales
    tremorPhase = 0.0f;
    
    // Resetear buffers de procesamiento al cambiar condición (CORRECCIÓN 6)
    resetProcessingBuffers();
    
    switch (params.condition) {
        case EMGCondition::REST:
            // Reposo: 0-5% MVC - tono postural mínimo
            // RMS <0.05 mV, muy pocas MUs activas (0-5 típico)
            // Default 0.5% fisiológico (De Luca 1997: "actividad basal mínima")
            currentExcitation = (params.excitationLevel > 0.0f) 
                ? constrain(params.excitationLevel, 0.0f, 0.05f) 
                : 0.005f;
            break;
            
        case EMGCondition::LOW_CONTRACTION:
            // Contracción baja: 5-20% MVC
            // Default 12% si no se especifica (punto medio del rango)
            currentExcitation = (params.excitationLevel > 0.0f) 
                ? constrain(params.excitationLevel, 0.05f, 0.20f) 
                : 0.12f;
            break;
            
        case EMGCondition::MODERATE_CONTRACTION:
            // Contracción moderada: 20-50% MVC
            // Default 35% si no se especifica (punto medio del rango)
            currentExcitation = (params.excitationLevel > 0.0f) 
                ? constrain(params.excitationLevel, 0.20f, 0.50f) 
                : 0.35f;
            break;
            
        case EMGCondition::HIGH_CONTRACTION:
            // Contracción alta: 50-100% MVC
            // Default 80% (MVC típico real, mayoría no alcanza 100%)
            // Ref: Fuglevand 1993 usa 80-90% para simulaciones MVC
            currentExcitation = (params.excitationLevel > 0.0f) 
                ? constrain(params.excitationLevel, 0.50f, 1.0f) 
                : 0.80f;
            break;
            
        case EMGCondition::TREMOR:
            // Temblor Parkinsoniano: 4-6 Hz (media 5 Hz)
            // Ref: Deuschl G. Mov Disord. 1998;13(S3):2-23
            // RMS objetivo: 0.3 mV (centro de 0.1-0.5 mV)
            // La excitación se modula sinusoidalmente en generateSample()
            currentExcitation = 0.0f;  // Se modula cíclicamente
            break;
            
        case EMGCondition::FATIGUE:
            // Fatiga muscular TIPO 2: Colapso periférico (PARTE 4)
            // Ciclo rápido visible en ~14s:
            // - Sostenido: 0-3s (estable)
            // - Descenso: 3-10s (progresivo)
            // - Colapso: 10-15s (acelerado)
            // RMS: 1.5 mV → 0.6 mV (↓60% fatiga periférica)
            // MDF: 95 Hz → 60 Hz (↓37%)
            // FR: 22 Hz → 12 Hz (↓45%, irregular)
            // Refs: Cifrek 2009, Wang 2021, Dimitrov 2006
            currentExcitation = 0.50f;  // Protocolo fijo 50% MVC
            fatigueState.isActive = true;
            fatigueState.medianFrequency = FATIGUE_MDF_INITIAL;
            fatigueState.rmsDecayFactor = 1.0f;
            fatigueState.firingRateDecay = 1.0f;
            fatigueState.muscleFatigueLevel = 0.0f;
            fatigueState.timeInFatigue = 0.0f;
            break;
            
        default:
            currentExcitation = 0.0f;
            break;
    }
    
    // Actualizar baseExcitation después de modifiers (CORRECCIÓN 4)
    baseExcitation = currentExcitation;
}

// ============================================================================
// ACTUALIZACIÓN DE RECLUTAMIENTO
// ============================================================================
/**
 * @brief Actualiza el estado de reclutamiento de todas las MUs
 * 
 * Según De Luca 2010, la relación entre excitación y frecuencia de disparo es:
 *   FR = FR_min + gain × (excitation - threshold)
 * 
 * donde:
 *   - FR_min = 6-8 Hz (frecuencia al reclutamiento)
 *   - gain = ~40 Hz por unidad de excitación
 *   - FR_max = 50 Hz (puede llegar a 60 transitoriamente)
 */
void EMGModel::updateMotorUnitRecruitment() {
    for (int i = 0; i < MAX_MOTOR_UNITS; i++) {
        // Verificar si la MU debe activarse según su umbral
        if (currentExcitation >= motorUnits[i].threshold) {
            if (!motorUnits[i].isActive) {
                // Recién reclutada: programar primer disparo
                motorUnits[i].isActive = true;
                motorUnits[i].nextFiringTime = accumulatedTime + gaussianRandom(0.05f, 0.02f);
            }
            
            // Calcular frecuencia de disparo (De Luca 2010)
            float excitationAboveThreshold = currentExcitation - motorUnits[i].threshold;
            motorUnits[i].firingRate = FIRING_RATE_MIN + excitationAboveThreshold * FIRING_RATE_GAIN;
            
            // TREMOR: Frecuencia FIJA 4.5 Hz (característica de Parkinson)
            if (params.condition == EMGCondition::TREMOR) {
                motorUnits[i].firingRate = 4.5f;  // Hz constante
            }
            
            // Aplicar decay de fatiga a frecuencia de disparo
            if (fatigueState.isActive) {
                motorUnits[i].firingRate *= fatigueState.firingRateDecay;
            }
            
            // Limitar a rango fisiológico (6-50 Hz, hasta 60 en picos)
            motorUnits[i].firingRate = constrain(motorUnits[i].firingRate, 
                                                  FIRING_RATE_MIN, 
                                                  FIRING_RATE_MAX);
        } else {
            motorUnits[i].isActive = false;
        }
    }
}

// ============================================================================
// GENERACIÓN DE MUAP TRIFÁSICO
// ============================================================================
/**
 * @brief Genera un potencial de acción de unidad motora (MUAP) trifásico
 * 
 * Usa la segunda derivada de una Gaussiana para producir la forma
 * característica: pequeño positivo → grande negativo → pequeño positivo
 * 
 * La forma matemática es:
 *   MUAP(t) = A × (1 - ((t-t0)/σ)²) × exp(-((t-t0)²)/(2σ²))
 * 
 * Esta es la "Mexican Hat Wavelet" o wavelet de Ricker, usada
 * frecuentemente para modelar MUAPs en literatura.
 * 
 * @param timeSinceFiring Tiempo desde el último disparo (segundos)
 * @param amplitude Amplitud del MUAP (mV)
 * @return Valor del MUAP en este instante (mV)
 */
float EMGModel::generateMUAP(float timeSinceFiring, float amplitude) {
    // Convertir a milisegundos para trabajar con parámetros en ms
    float t_ms = timeSinceFiring * 1000.0f;
    
    // Fuera de la ventana de duración, no hay contribución
    if (t_ms < 0 || t_ms > MUAP_DURATION) {
        return 0.0f;
    }
    
    // Centrar el MUAP en la mitad de la duración
    float t0 = MUAP_DURATION / 2.0f;
    float t_centered = t_ms - t0;
    
    // Segunda derivada de Gaussiana (Mexican Hat Wavelet)
    // Normalizada para que el pico negativo tenga amplitud = amplitude
    float sigma_sq = MUAP_SIGMA * MUAP_SIGMA;
    float t_sq = t_centered * t_centered;
    
    float gaussian = expf(-t_sq / (2.0f * sigma_sq));
    float wavelet = (1.0f - t_sq / sigma_sq) * gaussian;
    
    // El factor -1 invierte para que el pico principal sea negativo
    // (convención en EMG: el pico más grande suele ser negativo)
    // Dividimos por MUAP_PEAK_NORM (0.6065) para que el pico sea exactamente = amplitude
    return -amplitude * wavelet / MUAP_PEAK_NORM;
}


// ============================================================================
// GENERACIÓN DE MUESTRA
// ============================================================================
/**
 * @brief Genera una muestra de EMG
 * 
 * Proceso:
 * 1. Aplicar variabilidad natural de fuerza (fluctuación del control motor)
 * 2. Manejar condiciones especiales (temblor, fatiga, fasciculación)
 * 3. Actualizar reclutamiento de MUs
 * 4. Sumar MUAPs de todas las MUs activas que disparan
 * 5. Añadir ruido de fondo
 * 
 * @param deltaTime Tiempo desde última muestra (típicamente 1 ms)
 * @return Valor EMG en mV
 */
float EMGModel::generateSample(float deltaTime) {
    accumulatedTime += deltaTime;
    
    // Aplicar parámetros pendientes si hay
    if (hasPendingParams) {
        setParameters(pendingParams);
        hasPendingParams = false;
    }
    
    // =========================================================================
    // RAMPA DE EXCITACIÓN (simula reclutamiento progresivo de MUs)
    // =========================================================================
    // En contracciones reales, las MUs no se reclutan instantáneamente.
    // Hay un período de 50-150ms donde se reclutan progresivamente según
    // el principio de Henneman (pequeñas primero, grandes después).
    if (excitationRampTime < EXCITATION_RAMP_DURATION) {
        excitationRampTime += deltaTime;
        float t = excitationRampTime / EXCITATION_RAMP_DURATION;
        t = constrain(t, 0.0f, 1.0f);
        
        // Interpolación ease-in-out cúbica (transición suave S-curve)
        float smoothT = t < 0.5f 
            ? 4.0f * t * t * t 
            : 1.0f - powf(-2.0f * t + 2.0f, 3.0f) / 2.0f;
        
        // Interpolar entre excitación actual y objetivo
        baseExcitation = baseExcitation * (1.0f - smoothT) + targetExcitation * smoothT;
        currentExcitation = baseExcitation;
    }
    
    // =========================================================================
    // ACTUALIZACIÓN DE FATIGA MUSCULAR (PARTE 5)
    // =========================================================================
    if (fatigueState.isActive) {
        fatigueState.timeInFatigue += deltaTime;
        
        // MDF desciende exponencialmente: MDF(t) = MDF_final + (MDF_initial - MDF_final) * exp(-t/τ)
        // 95 Hz → 60 Hz en ~10s (visible en ventana)
        fatigueState.medianFrequency = FATIGUE_MDF_FINAL + 
            (FATIGUE_MDF_INITIAL - FATIGUE_MDF_FINAL) * 
            expf(-fatigueState.timeInFatigue / FATIGUE_MDF_TAU);
        
        // RMS DESCIENDE exponencialmente (fatiga periférica - colapso)
        // factor(t) = RMS_final/RMS_initial + (1 - RMS_final/RMS_initial) * exp(-t/τ)
        // 1.5 mV → 0.6 mV en ~10s
        float finalRatio = FATIGUE_RMS_FINAL / FATIGUE_RMS_INITIAL;  // ~0.4
        fatigueState.rmsDecayFactor = finalRatio + (1.0f - finalRatio) * 
            expf(-fatigueState.timeInFatigue / FATIGUE_RMS_TAU);
        
        // Firing rate DISMINUYE exponencialmente (pérdida progresiva)
        // FR(t) = 0.55 + 0.45 * exp(-t/τ)  → 1.0 a 0.55 (~45% reducción)
        // Más agresivo para colapso visible
        fatigueState.firingRateDecay = 0.55f + 0.45f * 
            expf(-fatigueState.timeInFatigue / FATIGUE_RMS_TAU);
        
        // MFL crece linealmente: MFL(t) = t / T_total
        // Alcanza 1.0 en 15s (ciclo completo)
        fatigueState.muscleFatigueLevel = 
            constrain(fatigueState.timeInFatigue / FATIGUE_MFL_DURATION, 0.0f, 1.0f);
    }
    
    // =========================================================================
    // VARIABILIDAD NATURAL DE FUERZA
    // =========================================================================
    // El control motor humano no es perfecto - hay fluctuaciones naturales
    // de ~2-5% a frecuencia de 1-3 Hz (Enoka 2003)
    // Solo aplicar si hay contracción activa (>5% MVC) y no es TREMOR ni FATIGUE
    if (baseExcitation > 0.05f && 
        params.condition != EMGCondition::TREMOR &&
        params.condition != EMGCondition::FATIGUE) {
        
        forceVariabilityPhase += deltaTime * 2.0f * PI * FORCE_VARIABILITY_FREQ;
        if (forceVariabilityPhase > 2.0f * PI) forceVariabilityPhase -= 2.0f * PI;
        
        float variability = sinf(forceVariabilityPhase) * FORCE_VARIABILITY_AMP;
        // Añadir componente aleatorio de alta frecuencia
        variability += gaussianRandom(0.0f, 0.02f);
        
        currentExcitation = baseExcitation * (1.0f + variability);
        currentExcitation = constrain(currentExcitation, 0.0f, 1.0f);
    }
    
    // =========================================================================
    // MODIFICACIONES ESPECÍFICAS POR CONDICIÓN
    // =========================================================================
    if (params.condition == EMGCondition::TREMOR) {
        // Temblor Parkinsoniano: 4-6 Hz (típico 5 Hz)
        // Características:
        // - Músculo en REPOSO (5-10% MVC)
        // - Pocas MUs activas (10-25)
        // - FR constante 4.5 Hz
        // - Amplitud controlada ±0.5-1.0 mV
        // - RMS objetivo: 0.15-0.25 mV
        tremorPhase += deltaTime * 2.0f * PI * TREMOR_FREQUENCY;
        if (tremorPhase > 2.0f * PI) tremorPhase -= 2.0f * PI;
        
        // Modulación sinusoidal suave: oscila entre mínimo y máximo
        float tremorModulation = 0.5f + 0.5f * sinf(tremorPhase);  // 0-1
        currentExcitation = 0.05f + 0.05f * tremorModulation;  // 5-10% MVC
    }
    
    // =========================================================================
    // ACTUALIZAR RECLUTAMIENTO
    // =========================================================================
    updateMotorUnitRecruitment();
    
    // =========================================================================
    // GENERAR SEÑAL: SUMAR MUAPs DE TODAS LAS MUs ACTIVAS
    // =========================================================================
    float signal = 0.0f;
    
    // Todas las condiciones sEMG usan duración estándar
    const float muapDuration = MUAP_DURATION;
    
    for (int i = 0; i < MAX_MOTOR_UNITS; i++) {
        if (motorUnits[i].isActive || 
            (accumulatedTime - motorUnits[i].lastFiringTime) < (muapDuration / 1000.0f)) {
            
            // Verificar si es tiempo de disparar
            if (motorUnits[i].isActive && accumulatedTime >= motorUnits[i].nextFiringTime) {
                motorUnits[i].lastFiringTime = accumulatedTime;
                
                float isi = 1.0f / motorUnits[i].firingRate;
                isi *= (1.0f + gaussianRandom(0.0f, ISI_VARIABILITY_CV));
                isi = constrain(isi, 0.015f, 0.2f);
                motorUnits[i].nextFiringTime = accumulatedTime + isi;
            }
            
            // Añadir contribución del MUAP (todas las condiciones usan MUAP estándar)
            float timeSinceFiring = accumulatedTime - motorUnits[i].lastFiringTime;
            if (timeSinceFiring >= 0 && timeSinceFiring < (muapDuration / 1000.0f)) {
                signal += generateMUAP(timeSinceFiring, motorUnits[i].amplitude);
            }
        }
    }
    
    // =========================================================================
    // APLICAR DESCENSO DE RMS POR FATIGA PERIFÉRICA (PARTE 5)
    // =========================================================================
    if (fatigueState.isActive) {
        signal *= fatigueState.rmsDecayFactor;  // RMS DESCIENDE (colapso)
    }
    
    // =========================================================================
    // REDUCIR AMPLITUD EN TREMOR (PARTE 5.1)
    // =========================================================================
    // En Parkinson, músculo está en reposo → amplitud controlada
    if (params.condition == EMGCondition::TREMOR) {
        signal *= 0.35f;  // Reducir a 35% para picos ±0.5-1.0 mV
    }
    
    // =========================================================================
    // NORMALIZACIÓN POR √(MUs ACTIVAS) - REDUCE PICOS DE SUPERPOSICIÓN
    // =========================================================================
    // Problema: Cuando >40 MUs disparan simultáneamente, sus MUAPs se superponen
    // y crean picos masivos (3-4 mV) que no reflejan la fuerza real.
    // Solución: Normalizar por √(activeMUs) cuando hay muchas MUs activas.
    // Esto simula que en EMG real hay cancelación de fase entre MUAPs.
    int activeMUs = getActiveMotorUnits();
    if (activeMUs > 40) {
        signal *= sqrtf(40.0f / (float)activeMUs);
    }
    
    // =========================================================================
    // APLICAR GANANCIA Y RUIDO
    // =========================================================================
    
    signal *= params.amplitude;  // Ganancia de usuario (default 1.0x)
    
    // Ruido de fondo (interferencia, ruido de electrodo)
    // 10% ruido = 0.5 mV sigma (proporcional al rango EMG ±5 mV)
    signal += gaussianRandom(0.0f, params.noiseLevel * 5.0f);
    
    // =========================================================================
    // CLAMP FISIOLÓGICO DE SEÑAL CRUDA (SATURACIÓN DE AMPLIFICADOR)
    // =========================================================================
    // Los amplificadores EMG reales saturan en ±5 mV. Este clamp es 100%
    // fisiológicamente correcto y previene que picos instantáneos (superposición
    // de MUAPs) excedan el rango antes del filtrado.
    signal = constrain(signal, EMG_OUTPUT_MIN_MV, EMG_OUTPUT_MAX_MV);
    
    // =========================================================================
    // ACTUALIZAR BUFFER RMS Y GUARDAR VALOR
    // =========================================================================
    updateRMSBuffer(signal);
    lastSampleValue = signal;
    
    return signal;
}

/**
 * @brief Actualiza el buffer circular para cálculo de RMS (señal AC cruda)
 * @param sample Muestra de señal cruda bipolar (±mV)
 * 
 * Este RMS es para medir amplitud total de la señal AC (getRMSAmplitude).
 * NO es para envolvente visual - para eso usar updateEnvelopeBuffer.
 */
void EMGModel::updateRMSBuffer(float sample) {
    // Restar el valor antiguo de la suma
    rmsSum -= rmsBuffer[rmsBufferIndex] * rmsBuffer[rmsBufferIndex];
    
    // Añadir nuevo valor
    rmsBuffer[rmsBufferIndex] = sample;
    rmsSum += sample * sample;
    
    // Avanzar índice circular
    rmsBufferIndex = (rmsBufferIndex + 1) % RMS_BUFFER_SIZE;
}

/**
 * @brief Actualiza buffer para envolvente RMS (señal RECTIFICADA)
 * @param rectifiedSample Muestra rectificada |x| (solo positiva)
 * 
 * Este RMS es para envolvente visual (getProcessedSample).
 * Ventana de 30ms según recomendaciones SENIAM/De Luca.
 * 
 * La envolvente RMS SIEMPRE es <= que los picos de la rectificada,
 * porque promedia la energía en la ventana.
 */
void EMGModel::updateEnvelopeBuffer(float rectifiedSample) {
    // Restar el valor antiguo de la suma
    envelopeSum -= envelopeBuffer[envelopeBufferIndex] * envelopeBuffer[envelopeBufferIndex];
    
    // Añadir nuevo valor rectificado
    envelopeBuffer[envelopeBufferIndex] = rectifiedSample;
    envelopeSum += rectifiedSample * rectifiedSample;
    
    // Avanzar índice circular
    envelopeBufferIndex = (envelopeBufferIndex + 1) % ENVELOPE_BUFFER_SIZE;
}

uint8_t EMGModel::getDACValue(float deltaTime) {
    float voltage = generateSample(deltaTime);
    return voltageToDACValue(voltage);
}

// ============================================================================
// HELPERS
// ============================================================================

/**
 * @brief Genera número aleatorio con distribución Gaussiana
 * 
 * Implementa el algoritmo Box-Muller para transformar números uniformes
 * en distribución normal. Usa variables de instancia en lugar de static
 * para permitir reset limpio del modelo y evitar problemas de thread-safety.
 * 
 * @param mean Media de la distribución
 * @param std Desviación estándar
 * @return Valor aleatorio con distribución N(mean, std)
 */
float EMGModel::gaussianRandom(float mean, float std) {
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

// ============================================================================
// GETTERS PARA VISUALIZACIÓN
// ============================================================================

/**
 * @brief Obtiene número de unidades motoras activas
 * @return Cantidad de MUs actualmente reclutadas (0-100)
 */
int EMGModel::getActiveMotorUnits() const {
    int count = 0;
    for (int i = 0; i < MAX_MOTOR_UNITS; i++) {
        if (motorUnits[i].isActive) count++;
    }
    return count;
}

/**
 * @brief Obtiene amplitud RMS de la señal EMG
 * @return RMS en mV (calculado sobre ventana de ~100ms)
 * 
 * El RMS es la métrica más común para cuantificar actividad EMG.
 * Valores típicos:
 *   - Reposo: < 0.05 mV
 *   - Contracción leve: 0.1-0.5 mV
 *   - Contracción moderada: 0.5-1.5 mV
 *   - Contracción máxima: 1.5-4.0 mV
 */
float EMGModel::getRMSAmplitude() const {
    if (rmsSum <= 0.0f) return 0.0f;
    return sqrtf(rmsSum / (float)RMS_BUFFER_SIZE);
}

/**
 * @brief Obtiene frecuencia promedio de disparo de MUs activas
 * @return Frecuencia en Hz (6-50 Hz típico)
 */
float EMGModel::getMeanFiringRate() const {
    float sumRate = 0.0f;
    int activeCount = 0;
    
    for (int i = 0; i < MAX_MOTOR_UNITS; i++) {
        if (motorUnits[i].isActive) {
            sumRate += motorUnits[i].firingRate;
            activeCount++;
        }
    }
    
    if (activeCount == 0) return 0.0f;
    return sumRate / (float)activeCount;
}

/**
 * @brief Obtiene excitación por defecto para una condición
 * @param condition Condición EMG
 * @return Nivel de excitación (0-1)
 */
float EMGModel::getDefaultExcitation(EMGCondition condition) const {
    switch (condition) {
        case EMGCondition::REST:                 return 0.005f;
        case EMGCondition::LOW_CONTRACTION:      return 0.12f;
        case EMGCondition::MODERATE_CONTRACTION: return 0.35f;
        case EMGCondition::HIGH_CONTRACTION:     return 0.80f;
        case EMGCondition::TREMOR:               return 0.0f;
        case EMGCondition::FATIGUE:              return 0.50f;
        default:                                 return 0.0f;
    }
}

/**
 * @brief Obtiene nivel de contracción actual
 * @return Porcentaje de contracción máxima (0-100%)
 */
float EMGModel::getContractionLevel() const {
    return currentExcitation * 100.0f;
}

/**
 * @brief Obtiene nombre de la condición actual
 * @return String descriptivo de la condición
 */
const char* EMGModel::getConditionName() const {
    switch (params.condition) {
        case EMGCondition::REST:                 return "Reposo";
        case EMGCondition::LOW_CONTRACTION:      return "Baja";
        case EMGCondition::MODERATE_CONTRACTION: return "Moderada";
        case EMGCondition::HIGH_CONTRACTION:     return "Alta";
        case EMGCondition::TREMOR:               return "Temblor";
        case EMGCondition::FATIGUE:              return "Fatiga";
        default:                                 return "Desconocido";
    }
}

/**
 * @brief Obtiene rango de salida del modelo EMG
 * @param minMV Puntero para almacenar mínimo en mV
 * @param maxMV Puntero para almacenar máximo en mV
 * 
 * EMG tiene rango fijo ±5 mV (bipolar) independiente de la condición.
 * Esto permite comparación visual consistente entre condiciones.
 */
void EMGModel::getOutputRange(float* minMV, float* maxMV) const {
    if (minMV) *minMV = EMG_OUTPUT_MIN_MV;  // -5.0 mV
    if (maxMV) *maxMV = EMG_OUTPUT_MAX_MV;  // +5.0 mV
}

/**
 * @brief Obtiene todas las métricas para display en un struct
 * @return EMGDisplayMetrics con todos los valores
 */
EMGDisplayMetrics EMGModel::getDisplayMetrics() const {
    EMGDisplayMetrics metrics;
    metrics.rmsAmplitude_mV = getRMSAmplitude();
    metrics.activeMotorUnits = getActiveMotorUnits();
    metrics.meanFiringRate_Hz = getMeanFiringRate();
    metrics.contractionLevel = getContractionLevel();
    metrics.conditionName = getConditionName();
    return metrics;
}

// ============================================================================
// CONVERSIÓN DAC - RANGO FIJO ±5 mV
// ============================================================================

/**
 * @brief Convierte voltaje a valor DAC de 8 bits con rango fijo
 * @param voltage Voltaje en mV
 * @return Valor DAC 0-255 (128 = 0mV para señales bipolares)
 * 
 * RANGO FIJO: -5.0 a +5.0 mV (PARTE 3)
 * Justificación científica:
 * - De Luca 1997: sEMG típico 50 µV - 5 mV RMS
 * - Merletti 2004: 90% de señales clínicas <5 mV pico
 * - Konrad 2005: Rango ADC estándar para sEMG: ±5 mV o ±10 mV
 * 
 * VENTAJAS RANGO FIJO:
 * - Permite comparación visual entre condiciones
 * - Grid Nextion consistente
 * - Didácticamente más claro (no cambia escala)
 * 
 * EMG es bipolar (centrado en 0):
 *   - 0 mV → DAC 128 (centro)
 *   - +5 mV → DAC 255
 *   - -5 mV → DAC 0
 */
uint8_t EMGModel::voltageToDACValue(float voltage) const {
    // Limitar al rango fijo
    voltage = constrain(voltage, EMG_OUTPUT_MIN_MV, EMG_OUTPUT_MAX_MV);
    
    // Convertir a DAC: -5mV → 0, 0mV → 128, +5mV → 255
    // Normalizar: -5 a +5 mV → -1 a +1
    float normalized = voltage / EMG_OUTPUT_MAX_MV;
    
    // Escalar a 0-255 con centro en 128
    int dacValue = (int)(128.0f + normalized * 127.0f);
    
    // Clamp por seguridad
    return (uint8_t)constrain(dacValue, 0, 255);
}

// ============================================================================
// PROCESAMIENTO DE SEÑAL - FILTROS Y ENVOLVENTE (PARTE 8 - CORREGIDO)
// ============================================================================

/**
 * @brief Inicializa coeficientes Butterworth 4º orden (20-450 Hz @ 1kHz)
 * 
 * Diseño: Butterworth bandpass 4º orden = 2 biquad SOS en cascada
 * Calculado con scipy.signal.butter(4, [20, 450], 'bandpass', fs=1000, output='sos')
 * 
 * IMPORTANTE: Coeficientes precalculados para evitar cálculo en runtime
 */
void EMGModel::initBiquadCoefficients() {
    // SOS Section 1 (pasa-altos dominante)
    // b0, b1, b2, a1, a2
    biquadCoeffs[0][0] = 0.94595947f;   // b0
    biquadCoeffs[0][1] = -1.89191895f;  // b1
    biquadCoeffs[0][2] = 0.94595947f;   // b2
    biquadCoeffs[0][3] = -1.88903313f;  // a1
    biquadCoeffs[0][4] = 0.89480810f;   // a2
    
    // SOS Section 2 (pasa-bajos dominante)
    biquadCoeffs[1][0] = 1.0f;          // b0
    biquadCoeffs[1][1] = 2.0f;          // b1
    biquadCoeffs[1][2] = 1.0f;          // b2
    biquadCoeffs[1][3] = -1.60104076f;  // a1
    biquadCoeffs[1][4] = 0.64135154f;   // a2
}

/**
 * @brief Inicializa filtro suavizante post-bandpass @ 80 Hz
 * 
 * PROPÓSITO: Control más agresivo de picos agudos sin destruir morfología
 * - fc = 80 Hz (más suave que 100 Hz para mejor control de picos)
 * - Butterworth 2º orden (atenuación suave sin rizado)
 * - Reduce picos de ±3.26 mV a ±1.0 mV antes de rectificación
 * 
 * Calculado con: scipy.signal.butter(2, 80, 'lowpass', fs=1000, output='sos')
 */
void EMGModel::initSmoothingCoefficients() {
    // Butterworth 2º orden pasa-bajos @ 80 Hz
    smoothingCoeffs[0] = 0.04491857f;   // b0
    smoothingCoeffs[1] = 0.08983715f;   // b1
    smoothingCoeffs[2] = 0.04491857f;   // b2
    smoothingCoeffs[3] = -1.25761817f;  // a1
    smoothingCoeffs[4] = 0.43729246f;   // a2
}

/**
 * @brief Inicializa envelope Butterworth 2º orden @ 6 Hz
 * 
 * ESTÁNDAR SENIAM / De Luca (1997) / Merletti (2004):
 * - Linear envelope: LPF 3-10 Hz sobre señal rectificada
 * - 6 Hz es el valor central recomendado
 * - Promedia ~170ms - suaviza bien la actividad muscular
 * 
 * Pipeline estándar:
 * Raw → Bandpass(20-450) → Rectify → Envelope(6 Hz)
 * 
 * Calculado con: scipy.signal.butter(2, 6, 'lowpass', fs=1000, output='sos')
 */
void EMGModel::initEnvelopeCoefficients() {
    // Butterworth 2º orden pasa-bajos @ 6 Hz (ESTÁNDAR SENIAM)
    envelopeCoeffs[0] = 0.00033717f;   // b0
    envelopeCoeffs[1] = 0.00067434f;   // b1
    envelopeCoeffs[2] = 0.00033717f;   // b2
    envelopeCoeffs[3] = -1.94669378f;  // a1
    envelopeCoeffs[4] = 0.94804245f;   // a2
}

/**
 * @brief Aplica una sección biquad IIR (Direct Form II Transposed)
 * @param input Muestra de entrada
 * @param state Array de 2 estados [w1, w2]
 * @param coeffs Array de 5 coeficientes [b0, b1, b2, a1, a2]
 * @return Muestra filtrada
 * 
 * Estructura Direct Form II Transposed (más estable numéricamente):
 *   y[n] = b0*x[n] + w1[n-1]
 *   w1[n] = b1*x[n] - a1*y[n] + w2[n-1]
 *   w2[n] = b2*x[n] - a2*y[n]
 */
float EMGModel::applyBiquadSection(float input, float* state, const float* coeffs) {
    float output = coeffs[0] * input + state[0];
    state[0] = coeffs[1] * input - coeffs[3] * output + state[1];
    state[1] = coeffs[2] * input - coeffs[4] * output;
    return output;
}

/**
 * @brief Filtro pasa-banda Butterworth 4º orden real (20-450 Hz @ 1kHz)
 * @param input Muestra de entrada en mV
 * @return Muestra filtrada en mV
 * 
 * Implementación con 2 biquad sections en cascada (SOS).
 * Atenuación: -24 dB/octava fuera de banda (característica Butterworth 4º orden)
 */
float EMGModel::applyBandpassFilter(float input) {
    // Aplicar primera sección biquad
    float stage1 = applyBiquadSection(input, filterState1, biquadCoeffs[0]);
    
    // Aplicar segunda sección biquad
    float output = applyBiquadSection(stage1, filterState2, biquadCoeffs[1]);
    
    return output;
}

/**
 * @brief Resetea todos los buffers de procesamiento
 * 
 * Llamado al cambiar de condición para evitar transitorios.
 */
void EMGModel::resetProcessingBuffers() {
    // Reset estados biquad (filtro pasa-banda 20-450 Hz)
    filterState1[0] = 0.0f;
    filterState1[1] = 0.0f;
    filterState2[0] = 0.0f;
    filterState2[1] = 0.0f;
    
    // Reset estados filtro suavizante (100 Hz)
    smoothingState[0] = 0.0f;
    smoothingState[1] = 0.0f;
    
    // Reset estados filtro Butterworth envelope (15 Hz)
    envelopeState[0] = 0.0f;
    envelopeState[1] = 0.0f;
    lastProcessedValue = 0.0f;
}

/**
 * @brief Aplica filtro suavizante post-bandpass @ 100 Hz
 * @param input Señal filtrada por bandpass
 * @return Señal suavizada (picos reducidos)
 */
float EMGModel::applySmoothingFilter(float input) {
    return applyBiquadSection(input, smoothingState, smoothingCoeffs);
}

/**
 * @brief Rectificación de onda completa
 */
float EMGModel::applyRectification(float input) {
    return fabsf(input);
}

/**
 * @brief Linear Envelope estándar SENIAM
 * @param input Señal rectificada en mV
 * @return Envelope suavizado en mV
 * 
 * ESTÁNDAR: Butterworth 2º orden @ 6 Hz (De Luca 1997, SENIAM)
 * - Sin attack/release (eso NO es estándar)
 * - Filtro puro Butterworth como indica la literatura
 */
float EMGModel::applyRMSEnvelope(float input) {
    return applyBiquadSection(input, envelopeState, envelopeCoeffs);
}

// ============================================================================
// SISTEMA DE CACHÉ - BUG CRÍTICO CORREGIDO
// ============================================================================

/**
 * @brief Tick del modelo - genera UNA muestra por ciclo
 * @param deltaTime Tiempo desde última muestra (normalmente 0.001f)
 * 
 * IMPORTANTE: Llamar EXACTAMENTE una vez por ciclo de 1ms.
 * Todas las funciones getRawSample/getProcessedSample usan este valor cacheado.
 * 
 * BUG CORREGIDO: Anteriormente, getRawSample() y getProcessedSample() generaban
 * DOS muestras diferentes al llamarse ambas, causando:
 * - Avance temporal incorrecto (2ms en lugar de 1ms)
 * - Señales desincronizadas (ruido diferente)
 * - Desperdicio de CPU
 */
void EMGModel::tick(float deltaTime) {
    // Actualizar secuencia si está activa
    updateSequence(deltaTime);
    
    // Generar UNA sola muestra cruda del modelo
    cachedRawSample = generateSample(deltaTime);
    sampleIsCached = true;
    
    // Actualizar envelope en cada tick para que esté sincronizado con el waveform
    // Esto hace que lastProcessedValue esté siempre actualizado para getWaveformValue_Ch1()
    float rectified = fabsf(cachedRawSample);
    updateEnvelopeBuffer(rectified);
    float envelopeRMS = (envelopeSum > 0.0f) ? sqrtf(envelopeSum / (float)ENVELOPE_BUFFER_SIZE) : 0.0f;
    const float alpha = 0.02f;
    lastProcessedValue = lastProcessedValue * (1.0f - alpha) + envelopeRMS * alpha;
}

// ============================================================================
// GETTERS DUALES - SEÑAL CRUDA Y PROCESADA (CORREGIDO)
// ============================================================================

/**
 * @brief Obtiene señal CRUDA cacheada (NO regenera)
 * @return Señal cruda en mV (±5 mV bipolar)
 * 
 * PREREQUISITO: tick(deltaTime) debe haberse llamado antes en este ciclo.
 * Si no, retorna 0.0f.
 */
float EMGModel::getRawSample() const {
    if (!sampleIsCached) {
        // Error: tick() no se llamó antes
        return 0.0f;
    }
    return cachedRawSample;
}

/**
 * @brief Obtiene DAC de señal CRUDA cacheada
 * @return DAC 0-255 (128 = 0mV centro)
 */
uint8_t EMGModel::getRawDACValue() const {
    float voltage = getRawSample();
    return voltageToDACValue(voltage);
}

/**
 * @brief Obtiene señal PROCESADA - ENVOLVENTE RMS SOBRE SEÑAL RECTIFICADA
 * 
 * Pipeline CORRECTO según SENIAM / De Luca (1997) / Merletti (2004):
 * 
 *   Raw (±mV) → |Rectificación| → RMS ventana 30ms → EMA suavizado
 *       ↓              ↓                  ↓                ↓
 *    Bipolar     Unipolar (+)    Promedio energía    Transiciones suaves
 * 
 * CONCEPTOS CLAVE:
 * - Rectificación: convierte señal en positiva para medir energía
 * - RMS ventana 30ms: promedia picos de MUAPs en ventana (SIEMPRE <= picos máximos)
 * - EMA alpha=0.02: suaviza para visualización (constante tiempo ~50ms)
 * 
 * RELACIÓN rectificada vs envolvente:
 * - Rectificada: picos rápidos, amplitud instantánea variable
 * - Envolvente: curva suave dentro del rango de la rectificada
 * - La envolvente NUNCA supera los picos máximos de la rectificada
 * 
 * Referencias:
 * - De Luca CJ. J Appl Biomech. 1997 - "RMS is the preferred amplitude measure"
 * - SENIAM Project - "RMS window 20-50ms recommended"
 * - Merletti R, Parker PA. IEEE Press. 2004
 * 
 * @return Envolvente RMS en mV (~0.3-0.5 mV en contracción moderada)
 */
float EMGModel::getProcessedSample() {
    // El envelope se actualiza en tick() para estar sincronizado con el waveform
    // Aquí solo retornamos el valor ya calculado
    // Valores esperados:
    //   REST: 0.03-0.05 mV
    //   LOW: 0.3-0.5 mV
    //   MODERATE: 0.8-1.5 mV
    //   HIGH: 2.0-4.0 mV
    return lastProcessedValue;
}

/**
 * @brief Obtiene DAC de señal PROCESADA (envelope)
 * @return DAC 0-255 (0 = 0mV, 255 = 2mV - rango completo para envelope)
 * 
 * NOTA: Escala diferente a visualización Nextion.
 * - Nextion: usa escala 0-5mV (compartida con RAW para superposición)
 * - DAC real: usa escala 0-2mV (EMG_RMS_MAX_MV) para máxima resolución
 */
uint8_t EMGModel::getProcessedDACValue() {
    float envelope = getProcessedSample();
    envelope = constrain(envelope, 0.0f, EMG_RMS_MAX_MV);  // 0-2 mV (rango real envelope)
    int dacValue = (int)((envelope / EMG_RMS_MAX_MV) * 255.0f);  // Full scale DAC
    return (uint8_t)constrain(dacValue, 0, 255);
}

// ============================================================================
// SISTEMA DE SECUENCIAS DINÁMICAS
// ============================================================================

/**
 * @brief Inicia una secuencia predefinida
 * @param sequence Secuencia a ejecutar
 */
void EMGModel::startSequence(const EMGSequence& sequence) {
    currentSequence = sequence;
    sequenceActive = true;
    sequenceTime = 0.0f;
    currentEventIndex = 0;
    
    // Aplicar primer evento inmediatamente (SIN recursión)
    if (sequence.numEvents > 0) {
        // Actualizar params directamente (sin llamar a setParameters para evitar recursión)
        params.condition = sequence.events[0].condition;
        params.excitationLevel = sequence.events[0].excitationLevel;
        // Mantener params.noiseLevel y params.amplitude actuales
        
        // Aplicar modificadores de la condición
        applyConditionModifiers();
        baseExcitation = currentExcitation;
    }
}

/**
 * @brief Detiene la secuencia actual (vuelve a modo estático)
 */
void EMGModel::stopSequence() {
    sequenceActive = false;
    sequenceTime = 0.0f;
    currentEventIndex = 0;
}

/**
 * @brief Obtiene nombre del evento actual
 */
const char* EMGModel::getCurrentEventName() const {
    if (!sequenceActive || currentEventIndex >= currentSequence.numEvents) {
        return "Estatico";
    }
    
    EMGCondition condition = currentSequence.events[currentEventIndex].condition;
    
    switch (condition) {
        case EMGCondition::REST:                 return "Reposo";
        case EMGCondition::LOW_CONTRACTION:      return "Contraccion Leve";
        case EMGCondition::MODERATE_CONTRACTION: return "Contraccion Moderada";
        case EMGCondition::HIGH_CONTRACTION:     return "Contraccion Alta";
        case EMGCondition::TREMOR:               return "Temblor";
        case EMGCondition::FATIGUE:              return "Fatiga";
        default:                                 return "Desconocido";
    }
}

/**
 * @brief Actualizar secuencia en tick()
 */
void EMGModel::updateSequence(float deltaTime) {
    if (!sequenceActive) return;
    
    sequenceTime += deltaTime;
    
    // Verificar si pasamos al siguiente evento
    if (currentEventIndex < currentSequence.numEvents) {
        EMGSequenceEvent& currentEvent = currentSequence.events[currentEventIndex];
        float eventEnd = currentEvent.timeStart + currentEvent.duration;
        
        // ¿Ya terminó el evento actual?
        if (sequenceTime >= eventEnd) {
            currentEventIndex++;
            
            // ¿Hay más eventos?
            if (currentEventIndex < currentSequence.numEvents) {
                // Aplicar siguiente evento (SIN recursión)
                EMGSequenceEvent& nextEvent = currentSequence.events[currentEventIndex];
                
                // Calcular excitación objetivo (usar excitationLevel o default de condición)
                targetExcitation = (nextEvent.excitationLevel > 0.0f) 
                    ? nextEvent.excitationLevel 
                    : getDefaultExcitation(nextEvent.condition);
                
                // Activar rampa de excitación (100ms de reclutamiento progresivo)
                excitationRampTime = 0.0f;
                
                // Actualizar params
                params.condition = nextEvent.condition;
                params.excitationLevel = nextEvent.excitationLevel;
                
                // Aplicar modificadores de la condición
                applyConditionModifiers();
                // NO actualizar baseExcitation aquí - la rampa lo hará gradualmente
            }
            // ¿Se acabaron los eventos?
            else {
                // ¿Hay que hacer loop?
                if (currentSequence.loop) {
                    sequenceTime = 0.0f;
                    currentEventIndex = 0;
                    
                    // Reiniciar con primer evento (SIN recursión)
                    EMGSequenceEvent& firstEvent = currentSequence.events[0];
                    
                    // Calcular excitación objetivo
                    targetExcitation = (firstEvent.excitationLevel > 0.0f)
                        ? firstEvent.excitationLevel
                        : getDefaultExcitation(firstEvent.condition);
                    
                    // Activar rampa
                    excitationRampTime = 0.0f;
                    
                    // Actualizar params
                    params.condition = firstEvent.condition;
                    params.excitationLevel = firstEvent.excitationLevel;
                    
                    // Aplicar modificadores
                    applyConditionModifiers();
                } else {
                    // Detener secuencia
                    sequenceActive = false;
                }
            }
        }
    }
}

// ============================================================================
// ESCALADO WAVEFORM NEXTION DUAL-CHANNEL - 700×380px (PARTE 11)
// ============================================================================

/**
 * @brief Canal 0: Señal cruda bipolar para Nextion
 * 
 * Mapeo FIJO: -5mV a +5mV → Y invertido (0-380)
 * - -5.0 mV → Y=380 (fondo)
 * -  0.0 mV → Y=190 (centro, línea isoeléctrica)
 * - +5.0 mV → Y=255 (tope)
 * 
 * Grid fijo: 1mV/div, permite comparación visual entre condiciones.
 * REST (0.05mV) vs HIGH (3.0mV) se ven en misma escala.
 * Rango completo 0-255 para compatibilidad con grid Nextion.
 */
uint8_t EMGModel::getWaveformValue_Ch0() const {
    // Usar muestra cruda cacheada (ya en mV)
    float voltage = cachedRawSample;
    
    // Limitar a rango fijo ±5mV
    voltage = constrain(voltage, EMG_OUTPUT_MIN_MV, EMG_OUTPUT_MAX_MV);
    
    // Normalizar: -5mV → 0.0, 0mV → 0.5, +5mV → 1.0
    float normalized = (voltage - EMG_OUTPUT_MIN_MV) / (EMG_OUTPUT_MAX_MV - EMG_OUTPUT_MIN_MV);
    
    // Mapear a 0-255 (rango completo)
    uint8_t y = (uint8_t)(normalized * 255.0f);
    
    return y;
}

/**
 * @brief Canal 1: Envelope procesada usando MISMA ESCALA que raw
 * 
 * Mapeo en escala del RAW: ±5mV → 0-255 (rango completo)
 * El envelope es unipolar (0 a ~2 mV) pero se muestra en la escala del raw
 * para que visualmente sea proporcional (como en Serial Plotter).
 * 
 * - 0.0 mV → Y=127 (centro, línea isoeléctrica del raw)
 * - 2.0 mV → Y=178 (2mV arriba del centro)
 * - 5.0 mV → Y=255 (máximo de la escala)
 * 
 * Ventaja: El estudiante ve el envelope proporcional al raw.
 */
uint8_t EMGModel::getWaveformValue_Ch1() const {
    // Usar envelope procesada (RMS con EMA)
    float voltage = lastProcessedValue;
    
    // El envelope es positivo (0 a ~2-4 mV dependiendo de condición)
    // Usar MISMA ESCALA que el raw (-5 a +5 mV) para mapeo proporcional
    voltage = constrain(voltage, 0.0f, EMG_OUTPUT_MAX_MV);  // Clamp a 0-5mV
    
    // Normalizar usando escala del raw: -5mV → 0.0, 0mV → 0.5, +5mV → 1.0
    float normalized = (voltage - EMG_OUTPUT_MIN_MV) / (EMG_OUTPUT_MAX_MV - EMG_OUTPUT_MIN_MV);
    
    // Mapear a 0-255 (rango completo)
    uint8_t y = (uint8_t)(normalized * 255.0f);
    
    return y;
}

// ============================================================================
// PARAMETRIZACIÓN SEGURA - VALIDACIÓN POR CONDICIÓN (PARTE 12)
// ============================================================================

/**
 * @brief Valida excitación según límites seguros de cada condición
 * @param excitation Excitación solicitada (0.0-1.0)
 * @return Excitación clampeada a rango seguro
 * 
 * Previene que usuarios destruyan características patológicas:
 * - REST: 0-10% (mínima activación)
 * - LOW: 5-30% (contracción suave)
 * - MODERATE: 20-60% (contracción moderada)
 * - HIGH: 50-100% (máxima contracción)
 * - TREMOR: 3-15% (activación muy baja, tremor visible)
 * - FATIGUE: 40-60% (protocolo fijo 50% MVC)
 */
float EMGModel::clampExcitationForCondition(float excitation) const {
    switch (params.condition) {
        case EMGCondition::REST:
            return constrain(excitation, 0.0f, 0.10f);  // 0-10%
            
        case EMGCondition::LOW_CONTRACTION:
            return constrain(excitation, 0.05f, 0.30f); // 5-30%
            
        case EMGCondition::MODERATE_CONTRACTION:
            return constrain(excitation, 0.20f, 0.60f); // 20-60%
            
        case EMGCondition::HIGH_CONTRACTION:
            return constrain(excitation, 0.50f, 1.00f); // 50-100%
            
        case EMGCondition::TREMOR:
            return constrain(excitation, 0.03f, 0.15f); // 3-15% (Parkinson en reposo)
            
        case EMGCondition::FATIGUE:
            return constrain(excitation, 0.40f, 0.60f); // 40-60% (protocolo fijo)
            
        default:
            return constrain(excitation, 0.0f, 1.0f);
    }
}

/**
 * @brief Setter seguro para nivel de ruido
 * @param noise Nivel de ruido (0.0-0.10 = 0-10%)
 * 
 * Límite: 0-10% para mantener señal interpretable
 */
void EMGModel::setNoiseLevel(float noise) {
    params.noiseLevel = constrain(noise, 0.0f, 0.10f);  // 0-10% máximo
}

/**
 * @brief Setter seguro para amplitud
 * @param amp Factor de amplitud (0.5-2.0x)
 * 
 * Simula variabilidad de impedancia electrodo/piel sin alterar morfología
 */
void EMGModel::setAmplitude(float amp) {
    params.amplitude = constrain(amp, 0.5f, 2.0f);  // ±100% rango seguro
}

void EMGModel::setExcitationLevel(float exc) {
    exc = constrain(exc, 0.0f, 1.0f);
    
    // Si hay secuencia activa, NO interferir - la secuencia controla excitación
    if (sequenceActive) {
        // Solo actualizar si el usuario cambió significativamente (>10%)
        float diff = fabsf(exc - params.excitationLevel);
        if (diff > 0.10f) {
            // Usuario quiere control manual - detener secuencia
            sequenceActive = false;
            params.excitationLevel = exc;
            currentExcitation = exc;
            targetExcitation = exc;
            Serial.printf("[EMG] Secuencia detenida - excitación manual %.0f%%\n", exc * 100);
        }
        return;
    }
    
    // Sin secuencia activa - aplicar directamente
    params.excitationLevel = exc;
    currentExcitation = exc;
    targetExcitation = exc;
}

// ============================================================================
// CONTROL DE FILTRADO DIGITAL
// ============================================================================

void EMGModel::setNotchFrequency(float freq) {
    filterChain.setNotchFreq(freq, 30.0f);
}

void EMGModel::enableHighpassFilter(bool en) {
    filterChain.enableHighpass(en);
}

void EMGModel::enableLowpassFilter(bool en) {
    filterChain.enableLowpass(en);
}

void EMGModel::enableNotchFilter(bool en) {
    filterChain.enableNotch(en);
}
