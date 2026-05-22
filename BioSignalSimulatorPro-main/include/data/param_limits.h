/**
 * @file param_limits.h
 * @brief Límites fisiológicos de parámetros por condición
 * @version 1.0.0
 * 
 * @details
 * Define rangos válidos para cada parámetro según la condición patológica.
 * 
 * USO PRINCIPAL:
 * - param_controller.cpp consulta estos límites para RESTRINGIR los valores
 *   que el usuario puede establecer según la condición actual.
 * - Ejemplo: Si está en NORMAL, heartRate se limita a 60-100 BPM.
 *   Si intenta poner 120, se clampea a 100.
 * 
 * BENEFICIO:
 * - Garantiza coherencia fisiológica: no se puede estar en "NORMAL" con
 *   parámetros que corresponden a otra patología.
 * - La UI (Nextion) puede consultar getCurrentXXXLimits() para mostrar
 *   el rango válido del slider según la condición actual.
 * 
 * Referencias: AHA Guidelines, Task Force 1996, De Luca 1997, Allen 2007
 */

#ifndef PARAM_LIMITS_H
#define PARAM_LIMITS_H

#include "signal_types.h"

// ============================================================================
// ESTRUCTURA DE LÍMITES
// ============================================================================
struct ParamRange {
    float min;
    float max;
    float defaultVal;
};

// ============================================================================
// LÍMITES ECG POR CONDICIÓN
// Referencias:
//   - AHA/ACC Guidelines for ECG Interpretation (2018)
//   - Task Force of ESC/NASPE. Heart rate variability (1996)
//   - Surawicz B. & Knilans T. Chou's Electrocardiography (8th ed, 2008)
//   - Goldberger AL. Clinical Electrocardiography (9th ed, 2017)
// 
// Nota: Los límites corresponden a los parámetros en ECGParameters:
// - heartRate, pWaveAmplitude, qrsAmplitude, tWaveAmplitude, stShift
// ============================================================================
struct ECGLimits {
    ParamRange heartRate;       // BPM
    ParamRange pAmplitude;      // Factor multiplicador (0.0-2.0)
    ParamRange qrsAmplitude;    // Factor multiplicador (0.5-2.0)
    ParamRange tAmplitude;      // Factor multiplicador (0.5-2.0)
    ParamRange stShift;         // mV (-0.3 a +0.3)
};

inline ECGLimits getECGLimits(ECGCondition condition) {
    ECGLimits limits;
    
    // Valores por defecto (normales) - Surawicz 2008
    limits.pAmplitude   = {0.5f, 2.0f, 1.0f};
    limits.qrsAmplitude = {0.5f, 2.0f, 1.0f};
    limits.tAmplitude   = {0.5f, 2.0f, 1.0f};
    
    switch (condition) {
        case ECGCondition::NORMAL:
            // AHA: ritmo sinusal normal 60-100 BPM
            limits.heartRate   = {60.0f, 100.0f, 75.0f};
            limits.pAmplitude  = {0.1f, 0.3f, 0.2f};     // P: 0.1-0.3 mV
            limits.tAmplitude  = {0.2f, 0.6f, 0.4f};     // T: 0.2-0.6 mV
            limits.stShift     = {-0.05f, 0.05f, 0.0f};  // ST isoeléctrico
            break;
            
        case ECGCondition::TACHYCARDIA:
            // AHA: taquicardia sinusal >100 BPM, típicamente 100-180
            limits.heartRate   = {100.0f, 180.0f, 130.0f};
            limits.stShift     = {-0.1f, 0.1f, 0.0f};
            break;
            
        case ECGCondition::BRADYCARDIA:
            // AHA: bradicardia sinusal <60 BPM
            limits.heartRate   = {30.0f, 59.0f, 45.0f};
            limits.stShift     = {-0.05f, 0.05f, 0.0f};
            break;
            
        case ECGCondition::ATRIAL_FIBRILLATION:
            // Goldberger 2017: AFib 60-180, irregular, sin onda P
            limits.heartRate   = {60.0f, 180.0f, 110.0f};
            limits.pAmplitude  = {0.0f, 0.0f, 0.0f};  // Ondas f reemplazan P
            limits.stShift     = {-0.1f, 0.1f, 0.0f};
            break;
            
        case ECGCondition::VENTRICULAR_FIBRILLATION:
            // Pseudo-frecuencia VFib 150-500 (Clayton 1993)
            // Ref: Clayton RH et al. "Frequency analysis of VF." IEEE Trans Biomed Eng. 1993
            limits.heartRate   = {150.0f, 500.0f, 300.0f};
            limits.pAmplitude  = {0.0f, 0.0f, 0.0f};
            limits.qrsAmplitude = {0.0f, 0.0f, 0.0f};  // No hay QRS identificable
            limits.tAmplitude  = {0.0f, 0.0f, 0.0f};
            limits.stShift     = {-2.0f, 2.0f, 0.0f};  // Caótico
            break;
            
        case ECGCondition::AV_BLOCK_1:
            // Bloqueo AV 1º grado: morfología normal, solo PR > 200 ms
            // Ref: AHA/ACC/HRS 2018 Bradycardia Guidelines
            limits.heartRate   = {60.0f, 100.0f, 75.0f};
            limits.pAmplitude  = {0.15f, 0.25f, 0.2f};  // P normal
            limits.qrsAmplitude = {0.8f, 1.5f, 1.0f};   // QRS normal
            limits.tAmplitude  = {0.3f, 0.5f, 0.4f};    // T normal
            limits.stShift     = {-0.05f, 0.05f, 0.0f}; // ST isoeléctrico
            break;
            
        case ECGCondition::ST_ELEVATION:
            // STEMI: 50-110 BPM (bradicardia relativa o taquicardia)
            // Ref: Antman EM et al. ACC/AHA STEMI Guidelines. Circulation 2004
            // + Thygesen 2018: Fourth Universal Definition of MI
            limits.heartRate   = {50.0f, 110.0f, 80.0f};
            limits.pAmplitude  = {0.1f, 0.3f, 0.2f};     // P normal
            limits.stShift     = {0.2f, 0.5f, 0.3f};     // ELEVACIÓN: ≥0.2 mV
            limits.tAmplitude  = {0.6f, 1.2f, 0.8f};     // T hiperaguda >0.6 mV
            break;
            
        case ECGCondition::ST_DEPRESSION:
            // Isquemia: 50-150 BPM (puede coexistir con taquicardia por dolor/estrés)
            // Ref: Goldberger 2017 + ECGwaves - ST depression in ischemia
            limits.heartRate   = {50.0f, 150.0f, 90.0f};
            limits.pAmplitude  = {0.1f, 0.3f, 0.2f};     // P normal
            limits.stShift     = {-0.2f, -0.05f, -0.1f}; // DEPRESIÓN: 0.05-0.2 mV
            limits.tAmplitude  = {-0.3f, -0.1f, -0.2f};  // T invertida: -0.1 a -0.3 mV
            break;
            
        default:
            limits.heartRate   = {60.0f, 100.0f, 75.0f};
            limits.stShift     = {-0.1f, 0.1f, 0.0f};
            break;
    }
    
    return limits;
}

// ============================================================================
// LÍMITES EMG POR CONDICIÓN
// Referencia: De Luca 1997, Henneman 1965, Fuglevand 1993
// ============================================================================
struct EMGLimits {
    ParamRange excitationLevel;  // 0.0-1.0 (% MVC)
    ParamRange amplitude;        // Factor multiplicador
};

inline EMGLimits getEMGLimits(EMGCondition condition) {
    EMGLimits limits;
    
    switch (condition) {
        case EMGCondition::REST:
            limits.excitationLevel = {0.0f, 0.1f, 0.0f};
            limits.amplitude       = {0.1f, 0.5f, 0.2f};
            break;
            
        case EMGCondition::LOW_CONTRACTION:
            limits.excitationLevel = {0.05f, 0.20f, 0.12f};
            limits.amplitude       = {0.5f, 1.0f, 0.7f};
            break;
            
        case EMGCondition::MODERATE_CONTRACTION:
            limits.excitationLevel = {0.20f, 0.50f, 0.35f};
            limits.amplitude       = {0.8f, 1.5f, 1.0f};
            break;
            
        case EMGCondition::HIGH_CONTRACTION:
            limits.excitationLevel = {0.50f, 1.0f, 0.75f};
            limits.amplitude       = {1.2f, 2.5f, 1.8f};
            break;
            
        case EMGCondition::TREMOR:
            limits.excitationLevel = {0.0f, 0.0f, 0.0f};  // No parametrizable
            limits.amplitude       = {0.5f, 1.5f, 1.0f};
            break;
            
        case EMGCondition::FATIGUE:
            limits.excitationLevel = {0.0f, 0.0f, 0.0f};  // No parametrizable (protocolo fijo 50% MVC)
            limits.amplitude       = {0.5f, 1.5f, 1.0f};
            break;
            
        default:
            limits.excitationLevel = {0.0f, 1.0f, 0.5f};
            limits.amplitude       = {0.5f, 2.0f, 1.0f};
            break;
    }
    
    return limits;
}

// ============================================================================
// LÍMITES PPG POR CONDICIÓN
// Referencias:
//   - Allen J. (2007). Photoplethysmography and its application in clinical
//     physiological measurement. Physiological Measurement, 28(3), R1-R39.
//   - Elgendi M. (2012). On the analysis of fingertip photoplethysmogram signals.
//     Current Cardiology Reviews, 8(1), 14-25.
//   - Millasseau SC. (2002). Contour analysis of the photoplethysmographic pulse.
//     Journal of Hypertension, 20(12), 2407-2414.
//   - Reisner A. (2008). Utility of the photoplethysmogram in circulatory monitoring.
//     Anesthesiology, 108(5), 950-958.
//   - Shelley KH. (2007). Photoplethysmography: Beyond the calculation of arterial
//     oxygen saturation and heart rate. Anesthesia & Analgesia, 105(6), S31-S36.
// ============================================================================
struct PPGLimits {
    ParamRange heartRate;
    ParamRange perfusionIndex;   // PI en % (0.1-20%)
    ParamRange dicroticNotch;    // Prominencia de muesca dicrótica (0-1)
};

inline PPGLimits getPPGLimits(PPGCondition condition) {
    PPGLimits limits;
    
    switch (condition) {
        case PPGCondition::NORMAL:
            // Allen 2007: ritmo sinusal 60-100, PI 2.9-6.1%
            limits.heartRate       = {60.0f, 100.0f, 75.0f};
            limits.perfusionIndex  = {2.9f, 6.1f, 4.5f};
            limits.dicroticNotch   = {0.2f, 0.5f, 0.35f};
            break;
            
        case PPGCondition::ARRHYTHMIA:
            // Elgendi 2012: variabilidad RR aumentada, PI 1.0-5.0%
            limits.heartRate       = {50.0f, 150.0f, 75.0f};
            limits.perfusionIndex  = {1.0f, 5.0f, 3.0f};
            limits.dicroticNotch   = {0.1f, 0.4f, 0.25f};
            break;
            
        case PPGCondition::WEAK_PERFUSION:
            // Reisner 2008: hipovolemia, PI 0.3-2.0%
            limits.heartRate       = {90.0f, 140.0f, 110.0f};
            limits.perfusionIndex  = {0.3f, 2.0f, 0.8f};
            limits.dicroticNotch   = {0.05f, 0.15f, 0.1f};  // Muy reducido
            break;
            
        case PPGCondition::STRONG_PERFUSION:
            // Millasseau 2002: vasodilatación aumenta notch
            limits.heartRate       = {50.0f, 90.0f, 70.0f};
            limits.perfusionIndex  = {10.0f, 20.0f, 12.0f};
            limits.dicroticNotch   = {0.4f, 0.7f, 0.55f};  // Prominente
            break;
            
        case PPGCondition::VASODILATION:
            // Allen 2007: vasodilatación aumenta PI (5-10%)
            limits.heartRate       = {60.0f, 90.0f, 75.0f};
            limits.perfusionIndex  = {5.0f, 10.0f, 7.5f};
            limits.dicroticNotch   = {0.3f, 0.5f, 0.4f};   // Marcado
            break;
            
        case PPGCondition::VASOCONSTRICTION:
            // Shelley 2007: vasoconstricción reduce amplitud y notch
            limits.heartRate       = {70.0f, 110.0f, 85.0f};
            limits.perfusionIndex  = {0.2f, 0.8f, 0.5f};
            limits.dicroticNotch   = {0.05f, 0.15f, 0.1f};  // Muy reducido
            break;
            
        default:
            limits.heartRate       = {60.0f, 100.0f, 75.0f};
            limits.perfusionIndex  = {2.0f, 10.0f, 5.0f};
            limits.dicroticNotch   = {0.2f, 0.5f, 0.35f};
            break;
    }
    
    return limits;
}

// ============================================================================
// LÍMITES DE VARIABILIDAD HR (HRV) POR CONDICIÓN
// Referencias:
//   - Task Force ESC/NASPE 1996: HRV Standards
//   - CV% = (hrStd / hrMean) × 100
//   - Ritmo regular: CV% < 10%
//   - AFib "irregularmente irregular": CV% > 15%
// ============================================================================
struct HRVRange {
    float minVar;      // % mínimo de variabilidad
    float maxVar;      // % máximo de variabilidad
    float defaultVar;  // % por defecto
};

inline HRVRange getHRVLimits(ECGCondition condition) {
    switch (condition) {
        case ECGCondition::NORMAL:
            // Ritmo sinusal regular: baja variabilidad
            return {1.0f, 10.0f, 3.0f};
            
        case ECGCondition::TACHYCARDIA:
            // Taquicardia sinusal: variabilidad reducida
            return {1.0f, 8.0f, 2.0f};
            
        case ECGCondition::BRADYCARDIA:
            // Bradicardia sinusal: variabilidad baja
            return {1.0f, 8.0f, 2.0f};
            
        case ECGCondition::ATRIAL_FIBRILLATION:
            // AFib: DEBE ser irregular (≥15%)
            return {15.0f, 35.0f, 20.0f};
            
        case ECGCondition::VENTRICULAR_FIBRILLATION:
            // VFib: caótico, no aplica slider
            return {30.0f, 50.0f, 40.0f};
            
        case ECGCondition::AV_BLOCK_1:
            // BAV1: ritmo regular
            return {1.0f, 10.0f, 2.0f};
            
        case ECGCondition::ST_ELEVATION:
            // STEMI: puede tener algo de variabilidad
            return {1.0f, 12.0f, 3.0f};
            
        case ECGCondition::ST_DEPRESSION:
            // Isquemia: puede haber taquicardia reactiva
            return {1.0f, 12.0f, 3.0f};
            
        default:
            return {1.0f, 10.0f, 3.0f};
    }
}

// ============================================================================
// LÍMITES GLOBALES [Para validación de entrada serial/UI]
// Constantes absolutas para validación independiente de condición
// ============================================================================
struct GlobalLimits {
    static constexpr float NOISE_MIN = 0.0f;
    static constexpr float NOISE_MAX = 0.10f;   // 10% máximo (cosmético)
    static constexpr float NOISE_DEFAULT = 0.02f;
    
    static constexpr float ZOOM_MIN = 0.5f;     // Zoom visual mínimo
    static constexpr float ZOOM_MAX = 2.0f;     // Zoom visual máximo
    static constexpr float ZOOM_DEFAULT = 1.0f;
    
    static constexpr float HR_ABSOLUTE_MIN = 30.0f;
    static constexpr float HR_ABSOLUTE_MAX = 200.0f;
};

// ============================================================================
// RESUMEN: 4 SLIDERS PARA NEXTION UI
// ============================================================================
// | Slider      | Parámetro    | Rango           | Fuente de límites      |
// |-------------|--------------|-----------------|------------------------|
// | 1. HR       | heartRate    | Dinámico        | getECGLimits()         |
// | 2. Ruido    | noiseLevel   | 0-10%           | GlobalLimits::NOISE_*  |
// | 3. Zoom     | visualGain   | 0.5x-2.0x       | GlobalLimits::ZOOM_*   |
// | 4. Var HR%  | hrVariability| Dinámico        | getHRVLimits()         |
// ============================================================================

#endif // PARAM_LIMITS_H
