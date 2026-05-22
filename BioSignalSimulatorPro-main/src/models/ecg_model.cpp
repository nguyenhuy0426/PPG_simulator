/**
 * @file ecg_model.cpp
 * @brief Implementación del modelo ECGSYN (McSharry, Clifford et al. 2003)
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Implementación fiel del modelo ECGSYN de MATLAB en C++ para ESP32.
 * 
 * REFERENCIA:
 * McSharry PE, Clifford GD, Tarassenko L, Smith LA.
 * "A dynamical model for generating synthetic electrocardiogram signals."
 * IEEE Trans Biomed Eng. 2003;50(3):289-294.
 * 
 * ECUACIONES DEL MODELO:
 * dx/dt = α·x - ω·y
 * dy/dt = α·y + ω·x
 * dz/dt = -Σ(ai·Δθi·exp(-Δθi²/2bi²)) - (z - z0)
 * 
 * Donde:
 * - α = 1 - √(x² + y²) : atracción al círculo unitario
 * - ω = 2π/RR : velocidad angular
 * - θ = atan2(y, x) : ángulo actual
 * - Δθi = θ - θi : distancia angular a cada onda
 * - z0 = 0 : baseline de equilibrio
 */

#include "models/ecg_model.h"
#include "config.h"
#include <math.h>
#include <stdlib.h>

#ifdef ESP32
#include <esp_random.h>
#endif

// ============================================================================
// PARÁMETROS DEFAULT DEL MODELO MCSHARRY (del MATLAB original)
// ============================================================================
// Orden de extrema: [P, Q, R, S, T]
static const float DEFAULT_TI_DEG[MCSHARRY_WAVES] = {-70.0f, -15.0f, 0.0f, 15.0f, 100.0f};
static const float DEFAULT_AI[MCSHARRY_WAVES] = {1.15f, -5.0f, 30.0f, -7.5f, 0.75f};
static const float DEFAULT_BI[MCSHARRY_WAVES] = {0.25f, 0.1f, 0.1f, 0.1f, 0.4f};

// Valor inicial de z (del MATLAB: x0 = [1, 0, 0.04])
static const float Z0_INITIAL = 0.04f;
static const float Z0_EQUILIBRIUM = 0.0f;  // Baseline de equilibrio

// ============================================================================
// CONSTRUCTOR
// ============================================================================
ECGModel::ECGModel() {
    // Inicializar punteros a NULL
    rrProcess = nullptr;
    
    // Valores por defecto
    hrMean = 60.0f;
    hrStd = 1.0f;
    lfhfRatio = 0.5f;
    noiseLevel = 0.0f;
    
    currentCondition = ECGCondition::NORMAL;
    
    // Reset inicializa todo
    reset();
}

// ============================================================================
// DESTRUCTOR
// ============================================================================
ECGModel::~ECGModel() {
    if (rrProcess != nullptr) {
        free(rrProcess);
        rrProcess = nullptr;
    }
    // calibrationRPeaks es array estático, no requiere free
}

// ============================================================================
// RESET - Inicializa el modelo al estado inicial
// ============================================================================
void ECGModel::reset() {
    // Estado inicial del sistema dinámico (idéntico al MATLAB)
    // x0 = [1, 0, 0.04]
    state.x = 1.0f;
    state.y = 0.0f;
    state.z = Z0_INITIAL;
    
    // Variables de control
    lastTheta = 0.0f;
    beatCount = 0;
    sampleCount = 0;
    
    // Inicializar parámetros de onda PQRST
    initializeWaveParams();
    
    // Aplicar corrección hrfact según HR medio
    applyHRFactCorrection();
    
    // Generar primer RR
    currentRR = 60.0f / hrMean;  // RR = 60/HR en segundos
    
    // Calibración por picos R
    isCalibrated = false;
    physiologicalGain = 1.0f;  // G = R_objetivo / R_model
    rModelValue = 0.0f;        // Promedio de picos R crudos
    baselineZ = Z0_EQUILIBRIUM; // Línea isoeléctrica estimada
    calibrationPeakCount = 0;
    calibrationBeatCount = 0;
    calibrationCycleZMax = -1000.0f;
    calibrationCycleZMin = 1000.0f;
    
    // Inicializar buffer de picos R
    for (int i = 0; i < MAX_CALIBRATION_PEAKS; i++) {
        calibrationRPeaks[i] = 0.0f;
    }
    
    // Mediciones del ciclo actual
    currentCycleZMax = -1000.0f;
    currentCycleZMin = 1000.0f;
    currentCycleTime = 0.0f;
    currentCycleSamples = 0;
    
    // Inicializar buffer de muestras del ciclo
    cycleSamples.reset();
    
    // Métricas clínicas iniciales (valores típicos)
    measuredRR_ms = 1000.0f;  // 60 BPM
    measuredPR_ms = 160.0f;
    measuredQRS_ms = 80.0f;
    measuredQT_ms = 400.0f;
    measuredQTc_ms = 400.0f;
    measuredP_mV = 0.15f;
    measuredQ_mV = -0.1f;
    measuredR_mV = 1.0f;
    measuredS_mV = -0.2f;
    measuredT_mV = 0.3f;
    measuredST_mV = 0.0f;
    lastMeasuredST_mV = 0.0f;
    currentBaseline_mV = 0.0f;
    stOffset_mV = 0.0f;  // Sin desplazamiento ST por defecto
    
    // Generador aleatorio
    gaussHasSpare = false;
    gaussSpare = 0.0f;
    
    // Ganancia waveform (default 100%)
    waveformGain = 1.0f;
    
    // Inicializar filtrado digital (deshabilitado por defecto)
    filterChain.configureForECG(ECG_SFECG, 60.0f);  // 500 Hz, notch 60 Hz
    filterChain.reset();
    filteringEnabled = false;  // Deshabilitado - usuario activa si necesita
    
    // Liberar proceso RR anterior
    if (rrProcess != nullptr) {
        free(rrProcess);
        rrProcess = nullptr;
    }
    rrProcessLength = 0;
    rrProcessIndex = 0;
}

// ============================================================================
// INICIALIZAR PARÁMETROS DE ONDA (ti, ai, bi)
// ============================================================================
void ECGModel::initializeWaveParams() {
    // Convertir ángulos de grados a radianes
    for (int i = 0; i < MCSHARRY_WAVES; i++) {
        baseParams.ti[i] = DEFAULT_TI_DEG[i] * PI / 180.0f;
        baseParams.ai[i] = DEFAULT_AI[i];
        baseParams.bi[i] = DEFAULT_BI[i];
        
        // Copiar a parámetros actuales
        waveParams.ti[i] = baseParams.ti[i];
        waveParams.ai[i] = baseParams.ai[i];
        waveParams.bi[i] = baseParams.bi[i];
    }
    
    // Sincronizar ventanas angulares con los parámetros
    initializeAngularWindows();
}

// ============================================================================
// CORRECCIÓN HRFACT (del MATLAB original)
// ============================================================================
/**
 * Ajusta los parámetros bi y ti según la frecuencia cardíaca.
 * 
 * Del MATLAB:
 *   hrfact = sqrt(hrmean/60);
 *   hrfact2 = sqrt(hrfact);
 *   bi = hrfact * bi;
 *   ti = [hrfact2 hrfact 1 hrfact hrfact2] .* ti;
 */
void ECGModel::applyHRFactCorrection() {
    float hrfact = sqrtf(hrMean / 60.0f);
    float hrfact2 = sqrtf(hrfact);
    
    // Factores de corrección para cada onda [P, Q, R, S, T]
    float tiFactor[MCSHARRY_WAVES] = {hrfact2, hrfact, 1.0f, hrfact, hrfact2};
    
    for (int i = 0; i < MCSHARRY_WAVES; i++) {
        waveParams.bi[i] = baseParams.bi[i] * hrfact;
        waveParams.ti[i] = baseParams.ti[i] * tiFactor[i];
    }
    
    // Sincronizar ventanas angulares con los parámetros ajustados
    initializeAngularWindows();
}

// ============================================================================
// SET PENDING PARAMETERS (para aplicación diferida - compatibilidad)
// ============================================================================
void ECGModel::setPendingParameters(const ECGParameters& newParams) {
    setParameters(newParams);
}

// ============================================================================
// SET AMPLITUDE (parámetro Tipo A - inmediato)
// ============================================================================
void ECGModel::setAmplitude(float amp) {
    if (params.qrsAmplitude > 0.01f) {
        float factor = amp / params.qrsAmplitude;
        params.qrsAmplitude = amp;
        for (int i = 0; i < MCSHARRY_WAVES; i++) {
            waveParams.ai[i] = baseParams.ai[i] * factor;
        }
        // Reiniciar calibración
        isCalibrated = false;
        calibrationPeakCount = 0;
        calibrationBeatCount = 0;
    }
}

// ============================================================================
// SET PARAMETERS
// ============================================================================
void ECGModel::setParameters(const ECGParameters& newParams) {
    params = newParams;
    currentCondition = newParams.condition;
    
    // Aplicar morfología según condición
    switch (currentCondition) {
        case ECGCondition::NORMAL:
            setNormalMorphology();
            break;
        case ECGCondition::TACHYCARDIA:
            setTachycardiaMorphology();
            break;
        case ECGCondition::BRADYCARDIA:
            setBradycardiaMorphology();
            break;
        case ECGCondition::ATRIAL_FIBRILLATION:
            setAFibMorphology();
            break;
        case ECGCondition::VENTRICULAR_FIBRILLATION:
            setVFibMorphology();
            break;
        case ECGCondition::AV_BLOCK_1:
            setAVBlock1Morphology();
            break;
        case ECGCondition::ST_ELEVATION:
            setSTElevationMorphology();
            break;
        case ECGCondition::ST_DEPRESSION:
            setSTDepressionMorphology();
            break;
        default:
            setNormalMorphology();
            break;
    }
    
    // Si el usuario especifica HR, usarlo
    if (newParams.heartRate > 0) {
        hrMean = newParams.heartRate;
    }
    
    // Aplicar nivel de ruido
    noiseLevel = newParams.noiseLevel;
    
    // ✅ CRÍTICO: Solo recalcular hrfact si NO es AVB1
    //    (AVB1 ya lo hizo internamente con orden correcto)
    if (currentCondition != ECGCondition::AV_BLOCK_1) {
        applyHRFactCorrection();
    }
    
    // Recalcular RR
    currentRR = 60.0f / hrMean;
    
    // Reiniciar calibración si cambió la condición (excepto VFib que no usa McSharry)
    if (currentCondition != ECGCondition::VENTRICULAR_FIBRILLATION) {
        isCalibrated = false;
        calibrationPeakCount = 0;
        calibrationBeatCount = 0;
        calibrationCycleZMax = -1000.0f;
        calibrationCycleZMin = 1000.0f;
    }
    
    // =========================================================================
    // RESETEAR MÉTRICAS AL CAMBIAR CONDICIÓN
    // =========================================================================
    // Evita mostrar métricas "fantasma" de la condición anterior
    resetMetricsForCondition();
}

// ============================================================================
// MORFOLOGÍA POR CONDICIÓN
// ============================================================================

void ECGModel::setNormalMorphology() {
    hrMean = 75.0f;
    hrStd = 1.0f;
    lfhfRatio = 0.5f;
    initializeWaveParams();
    stOffset_mV = 0.0f;  // Sin desplazamiento ST
}

void ECGModel::setTachycardiaMorphology() {
    hrMean = 120.0f;
    hrStd = 2.0f;
    lfhfRatio = 0.5f;
    initializeWaveParams();
    stOffset_mV = 0.0f;  // Sin desplazamiento ST
}

void ECGModel::setBradycardiaMorphology() {
    hrMean = 50.0f;
    hrStd = 1.0f;
    lfhfRatio = 0.5f;
    initializeWaveParams();
    stOffset_mV = 0.0f;  // Sin desplazamiento ST
}

void ECGModel::setAFibMorphology() {
    hrMean = 100.0f;
    hrStd = 8.0f;  // Variabilidad RR reducida (8%) para evitar deriva de baseline
    lfhfRatio = 0.5f;
    initializeWaveParams();
    
    // ✅ Solo modificar waveParams (NO baseParams para no contaminar otras condiciones)
    // Sin onda P en AFib (ausencia de despolarización auricular organizada)
    waveParams.ai[0] = 0.0f;
    // ❌ ELIMINADO: baseParams.ai[0] = 0.0f;  ← Esto contaminaba otras condiciones
    
    // Reducir ligeramente amplitud de ondas para compensar ausencia de P
    // Esto estabiliza la señal evitando saltos bruscos
    for (int i = 1; i < MCSHARRY_WAVES; i++) {
        waveParams.ai[i] = baseParams.ai[i] * 0.95f;
    }
    stOffset_mV = 0.0f;  // Sin desplazamiento ST
    initializeAngularWindows();
}

void ECGModel::setVFibMorphology() {
    // VFib usa modelo espectral alternativo (no McSharry)
    // Estos parámetros son fallback si se usa McSharry por error
    hrMean = 300.0f;
    hrStd = 50.0f;
    lfhfRatio = 0.5f;
    initializeWaveParams();
    
    // Inicializar modelo VFIB espectral caótico
    initVFibModel();
    
    // Generar valor inicial para evitar lectura de 0 antes del primer sample
    float initialVfib = generateVFibSample(0.001f);
    state.z = initialVfib;  // Para getCurrentValueMV()
    vfibState.lastValue = initialVfib;  // Ya normalizado, no necesita escalado
    
    // VFib no necesita calibración McSharry - marcar como listo
    isCalibrated = true;
    currentBaseline_mV = 0.0f;
    stOffset_mV = 0.0f;  // Sin desplazamiento ST
}

void ECGModel::setAVBlock1Morphology() {
    hrMean = 70.0f;
    hrStd = 1.0f;
    lfhfRatio = 0.5f;
    
    // ✅ 1. Inicializar limpio desde DEFAULT
    initializeWaveParams();
    
    // ✅ 2. Aplicar hrfact PRIMERO (esto modifica waveParams.ti[] y .bi[])
    applyHRFactCorrection();
    
    // =========================================================================
    // AVB1: PR prolongado > 200 ms (criterio diagnóstico)
    // =========================================================================
    // ✅ 3. AHORA aplicar prolongación PR sobre waveParams YA ajustados
    //    (NO tocar baseParams, solo waveParams)
    //
    // A 70 BPM (RR = 857 ms), para PR = 250 ms necesitamos:
    // delta_angular_total = (250 / 857) × 2π = 1.83 rad
    float prProlongation = 1.1f;  // ~63° adicionales para PR > 200ms
    
    for (int i = 1; i < MCSHARRY_WAVES; i++) {  // Solo Q, R, S, T (no P)
        waveParams.ti[i] += prProlongation;
    }
    
    stOffset_mV = 0.0f;  // Sin desplazamiento ST
    
    // ✅ 4. Sincronizar ventanas angulares con ti modificados
    initializeAngularWindows();
}

void ECGModel::setSTElevationMorphology() {
    hrMean = 80.0f;
    hrStd = 2.0f;
    lfhfRatio = 0.5f;
    initializeWaveParams();
    
    // STEMI: Morfología con ST elevado
    // 1. Onda S menos profunda (se fusiona con ST elevado)
    waveParams.ai[3] = baseParams.ai[3] * 0.4f;  // S reducida a 40% (menos profunda)
    
    // 2. Onda T más alta (hiperaguda en STEMI)
    waveParams.ai[4] = baseParams.ai[4] * 1.8f;  // T aumentada (hiperaguda)
    waveParams.bi[4] = baseParams.bi[4] * 1.2f;  // T más ancha
    
    // 3. Desplazamiento ST vertical adicional
    stOffset_mV = 0.30f;
    
    initializeAngularWindows();
}

void ECGModel::setSTDepressionMorphology() {
    hrMean = 90.0f;
    hrStd = 2.0f;
    lfhfRatio = 0.5f;
    initializeWaveParams();
    
    // Isquemia: Morfología con ST deprimido
    // 1. Onda S más profunda (acentuada en isquemia)
    waveParams.ai[3] = baseParams.ai[3] * 1.4f;  // S aumentada (más profunda)
    
    // 2. Onda T reducida o invertida
    waveParams.ai[4] = baseParams.ai[4] * 0.5f;  // T reducida (puede invertirse con offset)
    
    // 3. Desplazamiento ST vertical (depresión)
    stOffset_mV = -0.20f;
    
    initializeAngularWindows();
}

// ============================================================================
// CÁLCULO DE DERIVADAS (ecuaciones del modelo McSharry)
// ============================================================================
/**
 * Calcula las derivadas del sistema dinámico:
 * dx/dt = α·x - ω·y
 * dy/dt = α·y + ω·x  
 * dz/dt = -Σ(ai·Δθi·exp(-Δθi²/2bi²)) - (z - z0)
 */
void ECGModel::computeDerivatives(const ECGDynamicState& s, ECGDynamicState& ds, float omega) {
    // Factor de atracción al círculo unitario
    float alpha = 1.0f - sqrtf(s.x * s.x + s.y * s.y);
    
    // Derivadas de posición (movimiento circular)
    ds.x = alpha * s.x - omega * s.y;
    ds.y = alpha * s.y + omega * s.x;
    
    // Ángulo actual en el ciclo cardíaco
    float theta = atan2f(s.y, s.x);
    
    // Derivada de z (forma de onda ECG)
    float zDot = 0.0f;
    
    for (int i = 0; i < MCSHARRY_WAVES; i++) {
        // Distancia angular a esta onda (normalizar a [-π, π])
        float dTheta = theta - waveParams.ti[i];
        while (dTheta > PI) dTheta -= 2.0f * PI;
        while (dTheta < -PI) dTheta += 2.0f * PI;
        
        // Contribución gaussiana de esta onda
        float bi = waveParams.bi[i];
        float biSq = bi * bi;
        zDot -= waveParams.ai[i] * dTheta * expf(-0.5f * dTheta * dTheta / biSq);
    }
    
    // Restauración a línea base (z0 = 0)
    zDot -= (s.z - Z0_EQUILIBRIUM);
    
    ds.z = zDot;
}

// ============================================================================
// INTEGRACIÓN RUNGE-KUTTA 4
// ============================================================================
void ECGModel::rungeKutta4Step(float dt, float omega) {
    // k1
    computeDerivatives(state, k1, omega);
    
    // k2
    temp.x = state.x + 0.5f * dt * k1.x;
    temp.y = state.y + 0.5f * dt * k1.y;
    temp.z = state.z + 0.5f * dt * k1.z;
    computeDerivatives(temp, k2, omega);
    
    // k3
    temp.x = state.x + 0.5f * dt * k2.x;
    temp.y = state.y + 0.5f * dt * k2.y;
    temp.z = state.z + 0.5f * dt * k2.z;
    computeDerivatives(temp, k3, omega);
    
    // k4
    temp.x = state.x + dt * k3.x;
    temp.y = state.y + dt * k3.y;
    temp.z = state.z + dt * k3.z;
    computeDerivatives(temp, k4, omega);
    
    // Actualización final (promedio ponderado)
    state.x += dt * (k1.x + 2.0f * k2.x + 2.0f * k3.x + k4.x) / 6.0f;
    state.y += dt * (k1.y + 2.0f * k2.y + 2.0f * k3.y + k4.y) / 6.0f;
    state.z += dt * (k1.z + 2.0f * k2.z + 2.0f * k3.z + k4.z) / 6.0f;
}

// ============================================================================
// DETECCIÓN DE NUEVO LATIDO
// ============================================================================
void ECGModel::detectNewBeat() {
    float theta = atan2f(state.y, state.x);
    
    // Detectar cruce por cero (θ pasa de negativo a positivo)
    if (lastTheta < 0 && theta >= 0) {
        beatCount++;
        
        // =====================================================================
        // FASE DE CALIBRACIÓN: Almacenar picos R crudos
        // =====================================================================
        if (!isCalibrated) {
            // Guardar pico R crudo del ciclo que acaba de terminar
            if (calibrationCycleZMax > -500.0f && calibrationPeakCount < MAX_CALIBRATION_PEAKS) {
                // Pico R = máximo Z menos baseline estimada
                float rPeakRaw = calibrationCycleZMax - baselineZ;
                calibrationRPeaks[calibrationPeakCount++] = rPeakRaw;
            }
            
            calibrationBeatCount++;
            
            // Intentar calibrar si tenemos suficientes picos
            if (calibrationPeakCount >= ECG_CALIBRATION_BEATS) {
                performCalibration();
            }
            
            // Reset tracking de calibración para nuevo ciclo
            calibrationCycleZMax = -1000.0f;
            calibrationCycleZMin = 1000.0f;
        }
        
        // =====================================================================
        // FASE ACTIVA: Medir métricas del ciclo completado por ventanas angulares
        // =====================================================================
        if (isCalibrated && cycleSamples.count > 10) {
            
            // =================================================================
            // 0. BASELINE - Medir primero la línea isoeléctrica
            // =================================================================
            
            // Baseline desde segmento TP (fin de T → inicio de P)
            float TP_start = windows.T_center + windows.T_width * 0.6f;
            float TP_end   = windows.P_center - windows.P_width;
            
            // Ajustar cruce de ciclo
            if (TP_end < TP_start) {
                TP_end += 2.0f * PI;
            }
            
            // Baseline real (línea isoeléctrica) del ciclo actual
            // NOTA: cycleSamples YA tiene corrección de baseline aplicada en generateSample()
            // Por lo tanto, esta medición debería dar ~0, pero la guardamos para
            // actualizar la corrección del próximo ciclo
            float baseline_mV = averageInWindow(TP_start, TP_end);
            
            // Actualizar baseline con filtro EMA y límite estricto (±0.05mV max)
            // Esto evita deriva y mantiene línea isoeléctrica estable
            float correction = baseline_mV * 0.3f;  // Filtro EMA suave (30%)
            correction = constrain(correction, -0.05f, 0.05f);  // Límite estricto
            currentBaseline_mV += correction;
            
            // =================================================================
            // 1. AMPLITUDES (mV) - Medidas DIRECTAS (cycleSamples ya corregido)
            // =================================================================
            // IMPORTANTE: NO restar baseline_mV porque cycleSamples ya está
            // corregido por baseline en generateSample(). Los picos medidos
            // aquí deben coincidir con min/max de la señal de salida.
            
            // P: Máximo en ventana P (despolarización auricular)
            measuredP_mV = findPeakInWindow(windows.P_center, windows.P_width, true);
            
            // Q: Mínimo en ventana Q (inicio QRS) - debe ser < 25% de R
            measuredQ_mV = findPeakInWindow(windows.Q_center, windows.Q_width, false);
            
            // R: Máximo en ventana R (pico QRS)
            measuredR_mV = findPeakInWindow(windows.R_center, windows.R_width, true);
            
            // S: Mínimo en ventana S (final QRS)
            measuredS_mV = findPeakInWindow(windows.S_center, windows.S_width, false);
            
            // T: Máximo en ventana T (repolarización ventricular)
            measuredT_mV = findPeakInWindow(windows.T_center, windows.T_width, true);
            
            // =================================================================
            // 2. SEGMENTO ST - Desviación respecto a baseline
            // =================================================================
            
            float ST_start = windows.S_center + windows.S_width * 0.6f;
            float ST_end   = windows.T_center - windows.T_width * 0.6f;
            
            if (normalizeAngle(ST_end - ST_start) > 0) {
                // Medir ST crudo (ya con corrección de baseline aplicada)
                float stRaw = averageInWindow(ST_start, ST_end);
                
                // ✅ FILTRO DE SUPRESIÓN DE DERIVA
                // Umbral clínico: ST < ±0.05 mV es normal (AHA/ACC Guidelines)
                bool isNonSTCondition = (currentCondition == ECGCondition::NORMAL ||
                                         currentCondition == ECGCondition::TACHYCARDIA ||
                                         currentCondition == ECGCondition::BRADYCARDIA ||
                                         currentCondition == ECGCondition::ATRIAL_FIBRILLATION ||
                                         currentCondition == ECGCondition::AV_BLOCK_1);
                
                if (isNonSTCondition && fabsf(stRaw) < 0.05f) {
                    // Deriva residual menor a umbral clínico → forzar a 0
                    measuredST_mV = 0.0f;
                } else {
                    // ST patológico real o desviación significativa
                    measuredST_mV = stRaw;
                }
            } else {
                measuredST_mV = lastMeasuredST_mV;
            }
            
            lastMeasuredST_mV = measuredST_mV;
            
            // =================================================================
            // 2. INTERVALOS TEMPORALES (ms) - Conversión angular → tiempo
            // =================================================================
            
            // RR: Usar el RR del modelo (currentRR en segundos)
            // NO usar currentCycleTime porque está afectado por SPEED_MULTIPLIER
            // currentRR representa el RR nominal fisiológico del paciente
            measuredRR_ms = currentRR * 1000.0f;
            
            // Encontrar ángulos donde ocurren los picos Q, S y T
            float theta_Q_peak = findAngleAtPeak(windows.Q_center, windows.Q_width, false);
            float theta_S_peak = findAngleAtPeak(windows.S_center, windows.S_width, false);
            float theta_T_peak = findAngleAtPeak(windows.T_center, windows.T_width, true);
            
            // QRS: Desde pico Q hasta pico S (duración del complejo QRS)
            float delta_QRS = theta_S_peak - theta_Q_peak;
            if (delta_QRS < 0) delta_QRS += 2.0f * PI;
            measuredQRS_ms = (delta_QRS / (2.0f * PI)) * measuredRR_ms;
            
            // QT: Desde INICIO de Q (onset) hasta FIN de T (offset)
            // Usar factor 0.6 (≈1.5σ) en lugar de 1.0 (2.5σ) para onset/offset clínicos
            // 2.5σ cubre 99% de Gaussian pero extiende más allá del punto clínico
            // 1.5σ cubre ~87% y corresponde mejor al inicio/fin clínico de las ondas
            float theta_Q_onset = windows.Q_center - windows.Q_width * 0.6f;
            float theta_T_offset = windows.T_center + windows.T_width * 0.6f;
            
            float delta_QT = theta_T_offset - theta_Q_onset;
            if (delta_QT < 0) delta_QT += 2.0f * PI;
            measuredQT_ms = (delta_QT / (2.0f * PI)) * measuredRR_ms;
            
            // QTc: QT / √(RR) donde RR en segundos (fórmula de Bazett)
            float rrSeconds = measuredRR_ms / 1000.0f;
            if (rrSeconds > 0.3f) {
                measuredQTc_ms = measuredQT_ms / sqrtf(rrSeconds);
            } else {
                measuredQTc_ms = measuredQT_ms;
            }
            
            // =================================================================
            // PR: Intervalo desde pico P hasta inicio de QRS (pico Q)
            // =================================================================
            // En AFib (ai[0]=0), no hay onda P → PR no medible
            if (waveParams.ai[0] != 0.0f) {
                float theta_P = findAngleAtPeak(windows.P_center, windows.P_width, true);
                
                // Calcular distancia angular P→Q (siempre positiva, P viene antes que Q)
                float delta_PR = normalizeAngle(theta_Q_peak - theta_P);
                if (delta_PR < 0) delta_PR += 2.0f * PI;
                
                // Convertir a milisegundos
                measuredPR_ms = (delta_PR / (2.0f * PI)) * measuredRR_ms;
                
                // Validar rango fisiológico (120-220 ms típico, hasta 300 ms en bloqueos)
                if (measuredPR_ms < 100.0f || measuredPR_ms > 400.0f) {
                    measuredPR_ms = 160.0f;  // Fallback a valor normal si es absurdo
                }
            } else {
                // AFib: Sin onda P, PR no aplicable
                measuredPR_ms = 0.0f;
                measuredP_mV = 0.0f;
            }
        }
        
        // =================================================================
        // RESET para nuevo ciclo
        // =================================================================
        cycleSamples.reset();
        currentCycleZMax = -1000.0f;
        currentCycleZMin = 1000.0f;
        currentCycleTime = 0.0f;
        currentCycleSamples = 0;
        
        // Generar nuevo RR con variabilidad
        currentRR = generateNextRR();
    }
    
    lastTheta = theta;
}

// ============================================================================
// GENERACIÓN DE PRÓXIMO RR (con variabilidad HRV)
// ============================================================================
float ECGModel::generateNextRR() {
    // RR base en segundos
    float rrMean = 60.0f / hrMean;
    float rrStd = (hrStd / hrMean) * rrMean;
    
    // Variabilidad gaussiana
    float rr = rrMean + gaussianRandom(0.0f, rrStd);
    
    // Limitar a rango fisiológico
    float minRR = 60.0f / 200.0f;  // 200 BPM máximo
    float maxRR = 60.0f / 30.0f;   // 30 BPM mínimo
    
    return fmaxf(minRR, fminf(maxRR, rr));
}

// ============================================================================
// CALIBRACIÓN POR PICOS R (¡NO min-max!)
// ============================================================================
/**
 * Calibración fisiológica:
 * 1. Durante calibración se detectan picos R crudos
 * 2. Se calcula R_model = promedio de picos R
 * 3. Se calcula G = R_objetivo / R_model
 * 4. El escalado es simplemente: z_mV = G * (z - baseline)
 */
void ECGModel::performCalibration() {
    if (calibrationPeakCount < ECG_CALIBRATION_BEATS) {
        return;  // No hay suficientes picos R
    }
    
    // Calcular R_model como promedio de picos R crudos detectados
    float sum = 0.0f;
    for (int i = 0; i < calibrationPeakCount; i++) {
        sum += calibrationRPeaks[i];
    }
    rModelValue = sum / (float)calibrationPeakCount;
    
    // Evitar división por cero
    if (rModelValue < 0.001f) {
        rModelValue = 0.5f;  // Valor por defecto si algo sale mal
    }
    
    // Calcular ganancia fisiológica: G = R_objetivo / R_model
    physiologicalGain = ECG_R_TARGET_MV / rModelValue;
    
    // Validar que la ganancia es razonable (evitar valores extremos)
    if (physiologicalGain < 0.1f) physiologicalGain = 0.1f;
    if (physiologicalGain > 100.0f) physiologicalGain = 100.0f;
    
    isCalibrated = true;
    
    // Las amplitudes se medirán dinámicamente en detectNewBeat()
    // NO se hardcodean aquí
}

/**
 * Actualiza el tracking durante calibración
 * Solo rastrea max/min del ciclo actual, NO almacena en buffer
 */
void ECGModel::updateCalibrationBuffer(float zValue) {
    // Durante calibración, solo rastrear max/min del ciclo
    if (!isCalibrated) {
        if (zValue > calibrationCycleZMax) calibrationCycleZMax = zValue;
        if (zValue < calibrationCycleZMin) calibrationCycleZMin = zValue;
        
        // Actualizar estimación de baseline (usar valor de equilibrio)
        // La baseline se estabiliza cerca de Z0_EQUILIBRIUM
        baselineZ = Z0_EQUILIBRIUM;
    }
}

// ============================================================================
// ESCALADO A mV (lineal simple por ganancia G)
// ============================================================================
/**
 * Escalado fisiológico simple:
 * z_mV = G * (zRaw - baseline)
 * 
 * Donde:
 * - G = R_objetivo / R_model (calculado durante calibración)
 * - baseline = Z0_EQUILIBRIUM (línea isoeléctrica del modelo)
 * 
 * El rango [-0.5, 1.5] mV es CONSECUENCIA, no condición.
 * El clamp se aplica solo para visualización (DAC), no aquí.
 */
float ECGModel::applyScaling(float zRaw) const {
    if (!isCalibrated) {
        // Durante calibración, usar escalado provisional para mostrar morfología
        // Usar ganancia estimada basada en el target R (1.0 mV típico)
        float provisionalGain = ECG_R_TARGET_MV / 0.8f;  // 0.8 es amplitud típica del modelo
        return provisionalGain * (zRaw - Z0_EQUILIBRIUM);
    }
    
    // Escalado lineal simple: z_mV = G * (z - baseline)
    float scaled = physiologicalGain * (zRaw - baselineZ);
    
    return scaled;
}

// ============================================================================
// GENERACIÓN DE MUESTRA
// ============================================================================
float ECGModel::generateSample(float deltaTime) {
    sampleCount++;
    
    // =========================================================================
    // VFIB: Usar modelo espectral alternativo (no McSharry)
    // =========================================================================
    if (currentCondition == ECGCondition::VENTRICULAR_FIBRILLATION) {
        // Generar muestra con modelo espectral caótico normalizado
        float vfibMV = generateVFibSample(deltaTime);
        
        // Actualizar state.z para que getCurrentValueMV() funcione
        state.z = vfibMV;
        
        // generateVFibSample() ya retorna valor normalizado en rango clínico
        // No necesita escalado adicional
        float ecgMV = vfibMV;
        
        // Añadir ruido si está configurado (proporcional al rango)
        if (noiseLevel > 0.0f) {
            float noiseSigma = noiseLevel * ECG_DISPLAY_RANGE_MV;
            ecgMV += gaussianRandom(0.0f, noiseSigma);
        }
        
        // Guardar para getCurrentValueMV()
        vfibState.lastValue = ecgMV;
        
        // Actualizar métricas - solo incrementar beatCount periódicamente
        // (cada ~200ms = ~300 BPM, no en cada muestra)
        static uint32_t lastVFibBeatMs = 0;
        uint32_t now = millis();
        if (now - lastVFibBeatMs > 200) {
            beatCount++;
            lastVFibBeatMs = now;
        }
        measuredRR_ms = 200.0f;
        
        return ecgMV;
    }
    
    // =========================================================================
    // Modelo McSharry normal para otras condiciones
    // =========================================================================
    
    // Velocidad angular ω = 2π/RR
    float omega = 2.0f * PI / currentRR;
    
    // Integrar ecuaciones con RK4
    rungeKutta4Step(deltaTime, omega);
    
    // Calcular theta actual (posición angular en el ciclo)
    float theta = atan2f(state.y, state.x);
    
    // Actualizar tracking del ciclo actual (valores crudos para calibración)
    if (state.z > currentCycleZMax) currentCycleZMax = state.z;
    if (state.z < currentCycleZMin) currentCycleZMin = state.z;
    currentCycleTime += deltaTime;  // Acumular tiempo real del modelo
    currentCycleSamples++;
    
    // Actualizar buffer de calibración si aún no está calibrado
    if (!isCalibrated) {
        updateCalibrationBuffer(state.z);
    }
    
    // Aplicar escalado a mV
    float ecgMV = applyScaling(state.z);
    
    // Corregir señal para que baseline = 0 (consistencia con métricas)
    // Solo después de calibración cuando tenemos baseline válida
    if (isCalibrated) {
        ecgMV -= currentBaseline_mV;
    }
    
    // ✅ APLICAR DESPLAZAMIENTO ST (STEMI/Isquemia)
    // Aplicar offset desde el final de S hasta el final de T (incluye ST + T)
    // Esto eleva/deprime visualmente tanto el segmento ST como la onda T
    if (stOffset_mV != 0.0f && isCalibrated) {
        // Inicio: final de S
        float st_start = windows.S_center + windows.S_width * 0.5f;
        // Final: final de T (no solo inicio de T)
        float st_end = windows.T_center + windows.T_width * 0.5f;
        
        // Normalizar theta a [0, 2π]
        float theta_norm = theta;
        if (theta_norm < 0) theta_norm += 2.0f * PI;
        
        // Aplicar offset si estamos entre final de S y final de T
        if (theta_norm >= st_start && theta_norm <= st_end) {
            ecgMV += stOffset_mV;
        }
    }
    
    // Almacenar muestra del ciclo actual (theta + valor CORREGIDO en mV)
    // Esto asegura que R/S medidos coincidan con min/max de la señal real
    if (isCalibrated) {
        cycleSamples.add(theta, ecgMV);
    }
    
    // Detectar nuevo latido (después de almacenar la muestra)
    detectNewBeat();
    
    // Añadir ruido si está configurado
    // noiseLevel está en rango 0.0-0.10 (0-10%)
    // Ruido proporcional al rango de señal ECG (2 mV)
    // 10% ruido = 0.2 mV sigma → variación visible ±0.6 mV (3σ)
    if (noiseLevel > 0.0f) {
        float noiseSigma = noiseLevel * ECG_DISPLAY_RANGE_MV;  // 0.1 * 2.0 = 0.2 mV
        ecgMV += gaussianRandom(0.0f, noiseSigma);
    }
    
    return ecgMV;
}

// ============================================================================
// VALOR DAC (0-255)
// ============================================================================
uint8_t ECGModel::getDACValue(float deltaTime) {
    float mV = generateSample(deltaTime);
    
    // Mapear [-0.5, 1.5] mV → [0, 255]
    float normalized = (mV - ECG_DISPLAY_MIN_MV) / ECG_DISPLAY_RANGE_MV;
    normalized = fmaxf(0.0f, fminf(1.0f, normalized));
    
    return (uint8_t)(normalized * 255.0f);
}

// ============================================================================
// VALOR WAVEFORM NEXTION (0-255)
// ============================================================================
uint8_t ECGModel::getWaveformValue() const {
    // Usar último valor generado (ya en mV)
    float mV = getCurrentValueMV();
    
    // Aplicar ganancia de waveform (10-200%)
    // La ganancia se aplica respecto al centro del rango (0.5 mV = baseline típico)
    const float CENTER_MV = 0.5f;  // Centro visual del ECG
    float amplified = CENTER_MV + (mV - CENTER_MV) * waveformGain;
    
    // Mapear [-0.5, 1.5] mV → [0, 255] (rango completo)
    // Si amplificación excede rango, se clampea automáticamente
    float normalized = (amplified - ECG_DISPLAY_MIN_MV) / ECG_DISPLAY_RANGE_MV;
    normalized = fmaxf(0.0f, fminf(1.0f, normalized));
    
    return (uint8_t)(normalized * 255.0f);
}

// ============================================================================
// GETTERS
// ============================================================================

float ECGModel::getCurrentBPM() const {
    if (measuredRR_ms > 0) {
        return 60000.0f / measuredRR_ms;
    }
    return hrMean;
}

float ECGModel::getCurrentRR_ms() const {
    return measuredRR_ms;
}

float ECGModel::getCurrentValueMV() const {
    if (!isCalibrated) {
        return 0.0f;
    }
    
    // VFib usa modelo alternativo - retornar último valor generado
    if (currentCondition == ECGCondition::VENTRICULAR_FIBRILLATION) {
        return vfibState.lastValue;
    }
    
    // Aplicar corrección de baseline para consistencia con generateSample()
    return applyScaling(state.z) - currentBaseline_mV;
}

bool ECGModel::isInBeat() const {
    float theta = atan2f(state.y, state.x);
    return (theta > -0.15f && theta < 0.15f);
}

const char* ECGModel::getConditionName() const {
    switch (currentCondition) {
        case ECGCondition::NORMAL:                return "Normal";
        case ECGCondition::TACHYCARDIA:           return "Taquicardia";
        case ECGCondition::BRADYCARDIA:           return "Bradicardia";
        case ECGCondition::ATRIAL_FIBRILLATION:   return "FA";
        case ECGCondition::VENTRICULAR_FIBRILLATION: return "FV";
        case ECGCondition::AV_BLOCK_1:            return "BAV1";
        case ECGCondition::ST_ELEVATION:          return "STEMI";
        case ECGCondition::ST_DEPRESSION:         return "Isquemia";
        default:                                  return "Desconocido";
    }
}

void ECGModel::getHRRange(float& minHR, float& maxHR) const {
    switch (currentCondition) {
        case ECGCondition::NORMAL:
            minHR = 60.0f; maxHR = 100.0f;
            break;
        case ECGCondition::TACHYCARDIA:
            minHR = 100.0f; maxHR = 180.0f;
            break;
        case ECGCondition::BRADYCARDIA:
            minHR = 30.0f; maxHR = 60.0f;
            break;
        case ECGCondition::ATRIAL_FIBRILLATION:
            minHR = 60.0f; maxHR = 180.0f;
            break;
        case ECGCondition::VENTRICULAR_FIBRILLATION:
            minHR = 150.0f; maxHR = 500.0f;
            break;
        default:
            minHR = 40.0f; maxHR = 150.0f;
            break;
    }
}

void ECGModel::getOutputRange(float* minMV, float* maxMV) const {
    *minMV = ECG_DISPLAY_MIN_MV;
    *maxMV = ECG_DISPLAY_MAX_MV;
}

ECGDisplayMetrics ECGModel::getDisplayMetrics() const {
    ECGDisplayMetrics metrics;
    
    // =========================================================================
    // CASO ESPECIAL: VENTRICULAR FIBRILLATION
    // =========================================================================
    if (currentCondition == ECGCondition::VENTRICULAR_FIBRILLATION) {
        // VFib NO tiene ondas organizadas, NO hay intervalos ni complejos
        metrics.bpm = 0.0f;                    // Sin latidos organizados
        metrics.rrInterval_ms = 0.0f;          // Sin intervalos RR
        metrics.prInterval_ms = 0.0f;          // Sin onda P
        metrics.qrsDuration_ms = 0.0f;         // Sin complejo QRS
        metrics.qtInterval_ms = 0.0f;          // Sin intervalo QT
        metrics.qtcInterval_ms = 0.0f;         // Sin QTc
        
        // Amplitudes de ondas = N/A (no existen)
        metrics.pAmplitude_mV = 0.0f;
        metrics.qAmplitude_mV = 0.0f;
        metrics.rAmplitude_mV = vfibState.lastValue;  // Valor instantáneo caótico
        metrics.sAmplitude_mV = 0.0f;
        metrics.tAmplitude_mV = 0.0f;
        metrics.stDeviation_mV = 0.0f;
        
        metrics.beatCount = beatCount;         // Mantener contador por estadística
        metrics.conditionName = "Ventricular Fibrillation";
        
        return metrics;  // Salir temprano
    }
    
    // =========================================================================
    // RESTO DE CONDICIONES (McSharry)
    // =========================================================================
    metrics.bpm = getCurrentBPM();
    metrics.rrInterval_ms = measuredRR_ms;
    metrics.prInterval_ms = measuredPR_ms;
    metrics.qrsDuration_ms = measuredQRS_ms;
    metrics.qtInterval_ms = measuredQT_ms;
    metrics.qtcInterval_ms = measuredQTc_ms;
    metrics.pAmplitude_mV = measuredP_mV;
    metrics.qAmplitude_mV = measuredQ_mV;
    metrics.rAmplitude_mV = measuredR_mV;
    metrics.sAmplitude_mV = measuredS_mV;
    metrics.tAmplitude_mV = measuredT_mV;
    metrics.stDeviation_mV = measuredST_mV;
    metrics.beatCount = beatCount;
    metrics.conditionName = getConditionName();
    
    return metrics;
}

// ============================================================================
// GENERADOR ALEATORIO GAUSSIANO (Box-Muller)
// ============================================================================
float ECGModel::gaussianRandom(float mean, float std) {
    if (gaussHasSpare) {
        gaussHasSpare = false;
        return mean + std * gaussSpare;
    }
    
    float u, v, s;
    do {
        u = randomFloat() * 2.0f - 1.0f;
        v = randomFloat() * 2.0f - 1.0f;
        s = u * u + v * v;
    } while (s >= 1.0f || s == 0.0f);
    
    s = sqrtf(-2.0f * logf(s) / s);
    gaussSpare = v * s;
    gaussHasSpare = true;
    
    return mean + std * u * s;
}

float ECGModel::randomFloat() {
#ifdef ESP32
    return (float)(esp_random()) / (float)UINT32_MAX;
#else
    return (float)rand() / (float)RAND_MAX;
#endif
}

// ============================================================================
// MODELO VFIB ALTERNATIVO (Superposición espectral caótica)
// ============================================================================
/**
 * @brief Inicializa el modelo alternativo para fibrilación ventricular
 * 
 * VFib se caracteriza por actividad eléctrica desorganizada con
 * frecuencia dominante de 4-10 Hz. Simulamos esto con múltiples
 * osciladores con parámetros que varían en el tiempo.
 */
void ECGModel::initVFibModel() {
    vfibState.time = 0.0f;
    vfibState.lastUpdateMs = millis();
    vfibState.lastValue = 0.0f;
    
    // Inicializar componentes frecuenciales
    for (int k = 0; k < VFIB_COMPONENTS; k++) {
        // Frecuencias en rango VFib real: 4-10 Hz
        // Coarse VFib: 4-6 Hz (mejor pronóstico)
        // Fine VFib: 6-10 Hz (peor pronóstico)
        vfibState.frequencies[k] = 4.0f + (float)k * 1.2f + randomFloat() * 0.8f;
        
        // Amplitudes más altas para visualización clara
        vfibState.amplitudes[k] = 0.18f + randomFloat() * 0.22f;
        
        // Fases aleatorias
        vfibState.phases[k] = randomFloat() * 2.0f * PI;
    }
}

/**
 * @brief Genera una muestra de VFib usando el modelo espectral
 * 
 * Implementa superposición espectral caótica según Clayton et al. 1993
 * con normalización fisiológica según Strohmenger 1997 (coarse VFib).
 */
float ECGModel::generateVFibSample(float deltaTime) {
    // Actualizar tiempo acumulado
    vfibState.time += deltaTime;
    
    // Actualizar parámetros caóticos cada 200ms
    if (millis() - vfibState.lastUpdateMs > 200) {
        updateVFibParameters();
        vfibState.lastUpdateMs = millis();
    }
    
    // =========================================================================
    // SUPERPOSICIÓN ESPECTRAL (Clayton et al. 1993)
    // =========================================================================
    // VFib = suma de múltiples osciladores en rango 4-10 Hz con fases caóticas
    float rawValue = 0.0f;
    
    for (int i = 0; i < VFIB_COMPONENTS; i++) {
        float phase = 2.0f * PI * vfibState.frequencies[i] * vfibState.time 
                      + vfibState.phases[i];
        rawValue += vfibState.amplitudes[i] * sinf(phase);
    }
    
    // =========================================================================
    // NORMALIZACIÓN FISIOLÓGICA AGRESIVA
    // =========================================================================
    // Problema: rawValue puede estar en [-4.0, +4.0] mV (suma de 5×0.8 mV)
    // Solución: Escalar a rango clínico de coarse VFib: [-0.5, +0.5] mV
    float normalizedValue = rawValue * VFIB_SCALE_FACTOR;  // × 0.125
    
    // =========================================================================
    // CLAMP ESTRICTO AL RANGO CLÍNICO
    // =========================================================================
    // Garantizar que NUNCA exceda [-0.6, +0.6] mV
    if (normalizedValue > VFIB_SAFETY_CLAMP) {
        normalizedValue = VFIB_SAFETY_CLAMP;
    }
    if (normalizedValue < -VFIB_SAFETY_CLAMP) {
        normalizedValue = -VFIB_SAFETY_CLAMP;
    }
    
    // Almacenar para display
    vfibState.lastValue = normalizedValue;
    
    return normalizedValue;
}

/**
 * @brief Actualiza parámetros de VFib para mantener caos
 * 
 * Modelo espectral caótico basado en Clayton 1993 + Strohmenger 1997.
 * VFib tiene componentes espectrales en 4-10 Hz con amplitudes variables.
 */
void ECGModel::updateVFibParameters() {
    for (int i = 0; i < VFIB_COMPONENTS; i++) {
        // Frecuencias en rango fisiológico de VFib (4-10 Hz)
        vfibState.frequencies[i] = 4.0f + randomFloat() * 6.0f;  // 4-10 Hz
        
        // =====================================================================
        // AMPLITUDES INDIVIDUALES - AJUSTE CRÍTICO
        // Ahora: 0.2-0.8 mV → suma hasta 4.0 mV, pero se normaliza después ✅
        // ¿Por qué aumentamos los valores crudos?
        // - El VFIB_SCALE_FACTOR (0.24) reducirá todo después
        // - Queremos mantener la variabilidad caótica entre componentes
        // - Amplitudes más altas = mejor contraste entre componentes
        vfibState.amplitudes[i] = 0.2f + randomFloat() * 0.6f;  // 0.2-0.8 mV
        
        // Fases aleatorias para desorganización temporal
        vfibState.phases[i] = randomFloat() * 2.0f * PI;
    }
    
    vfibState.lastUpdateMs = millis();
}

// ============================================================================
// FUNCIONES DE ANÁLISIS POR VENTANAS ANGULARES
// ============================================================================

/**
 * Inicializa las ventanas angulares basándose en los parámetros ti y bi.
 * Debe llamarse después de modificar waveParams (en initializeWaveParams y applyHRFactCorrection).
 */
void ECGModel::initializeAngularWindows() {
    // Centros = ángulos ti de cada onda (se adaptan con hrfact)
    windows.P_center = waveParams.ti[0];  // ~-1.22 rad (-70°)
    windows.Q_center = waveParams.ti[1];  // ~-0.26 rad (-15°)
    windows.R_center = waveParams.ti[2];  // 0 rad (0°)
    windows.S_center = waveParams.ti[3];  // ~0.26 rad (15°)
    windows.T_center = waveParams.ti[4];  // ~1.75 rad (100°)
    
    // Anchos = 2.5 × bi (cubrir la gaussiana completa de cada onda)
    windows.P_width = waveParams.bi[0] * 2.5f;
    windows.Q_width = waveParams.bi[1] * 2.5f;
    windows.R_width = waveParams.bi[2] * 2.5f;
    windows.S_width = waveParams.bi[3] * 2.5f;
    windows.T_width = waveParams.bi[4] * 2.5f;
}

/**
 * Normaliza un ángulo al rango [-π, π]
 */
float ECGModel::normalizeAngle(float theta) {
    while (theta > PI) theta -= 2.0f * PI;
    while (theta < -PI) theta += 2.0f * PI;
    return theta;
}

/**
 * Busca el pico (máximo o mínimo) dentro de una ventana angular.
 * @param centerAngle Centro de la ventana (radianes)
 * @param widthAngle Ancho de la ventana (radianes, se busca en ±width)
 * @param findMax Si true busca máximo, si false busca mínimo
 * @return Valor en mV del pico encontrado
 */
float ECGModel::findPeakInWindow(float centerAngle, float widthAngle, bool findMax) {
    float extremeValue = findMax ? -1000.0f : 1000.0f;
    
    for (int i = 0; i < cycleSamples.count; i++) {
        float theta = normalizeAngle(cycleSamples.theta[i]);
        float distance = fabsf(normalizeAngle(theta - centerAngle));
        
        // ¿Está dentro de la ventana?
        if (distance <= widthAngle) {
            float value = cycleSamples.z_mV[i];
            
            if (findMax) {
                if (value > extremeValue) extremeValue = value;
            } else {
                if (value < extremeValue) extremeValue = value;
            }
        }
    }
    
    // Si no se encontró nada en la ventana, retornar 0
    if ((findMax && extremeValue < -999.0f) || (!findMax && extremeValue > 999.0f)) {
        return 0.0f;
    }
    
    return extremeValue;
}

/**
 * Calcula el promedio de valores dentro de una ventana angular (para segmento ST).
 * @param startAngle Ángulo inicial (radianes)
 * @param endAngle Ángulo final (radianes)
 * @return Promedio en mV de las muestras en la ventana
 */
float ECGModel::averageInWindow(float startAngle, float endAngle) {
    float sum = 0.0f;
    int count = 0;
    
    for (int i = 0; i < cycleSamples.count; i++) {
        float theta = normalizeAngle(cycleSamples.theta[i]);
        
        // Verificar si está en el rango [startAngle, endAngle]
        bool inWindow;
        if (startAngle <= endAngle) {
            inWindow = (theta >= startAngle && theta <= endAngle);
        } else {
            // Rango que cruza -π/π
            inWindow = (theta >= startAngle || theta <= endAngle);
        }
        
        if (inWindow) {
            sum += cycleSamples.z_mV[i];
            count++;
        }
    }
    
    return (count > 0) ? (sum / (float)count) : 0.0f;
}

/**
 * Encuentra el ángulo donde ocurre el pico (para cálculo de QRS y QT).
 * @param centerAngle Centro de la ventana (radianes)
 * @param widthAngle Ancho de la ventana (radianes)
 * @param findMax Si true busca máximo, si false busca mínimo
 * @return Ángulo (radianes) donde se encuentra el pico
 */
float ECGModel::findAngleAtPeak(float centerAngle, float widthAngle, bool findMax) {
    float extremeValue = findMax ? -1000.0f : 1000.0f;
    float extremeAngle = centerAngle;
    
    for (int i = 0; i < cycleSamples.count; i++) {
        float theta = normalizeAngle(cycleSamples.theta[i]);
        float distance = fabsf(normalizeAngle(theta - centerAngle));
        
        if (distance <= widthAngle) {
            float value = cycleSamples.z_mV[i];
            
            if ((findMax && value > extremeValue) || 
                (!findMax && value < extremeValue)) {
                extremeValue = value;
                extremeAngle = theta;
            }
        }
    }
    
    return extremeAngle;
}

/**
 * @brief Resetea métricas clínicas a valores iniciales de la condición actual
 * 
 * Esto evita mostrar métricas "fantasma" de la condición anterior durante
 * los primeros segundos después de cambiar de condición.
 * 
 * Valores reseteados son:
 * - Estimaciones fisiológicamente correctas para la condición
 * - Se actualizarán con mediciones reales después del primer ciclo completo
 */
void ECGModel::resetMetricsForCondition() {
    // =========================================================================
    // CASO ESPECIAL: VENTRICULAR FIBRILLATION
    // =========================================================================
    if (currentCondition == ECGCondition::VENTRICULAR_FIBRILLATION) {
        // VFib NO tiene ondas organizadas
        measuredRR_ms = 0.0f;
        measuredPR_ms = 0.0f;
        measuredQRS_ms = 0.0f;
        measuredQT_ms = 0.0f;
        measuredQTc_ms = 0.0f;
        measuredP_mV = 0.0f;
        measuredQ_mV = 0.0f;
        measuredR_mV = 0.0f;  // Se actualizará con vfibState.lastValue
        measuredS_mV = 0.0f;
        measuredT_mV = 0.0f;
        measuredST_mV = 0.0f;
        return;  // Salir temprano
    }
    
    // =========================================================================
    // RESTO DE CONDICIONES (McSharry)
    // =========================================================================
    // Calcular RR esperado para esta condición
    float expectedRR_ms = (60.0f / hrMean) * 1000.0f;
    
    // Resetear con valores esperados
    measuredRR_ms = expectedRR_ms;
    
    // Intervalos estándar (estimación inicial, se medirán en primer ciclo)
    measuredPR_ms = 160.0f;   // Normal: 120-200 ms
    measuredQRS_ms = 80.0f;   // Normal: 60-100 ms
    measuredQT_ms = 400.0f;   // Aproximado, se corregirá con QTc
    
    // QTc Bazett: QTc = QT / sqrt(RR_seconds)
    float rrSeconds = expectedRR_ms / 1000.0f;
    if (rrSeconds > 0.0f) {
        measuredQTc_ms = measuredQT_ms / sqrtf(rrSeconds);
    } else {
        measuredQTc_ms = measuredQT_ms;
    }
    
    // Amplitudes por defecto (se medirán en primer ciclo real)
    measuredP_mV = 0.15f;
    measuredQ_mV = -0.10f;
    measuredR_mV = 1.0f;   // Valor objetivo de calibración
    measuredS_mV = -0.20f;
    measuredT_mV = 0.30f;
    measuredST_mV = 0.0f;
    
    // =========================================================================
    // AJUSTES ESPECÍFICOS POR CONDICIÓN
    // =========================================================================
    switch (currentCondition) {
        case ECGCondition::TACHYCARDIA:
            // Tachy: QRS puede ser ligeramente más ancho
            measuredQRS_ms = 90.0f;
            // T puede ser más pequeña por repolarización rápida
            measuredT_mV = 0.20f;
            break;
            
        case ECGCondition::BRADYCARDIA:
            // Brady: intervalos más largos
            measuredPR_ms = 180.0f;
            measuredQT_ms = 450.0f;
            if (rrSeconds > 0.0f) {
                measuredQTc_ms = 450.0f / sqrtf(rrSeconds);
            }
            break;
            
        case ECGCondition::ATRIAL_FIBRILLATION:
            // AFib: sin onda P consistente
            measuredP_mV = 0.0f;   // P desorganizada
            measuredPR_ms = 0.0f;  // Sin PR definido
            break;
            
        case ECGCondition::AV_BLOCK_1:
            // AVB1: PR prolongado
            measuredPR_ms = 250.0f;  // >200 ms (diagnóstico de AVB1)
            break;
            
        case ECGCondition::ST_ELEVATION:
            // STEMI: elevación ST significativa
            measuredST_mV = 0.3f;   // Elevación de 3mm (criterio STEMI)
            break;
            
        case ECGCondition::ST_DEPRESSION:
            // NSTEMI: depresión ST
            measuredST_mV = -0.2f;  // Depresión de 2mm
            break;
            
        case ECGCondition::NORMAL:
        default:
            // Normal: valores ya seteados arriba son correctos
            break;
    }
}

// ============================================================================
// CONTROL DE FILTRADO DIGITAL
// ============================================================================

void ECGModel::setNotchFrequency(float freq) {
    filterChain.setNotchFreq(freq, 30.0f);
}

void ECGModel::enableHighpassFilter(bool en) {
    filterChain.enableHighpass(en);
}

void ECGModel::enableLowpassFilter(bool en) {
    filterChain.enableLowpass(en);
}

void ECGModel::enableNotchFilter(bool en) {
    filterChain.enableNotch(en);
}
