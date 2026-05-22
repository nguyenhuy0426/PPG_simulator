/**
 * @file ppg_model.cpp
 * @brief Implementación del modelo PPG - Fisiológicamente correcto
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Modelo fisiológico:
 * - Sístole ~constante (~300ms), diástole variable (se comprime con HR alto)
 * - PI dinámico como ÚNICO control de amplitud AC
 * - Forma de onda normalizada [0,1] con modificadores suaves por condición
 * - HR dinámico dentro del rango de patología
 * 
 * Referencias:
 * - Allen J (2007): Morfología base PPG
 * - Sun X et al. (2024): PI variabilidad latido a latido
 * - Fisiología cardiovascular: sístole ~constante, diástole variable
 */

#include "models/ppg_model.h"
#include "config.h"
#include <math.h>
#include <esp_random.h>

// ============================================================================
// CONSTRUCTOR
// ============================================================================
PPGModel::PPGModel() {
    hasPendingParams = false;
    reset();
}

// ============================================================================
// RESET - Valores base Allen 2007
// ============================================================================
void PPGModel::reset() {
    phaseInCycle = 0.0f;
    beatCount = 0;
    motionNoise = 0.0f;
    baselineWander = 0.0f;
    
    // Reset generador gaussiano
    gaussHasSpare = false;
    gaussSpare = 0.0f;
    
    // Valores iniciales (se actualizan con initConditionRanges)
    currentHR = 75.0f;
    currentPI = 3.0f;
    currentRR = 60.0f / currentHR;  // 0.8s a 75 BPM
    
    // DC baseline por defecto (1500 mV para que AC = PI × 15 mV)
    // Fórmula: PI = (AC / DC) × 100%  →  AC = PI × DC / 100 = PI × 15 mV
    dcBaseline = 1500.0f;
    lastSampleValue = dcBaseline;
    lastACValue = 0.0f;
    
    // Forma de onda BASE (Allen 2007) - NO en mV, normalizados
    systolicAmplitude = PPG_BASE_SYSTOLIC_AMPL;    // 1.0
    systolicWidth = PPG_SYSTOLIC_WIDTH;             // 0.055
    diastolicAmplitude = PPG_BASE_DIASTOLIC_RATIO; // 0.4
    diastolicWidth = PPG_DIASTOLIC_WIDTH;           // 0.10
    dicroticDepth = PPG_BASE_DICROTIC_DEPTH;        // 0.25
    dicroticWidth = PPG_NOTCH_WIDTH;                // 0.02
    
    // Calcular tiempos de fase iniciales
    systoleFraction = calculateSystoleFraction(currentHR);
    systoleTime = currentRR * 1000.0f * systoleFraction;
    diastoleTime = currentRR * 1000.0f * (1.0f - systoleFraction);
    
    // Variables para medición en tiempo real
    measuredPeakValue = dcBaseline;
    measuredValleyValue = dcBaseline;
    measuredNotchValue = dcBaseline;
    
    // Tracking dentro del ciclo
    currentCyclePeak = 0.0f;
    currentCycleValley = 99999.0f;
    currentCycleNotch = 99999.0f;
    
    // Tiempo simulado
    simulatedTime_ms = 0.0f;
    lastPeakTime_ms = 0.0f;
    lastValleyTime_ms = 0.0f;
    cycleStartTime_ms = 0.0f;
    previousPhase = 0.0f;
    
    // Métricas iniciales (del modelo)
    measuredRRInterval_ms = currentRR * 1000.0f;
    measuredSystoleTime_ms = systoleTime;
    measuredDiastoleTime_ms = diastoleTime;
    
    // Inicializar filtrado digital (deshabilitado por defecto)
    filterChain.configureForPPG(250.0f, 60.0f);  // 250 Hz, notch 60 Hz
    filterChain.reset();
    filteringEnabled = false;  // Deshabilitado - usuario activa si necesita
}

// ============================================================================
// INICIALIZACIÓN DE RANGOS POR CONDICIÓN
// Valores según tabla clínica (4 referencias)
// PI controla amplitud AC; forma base Allen ajustada por patología
// ============================================================================
void PPGModel::initConditionRanges() {
    switch (params.condition) {
        case PPGCondition::NORMAL:
            // PI: 2.9-6.1%, d/s 0.1-0.4
            // Pico sistólico claro; upstroke rápido; muesca sutil
            condRanges = {
                .hrMin = 60.0f, .hrMax = 100.0f, .hrCV = 0.02f,
                .piMin = 2.9f,  .piMax = 6.1f,   .piCV = 0.10f,
                .systolicAmpl = 1.0f,       // Base Allen
                .diastolicAmpl = 0.4f,      // Base Allen (d/s 0.4)
                .dicroticDepth = 0.25f      // Muesca sutil ≥20%
            };
            break;
            
        case PPGCondition::ARRHYTHMIA:
            // PI: 1.0-5.0%, amplitud variable
            // Latidos irregulares; plantilla promedio dispersa
            condRanges = {
                .hrMin = 60.0f, .hrMax = 180.0f, .hrCV = 0.15f,
                .piMin = 1.0f,  .piMax = 5.0f,   .piCV = 0.20f,
                .systolicAmpl = 1.0f,       // Base Allen
                .diastolicAmpl = 0.4f,      // Base Allen
                .dicroticDepth = 0.20f      // 10-30% variable
            };
            break;
            
        case PPGCondition::WEAK_PERFUSION:
            // PI: 0.5-2.1%, pico atenuado
            // AC muy reducido; muesca ausente o tenue
            condRanges = {
                .hrMin = 70.0f, .hrMax = 120.0f, .hrCV = 0.02f,
                .piMin = 0.5f,  .piMax = 2.1f,   .piCV = 0.15f,
                .systolicAmpl = 1.0f,       // Base Allen
                .diastolicAmpl = 0.3f,      // Reducido (pico atenuado)
                .dicroticDepth = 0.05f      // <10%, ausente o tenue
            };
            break;
            
        case PPGCondition::VASOCONSTRICTION:
            // PI: 0.7-0.8%, pulso aplanado
            // Upstroke menos pronunciado; muesca tenue
            condRanges = {
                .hrMin = 65.0f, .hrMax = 110.0f, .hrCV = 0.02f,
                .piMin = 0.7f,  .piMax = 0.8f,   .piCV = 0.10f,
                .systolicAmpl = 1.0f,       // Base Allen
                .diastolicAmpl = 0.25f,     // Reducido (pulso aplanado)
                .dicroticDepth = 0.05f      // <10%, tenue o inexistente
            };
            break;
            
        case PPGCondition::STRONG_PERFUSION:
            // PI: 7.0-20.0%, reflejo vascular prominente
            // Señal robusta; muesca prominente; alta AC
            condRanges = {
                .hrMin = 60.0f, .hrMax = 90.0f, .hrCV = 0.02f,
                .piMin = 7.0f,  .piMax = 20.0f, .piCV = 0.10f,
                .systolicAmpl = 1.0f,       // Base Allen
                .diastolicAmpl = 0.6f,      // Aumentado (reflejo vascular prominente)
                .dicroticDepth = 0.35f      // ≥30%, prominente
            };
            break;
            
        case PPGCondition::VASODILATION:
            // PI: 5.0-10.0%, mejor relleno diastólico
            // Pico más alto y ancho; muesca más marcada
            condRanges = {
                .hrMin = 60.0f, .hrMax = 90.0f, .hrCV = 0.02f,
                .piMin = 5.0f,  .piMax = 10.0f, .piCV = 0.10f,
                .systolicAmpl = 1.0f,       // Base Allen
                .diastolicAmpl = 0.5f,      // Aumentado (mejor relleno diastólico)
                .dicroticDepth = 0.30f      // 20-40%, más marcada
            };
            break;
            
        default:
            condRanges = {
                .hrMin = 60.0f, .hrMax = 100.0f, .hrCV = 0.02f,
                .piMin = 2.9f,  .piMax = 6.1f,   .piCV = 0.10f,
                .systolicAmpl = 1.0f,
                .diastolicAmpl = 0.4f,
                .dicroticDepth = 0.25f
            };
    }
}

// ============================================================================
// CONFIGURACIÓN DE PARÁMETROS
// ============================================================================
void PPGModel::setParameters(const PPGParameters& newParams) {
    params = newParams;
    initConditionRanges();
    applyConditionModifiers();
    
    // Generar HR inicial dentro del rango
    currentHR = generateDynamicHR();
    currentRR = 60.0f / currentHR;
    
    // Generar PI inicial dentro del rango
    currentPI = generateDynamicPI();
    
    // Calcular tiempos de fase
    systoleFraction = calculateSystoleFraction(currentHR);
    systoleTime = currentRR * 1000.0f * systoleFraction;
    diastoleTime = currentRR * 1000.0f * (1.0f - systoleFraction);
    
    // IMPORTANTE: Actualizar métricas medidas para que estén disponibles inmediatamente
    measuredRRInterval_ms = currentRR * 1000.0f;
    measuredSystoleTime_ms = systoleTime;
    measuredDiastoleTime_ms = diastoleTime;
}

void PPGModel::setPendingParameters(const PPGParameters& newParams) {
    pendingParams = newParams;
    hasPendingParams = true;
}

// ============================================================================
// MODIFICADORES DE FORMA POR CONDICIÓN
// Base Allen 2007 ajustada según patología
// PI controla amplitud AC; forma y muesca según tabla clínica
// ============================================================================
void PPGModel::applyConditionModifiers() {
    // Amplitudes según condición (base Allen, ajustadas por patología)
    systolicAmplitude = condRanges.systolicAmpl;
    diastolicAmplitude = condRanges.diastolicAmpl;
    
    // Profundidad muesca según tabla clínica
    dicroticDepth = condRanges.dicroticDepth;
    
    // Anchos se mantienen constantes (Allen 2007)
    systolicWidth = PPG_SYSTOLIC_WIDTH;
    diastolicWidth = PPG_DIASTOLIC_WIDTH;
    dicroticWidth = PPG_NOTCH_WIDTH;
    
    motionNoise = 0.0f;
}

// ============================================================================
// GENERACIÓN DE HR DINÁMICO
// Elige valor aleatorio dentro del rango de patología, luego varía con CV
// ============================================================================
float PPGModel::generateDynamicHR() {
    // Valor medio aleatorio dentro del rango de la condición
    float hrRange = condRanges.hrMax - condRanges.hrMin;
    float hrBase = condRanges.hrMin + (esp_random() / (float)UINT32_MAX) * hrRange;
    
    // Variabilidad gaussiana (sigma = mean * CV)
    float sigma = hrBase * condRanges.hrCV;
    float variation = gaussianRandom(0.0f, sigma);
    float dynamicHR = hrBase + variation;
    
    // Clampear al rango fisiológico
    dynamicHR = constrain(dynamicHR, condRanges.hrMin, condRanges.hrMax);
    
    return dynamicHR;
}

// ============================================================================
// GENERACIÓN DE PI DINÁMICO
// Ref: Sun X et al. (2024) - PI varía latido a latido
// sigma = meanPI * cvPI
// ============================================================================
float PPGModel::generateDynamicPI() {
    // Valor medio aleatorio dentro del rango de la condición
    float piRange = condRanges.piMax - condRanges.piMin;
    float piBase = condRanges.piMin + (esp_random() / (float)UINT32_MAX) * piRange;
    
    // Variabilidad gaussiana (sigma = mean * CV)
    float sigma = piBase * condRanges.piCV;
    float variation = gaussianRandom(0.0f, sigma);
    float dynamicPI = piBase + variation;
    
    // Clampear al rango de la condición
    dynamicPI = constrain(dynamicPI, condRanges.piMin, condRanges.piMax);
    
    return dynamicPI;
}

// ============================================================================
// CÁLCULO DE FRACCIÓN SISTÓLICA f(HR)
// 
// Fisiología: La sístole varía poco con HR, la diástole absorbe el cambio
// - HR bajo (60) → sístole ~30% del ciclo (300ms de 1000ms)
// - HR alto (120) → sístole ~52% del ciclo (260ms de 500ms)
// 
// Modelo lineal simplificado basado en datos fisiológicos:
// systole_ms ≈ 350 - 0.75 * HR  (aproximación)
// ============================================================================
float PPGModel::calculateSystoleFraction(float hr) {
    // Duración sistólica en ms (varía poco: ~250-350ms)
    // Modelo: decrece ligeramente con HR
    float systole_ms = PPG_SYSTOLE_BASE_MS - 0.5f * (hr - 60.0f);
    systole_ms = constrain(systole_ms, PPG_SYSTOLE_MIN_MS, PPG_SYSTOLE_MAX_MS);
    
    // RR en ms
    float rr_ms = 60000.0f / hr;
    
    // Fracción sistólica
    float fraction = systole_ms / rr_ms;
    
    // Limitar a rango razonable (no puede ser >60% ni <20%)
    fraction = constrain(fraction, 0.20f, 0.60f);
    
    return fraction;
}

// ============================================================================
// GENERACIÓN DE RR CON VARIABILIDAD
// ============================================================================
float PPGModel::generateNextRR() {
    // Usar HR de params (seteado por usuario o por condición inicial)
    // NO sobrescribir con generateDynamicHR() para respetar setHeartRate()
    currentHR = params.heartRate;
    
    // RR = 60 / HR
    float rrMean = 60.0f / currentHR;
    
    // Variabilidad adicional latido a latido
    float rrStd = rrMean * condRanges.hrCV;
    
    // Para arritmia: latidos ectópicos ocasionales
    if (params.condition == PPGCondition::ARRHYTHMIA) {
        if (esp_random() % 100 < 15) {
            rrMean *= 0.7f;  // Latido prematuro
        }
    }
    
    float rr = rrMean + gaussianRandom(0.0f, rrStd);
    rr = constrain(rr, 0.3f, 2.0f);  // 30-200 BPM
    
    // Actualizar tiempos de fase
    systoleFraction = calculateSystoleFraction(currentHR);
    systoleTime = rr * 1000.0f * systoleFraction;
    diastoleTime = rr * 1000.0f * (1.0f - systoleFraction);
    
    return rr;
}

// ============================================================================
// FORMA DEL PULSO - MODELO DOBLE GAUSSIANA (Allen 2007)
// Retorna forma NORMALIZADA [0, 1]
// ============================================================================
float PPGModel::computePulseShape(float phase) {
    // Normalizar fase a 0-1
    phase = fmodf(phase, 1.0f);
    if (phase < 0) phase += 1.0f;
    
    // Pico sistólico (gaussiana principal)
    float systolic = systolicAmplitude * 
        expf(-powf(phase - PPG_SYSTOLIC_POS, 2) / (2.0f * powf(systolicWidth, 2)));
    
    // Pico diastólico (reflexión de onda)
    float diastolic = diastolicAmplitude * 
        expf(-powf(phase - PPG_DIASTOLIC_POS, 2) / (2.0f * powf(diastolicWidth, 2)));
    
    // Muesca dicrótica (cierre válvula aórtica)
    float notch = dicroticDepth * systolicAmplitude * 
        expf(-powf(phase - PPG_NOTCH_POS, 2) / (2.0f * powf(dicroticWidth, 2)));
    
    // Señal compuesta
    float pulse = systolic + diastolic - notch;
    
    // NORMALIZAR a [0, 1]
    pulse = normalizePulse(pulse);
    
    return pulse;
}

// ============================================================================
// NORMALIZACIÓN DEL PULSO A [0, 1]
// ============================================================================
float PPGModel::normalizePulse(float rawPulse) {
    // Rango teórico aproximado del pulso crudo
    // Con systolic=1.0, diastolic=0.4, notch=0.25 → max ~1.15, min ~0
    const float PULSE_MIN = 0.0f;
    const float PULSE_MAX = 1.4f;  // Margen para modificadores
    
    float normalized = (rawPulse - PULSE_MIN) / (PULSE_MAX - PULSE_MIN);
    normalized = constrain(normalized, 0.0f, 1.0f);
    
    return normalized;
}

// ============================================================================
// DETECCIÓN DE LATIDO Y APLICACIÓN DE PARÁMETROS PENDIENTES
// ============================================================================
void PPGModel::detectBeatAndApplyPending() {
    beatCount++;
    
    // Aplicar parámetros pendientes
    if (hasPendingParams) {
        setParameters(pendingParams);
        hasPendingParams = false;
    }
    
    // Generar nuevo RR (incluye actualización de HR dinámico)
    currentRR = generateNextRR();
    
    // Actualizar PI dinámico
    currentPI = generateDynamicPI();
    
    // Actualizar métricas medidas basadas en el modelo (para display inmediato)
    // Esto asegura que RR y otras métricas estén disponibles desde el primer latido
    measuredRRInterval_ms = currentRR * 1000.0f;
}

// ============================================================================
// GENERACIÓN DE MUESTRA
// Flujo: pulseShape[0,1] → AC = PI * scale → signal = DC + pulse * AC
// ============================================================================
float PPGModel::generateSample(float deltaTime) {
    // Avanzar fase dentro del ciclo cardíaco
    phaseInCycle += deltaTime / currentRR;
    
    // Nuevo latido al completar ciclo
    if (phaseInCycle >= 1.0f) {
        phaseInCycle = fmodf(phaseInCycle, 1.0f);
        detectBeatAndApplyPending();
    }
    
    // 1. Calcular forma del pulso NORMALIZADA [0, 1]
    float pulse = computePulseShape(phaseInCycle);
    
    // 2. Calcular amplitud AC basada ÚNICAMENTE en PI dinámico
    // AC = PI * AC_SCALE_PER_PI (mV)
    float acAmplitude = currentPI * PPG_AC_SCALE_PER_PI;
    
    // 3. Componente AC pura (para Nextion Waveform)
    float acValue = pulse * acAmplitude;
    
    // 4. Señal final: DC + AC
    float signal_mv = dcBaseline + acValue;
    
    // 5. Baseline wander (~0.05 Hz)
    baselineWander = fmodf(baselineWander + deltaTime * 0.3f, 2.0f * PI);
    float wanderAmplitude = (dcBaseline > 0) ? 0.002f * dcBaseline : 2.0f;
    signal_mv += wanderAmplitude * sinf(baselineWander);
    
    // 6. Ruido gaussiano proporcional a AC
    // noiseLevel está en rango 0.0-0.10 (0-10%)
    // Ruido proporcional a amplitud AC de la señal
    // 10% ruido = acAmplitude * 0.1 sigma → variación visible
    float noiseAmplitude = params.noiseLevel * acAmplitude;
    signal_mv += gaussianRandom(0.0f, noiseAmplitude);
    
    // Evitar valores negativos si DC > 0
    if (dcBaseline > 0) {
        signal_mv = fmaxf(signal_mv, 0.0f);
    }
    
    // === MEDICIÓN EN TIEMPO REAL BASADA EN FASE ===
    // Usar tiempo simulado, no micros()
    float deltaTime_ms = deltaTime * 1000.0f;
    simulatedTime_ms += deltaTime_ms;
    
    // Trackear máximo (pico) en zona sistólica (fase 0.10-0.25)
    if (phaseInCycle >= 0.10f && phaseInCycle <= 0.25f) {
        if (signal_mv > currentCyclePeak) {
            currentCyclePeak = signal_mv;
        }
    }
    
    // Trackear mínimo (valle) al inicio del ciclo (fase 0-0.08)
    if (phaseInCycle <= 0.08f) {
        if (signal_mv < currentCycleValley) {
            currentCycleValley = signal_mv;
        }
    }
    
    // Trackear muesca dicrótica (fase 0.28-0.35)
    if (phaseInCycle >= 0.28f && phaseInCycle <= 0.35f) {
        if (signal_mv < currentCycleNotch) {
            currentCycleNotch = signal_mv;
        }
    }
    
    // Detectar fin de sístole (transición fase > 0.25 desde < 0.25)
    if (previousPhase <= 0.25f && phaseInCycle > 0.25f) {
        // Guardar pico medido
        if (currentCyclePeak > 0.0f) {
            measuredPeakValue = currentCyclePeak;
            
            // Calcular tiempo sistólico (desde inicio ciclo hasta pico)
            float peakTime = cycleStartTime_ms + (currentRR * 1000.0f * PPG_SYSTOLIC_POS);
            if (lastValleyTime_ms > 0.0f) {
                measuredSystoleTime_ms = peakTime - lastValleyTime_ms;
            }
            lastPeakTime_ms = peakTime;
        }
    }
    
    // Detectar nuevo ciclo (fase wrap-around o fase muy baja después de alta)
    if (phaseInCycle < previousPhase && previousPhase > 0.5f) {
        // Fin del ciclo anterior - guardar métricas
        if (currentCycleValley < 99999.0f) {
            measuredValleyValue = currentCycleValley;
        }
        if (currentCycleNotch < 99999.0f) {
            measuredNotchValue = currentCycleNotch;
        }
        
        // Calcular RR (tiempo entre inicios de ciclo)
        if (cycleStartTime_ms > 0.0f) {
            measuredRRInterval_ms = simulatedTime_ms - cycleStartTime_ms;
        }
        
        // Calcular diástole (desde pico hasta fin de ciclo)
        if (lastPeakTime_ms > 0.0f && cycleStartTime_ms > 0.0f) {
            measuredDiastoleTime_ms = simulatedTime_ms - lastPeakTime_ms;
        }
        
        // Nuevo ciclo - reset tracking
        lastValleyTime_ms = simulatedTime_ms;
        cycleStartTime_ms = simulatedTime_ms;
        currentCyclePeak = 0.0f;
        currentCycleValley = 99999.0f;
        currentCycleNotch = 99999.0f;
    }
    
    previousPhase = phaseInCycle;
    
    lastSampleValue = signal_mv;
    lastACValue = acValue;  // Guardar componente AC pura
    
    return signal_mv;
}

// ============================================================================
// CONVERSIÓN A DAC
// ============================================================================
// NOTA: La salida DAC solo contiene la componente AC de la señal PPG.
// Justificación: El componente DC (baseline ~1000 mV) representa la absorción
// constante de luz y no aporta información diagnóstica. La utilidad clínica
// de la señal PPG reside en la componente pulsátil (AC), que refleja:
//   - Volumen sanguíneo pulsátil (forma de onda)
//   - Índice de perfusión (PI = AC/DC × 100%)
//   - Variabilidad de la frecuencia cardíaca
// Al enviar solo AC al DAC, la señal es directamente comparable con la
// visualización en Nextion y facilita la conexión a equipos externos.
// ============================================================================
uint8_t PPGModel::getDACValue(float deltaTime) {
    // Generar muestra completa (actualiza lastACValue internamente)
    generateSample(deltaTime);
    
    // Convertir solo la componente AC a valor DAC
    return acValueToDACValue(lastACValue);
}

uint8_t PPGModel::voltageToDACValue(float voltage) {
    // Mantener para compatibilidad - mapea señal completa DC+AC
    float rangeMin = dcBaseline - 200.0f;
    float rangeMax = dcBaseline + 200.0f;
    
    if (dcBaseline == 0.0f) {
        rangeMin = -100.0f;
        rangeMax = 100.0f;
    }
    
    float normalized = (voltage - rangeMin) / (rangeMax - rangeMin);
    normalized = constrain(normalized, 0.0f, 1.0f);
    return (uint8_t)(normalized * 255.0f);
}

uint8_t PPGModel::acValueToDACValue(float acValue_mV) {
    // Mapeo de componente AC pura a DAC 8-bit
    // Fórmula: PI = (AC / DC) × 100%  →  AC = PI × DC / 100
    // Con DC = 1500 mV:  AC = PI × 15 mV
    // La señal AC del PPG es UNIPOLAR: va de 0 (valle) a ~150 mV (pico sistólico)
    // donde AC_max = PI_max × 15 mV/% ≈ 10% × 15 = 150 mV
    // 
    // Escalado idéntico al usado en Nextion waveform:
    //   0 mV → DAC 0 → 0.0V
    //   150 mV → DAC 255 → 3.3V
    const float AC_MAX_MV = 150.0f;  // Máximo AC (PI~10%)
    
    float normalized = acValue_mV / AC_MAX_MV;
    normalized = constrain(normalized, 0.0f, 1.0f);
    return (uint8_t)(normalized * 255.0f);
}

// ============================================================================
// MÉTRICAS MEDIBLES
// ============================================================================

float PPGModel::getACAmplitude() const {
    // AC = PI * scale (mV)
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
// HELPERS
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
        case PPGCondition::WEAK_PERFUSION: return "Perfusion Debil";
        case PPGCondition::VASOCONSTRICTION: return "Vasoconstriccion";
        case PPGCondition::STRONG_PERFUSION: return "Perfusion Fuerte";
        case PPGCondition::VASODILATION: return "Vasodilatacion";
        default: return "Desconocido";
    }
}

// ============================================================================
// SEÑAL AC PURA PARA NEXTION WAVEFORM
// Escala la componente AC UNIPOLAR al rango 26-255 (piso al 10%)
// ============================================================================
uint8_t PPGModel::getWaveformValue() const {
    // Rango AC clínico fijo para visualización óptima:
    // - Fórmula: PI = (AC / DC) × 100%  →  AC = PI × DC / 100
    // - Con DC = 1500 mV:  AC = PI × 15 mV
    // - PI típico: 0.5% - 10% → AC: 7.5 - 150 mV
    //
    // La señal AC es UNIPOLAR: pulse va de 0 a 1, acValue va de 0 a AC_amplitude
    // Se aplica factor de amplificación configurado por el usuario (0.5-2.0)
    const float AC_DISPLAY_MAX = 150.0f;  // mV - PI 10% → AC 150 mV
    const uint8_t WAVEFORM_MIN = 26;      // Piso: 26/255 ≈ 10%
    const uint8_t WAVEFORM_RANGE = 229;   // 255 - 26 = 229 niveles útiles
    
    // Aplicar factor de amplificación (50-200% → 0.5-2.0)
    float amplifiedAC = lastACValue * params.amplification;
    
    // Mapeo unipolar: 0 → WAVEFORM_MIN, AC_DISPLAY_MAX → 255
    float normalized = amplifiedAC / AC_DISPLAY_MAX;
    normalized = constrain(normalized, 0.0f, 1.0f);
    
    return WAVEFORM_MIN + (uint8_t)(normalized * WAVEFORM_RANGE);
}

// ============================================================================
// MÉTRICAS MEDIDAS EN TIEMPO REAL
// Valores obtenidos de la señal, no de las variables del modelo
// ============================================================================

float PPGModel::getMeasuredHR() const {
    // HR = 60000 / RR_ms
    if (measuredRRInterval_ms > 0) {
        return 60000.0f / measuredRRInterval_ms;
    }
    return currentHR;  // Fallback al valor del modelo
}

float PPGModel::getMeasuredRRInterval() const {
    return measuredRRInterval_ms;
}

float PPGModel::getMeasuredACAmplitude() const {
    // AC = pico - valle (mV)
    return measuredPeakValue - measuredValleyValue;
}

float PPGModel::getMeasuredPI() const {
    // PI = (AC / DC) × 100%
    if (dcBaseline > 0) {
        float ac = getMeasuredACAmplitude();
        return (ac / dcBaseline) * 100.0f;
    }
    return currentPI;  // Fallback
}

float PPGModel::getMeasuredSystoleTime() const {
    return measuredSystoleTime_ms;
}

float PPGModel::getMeasuredDiastoleTime() const {
    return measuredDiastoleTime_ms;
}

float PPGModel::getMeasuredNotchDepth() const {
    // Profundidad = pico sistólico - punto mínimo de muesca (mV)
    return measuredPeakValue - measuredNotchValue;
}

// ============================================================================
// CONTROL DE FILTRADO DIGITAL
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
