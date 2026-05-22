/**
 * @file signal_types.h
 * @brief Definición de tipos de señales y sus estructuras
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Enumeraciones y estructuras para ECG, EMG y PPG.
 * Los rangos exactos por condición están en param_limits.h
 */

#ifndef SIGNAL_TYPES_H
#define SIGNAL_TYPES_H

#include <Arduino.h>

// ============================================================================
// TIPOS DE SEÑALES
// ============================================================================
enum class SignalType : uint8_t {
    NONE = 0,
    ECG  = 1,
    EMG  = 2,
    PPG  = 3
};

// ============================================================================
// ESTADOS DE SEÑAL
// ============================================================================
enum class SignalState : uint8_t {
    STOPPED  = 0,
    RUNNING  = 1,
    PAUSED   = 2,
    ERROR    = 3
};

// ============================================================================
// CONDICIONES ECG (8 condiciones)
// ============================================================================
enum class ECGCondition : uint8_t {
    NORMAL = 0,                     // Ritmo sinusal normal (60-100 BPM, <10% var)
    TACHYCARDIA,                    // Taquicardia sinusal (>100 BPM)
    BRADYCARDIA,                    // Bradicardia sinusal (<60 BPM)
    ATRIAL_FIBRILLATION,            // Fibrilación auricular (RR irregular, sin P)
    VENTRICULAR_FIBRILLATION,       // Fibrilación ventricular (caótico)
    AV_BLOCK_1,                     // Bloqueo AV 1º grado (PR > 200 ms)
    ST_ELEVATION,                   // Elevación ST (STEMI)
    ST_DEPRESSION,                  // Depresión ST (isquemia)
    
    COUNT = 8                       // Total de condiciones
};

// ============================================================================
// CONDICIONES EMG (6 condiciones - solo sEMG)
// ============================================================================
/**
 * REFACTORIZACIÓN v2.0: Eliminadas patologías de aguja (MYOPATHY, NEUROPATHY, FASCICULATION)
 * 
 * JUSTIFICACIÓN:
 * - sEMG (surface EMG) tiene atenuación ~50-70% vs needle EMG
 * - Patologías de aguja requieren amplitudes >5 mV (fuera de rango sEMG)
 * - Se mantienen solo condiciones observables en superficie
 * 
 * RANGOS sEMG:
 * - REST:     0-5% MVC   (RMS 0.02-0.05 mV)
 * - LOW:      5-20% MVC  (RMS 0.1-0.2 mV)
 * - MODERATE: 20-50% MVC (RMS 0.3-0.8 mV)
 * - HIGH:     50-100% MVC (RMS 1-5 mV)
 * - TREMOR:   Modulación 5 Hz (RMS 0.1-0.5 mV)
 * - FATIGUE:  50% MVC sostenido, RMS decay 1.5→0.4 mV, MDF 120→80 Hz
 * 
 * Refs: De Luca 1997, Cifrek 2009, Sun 2022
 */
enum class EMGCondition : uint8_t {
    // Niveles de contracción (% MVC)
    REST = 0,                       // Reposo (0-5% MVC)
    LOW_CONTRACTION,                // Baja (5-20% MVC)
    MODERATE_CONTRACTION,           // Moderada (20-50% MVC)
    HIGH_CONTRACTION,               // Alta (50-100% MVC)
    
    // Condiciones especiales sEMG
    TREMOR,                         // Temblor Parkinsoniano 4-6 Hz
    FATIGUE,                        // Fatiga muscular (protocolo 50% MVC sostenido)
    
    COUNT = 6                       // Total de condiciones
};

// ============================================================================
// CONDICIONES PPG (6 condiciones)
// Basado en Allen J. Physiol Meas. 2007;28(3):R1-R39
//          Lima A, Bakker J. Intensive Care Med. 2005;31(10):1316-1326
//          Jubran A. Crit Care. 2015;19:272
// 
// PI es un valor dinámico con variabilidad gaussiana natural.
// ============================================================================
enum class PPGCondition : uint8_t {
    NORMAL = 0,                     // PI 1-5%, morfología estándar con muesca dicrótica
    ARRHYTHMIA,                     // PI 1-5%, RR muy variable (±15%), morfología similar a normal
    WEAK_PERFUSION,                 // PI 0.02-0.4%, señal muy débil, muesca desaparecida
    VASOCONSTRICTION,               // PI 0.2-0.8%, pico pequeño, muesca apenas perceptible, onda afilada
    STRONG_PERFUSION,               // PI 10-20%, señal muy robusta, muesca prominente
    VASODILATION,                   // PI 5-10%, pico alto, muesca marcada, diástole bien definida
    
    COUNT = 6                       // Total de condiciones
};

// ============================================================================
// PARÁMETROS ECG
// Rangos varían por condición - ver param_limits.h para detalles
// ============================================================================
struct ECGParameters {
    float heartRate;                // BPM (30-500, varía por condición)
    float pWaveAmplitude;           // Factor P (0.0-2.0, 0 en AFib/VFib/PVC)
    float qrsAmplitude;             // Factor QRS (0.5-2.5, varía por condición)
    float tWaveAmplitude;           // Factor T (0.3-2.0, varía por condición)
    float stShift;                  // Desplazamiento ST en mV (-0.3 a +0.4)
    float noiseLevel;               // Nivel de ruido (0.0-1.0)
    ECGCondition condition;         // Condición actual
    
    // Constructor con valores por defecto
    // heartRate=0 significa "usar HR de la condición" (setXXXMorphology)
    ECGParameters() :
        heartRate(0.0f),           // 0 = usar HR de la condición
        pWaveAmplitude(1.0f),
        qrsAmplitude(1.0f),
        tWaveAmplitude(1.0f),
        stShift(0.0f),
        noiseLevel(0.0f),          // Sin ruido por defecto
        condition(ECGCondition::NORMAL)
    {}
};

// ============================================================================
// PARÁMETROS EMG
// Rangos varían por condición - ver param_limits.h para detalles
// ============================================================================
struct EMGParameters {
    float excitationLevel;          // Nivel de excitación (0.0-1.0, varía por condición)
    float amplitude;                // Amplitud relativa (0.1-3.0, varía por condición)
    float noiseLevel;               // Nivel de ruido (0.0-1.0)
    EMGCondition condition;         // Condición actual
    
    // Constructor con valores por defecto
    EMGParameters() :
        excitationLevel(0.0f),
        amplitude(1.0f),
        noiseLevel(0.0f),          // Sin ruido por defecto
        condition(EMGCondition::REST)
    {}
};

// ============================================================================
// SISTEMA DE SECUENCIAS DINÁMICAS EMG
// ============================================================================

/**
 * @brief Evento de una secuencia EMG (cambio de estado)
 */
struct EMGSequenceEvent {
    float timeStart;        // Tiempo de inicio (segundos)
    float duration;         // Duración del evento (segundos)
    EMGCondition condition; // Condición durante el evento
    float excitationLevel;  // Nivel de excitación (0-1), 0 = usar default de condición
};

/**
 * @brief Tipo de secuencia predefinida
 */
enum class EMGSequenceType : uint8_t {
    STATIC = 0,              // Condición fija (modo actual)
    REST_TO_LOW,             // Reposo → Contracción leve → Reposo
    REST_TO_MODERATE,        // Reposo → Contracción moderada → Reposo
    REST_TO_HIGH,            // Reposo → Contracción alta → Reposo
    PROGRESSIVE,             // Reposo → Leve → Moderada → Alta → Reposo
    TREMOR_CONTINUOUS,       // Temblor continuo con modulación
    FATIGUE_PROTOCOL,        // Protocolo de fatiga (contracción sostenida)
    CUSTOM                   // Secuencia personalizada
};

/**
 * @brief Definición completa de secuencia (máximo 10 eventos)
 */
struct EMGSequence {
    EMGSequenceType type;
    int numEvents;
    EMGSequenceEvent events[10];
    bool loop;                     // ¿Repetir al terminar?
};

// ============================================================================
// PARÁMETROS PPG
// Rangos varían por condición - ver param_limits.h para detalles
// ============================================================================
struct PPGParameters {
    float heartRate;                // BPM (50-150, varía por condición)
    float perfusionIndex;           // Índice de perfusión % (0.3-20.0, varía por condición)
    float dicroticNotch;            // Muesca dicrótica (0.0-0.7, varía por condición)
    float noiseLevel;               // Nivel de ruido (0.0-1.0)
    float amplification;            // Factor de amplificación (0.5-2.0, multiplica señal)
    PPGCondition condition;         // Condición actual
    
    // Constructor con valores por defecto
    PPGParameters() :
        heartRate(75.0f),
        perfusionIndex(5.0f),
        dicroticNotch(0.3f),
        noiseLevel(0.0f),          // Sin ruido por defecto
        amplification(1.0f),
        condition(PPGCondition::NORMAL)
    {}
};

// ============================================================================
// ESTRUCTURA DE DATOS DE SEÑAL
// ============================================================================
struct SignalData {
    SignalType type;
    SignalState state;
    uint32_t sampleCount;
    unsigned long lastUpdateTime;
    
    // Parámetros por tipo (sin union para evitar problemas con constructores)
    ECGParameters ecg;
    EMGParameters emg;
    PPGParameters ppg;
    
    SignalData() : 
        type(SignalType::NONE),
        state(SignalState::STOPPED),
        sampleCount(0),
        lastUpdateTime(0),
        ecg(),
        emg(),
        ppg()
    {}
};

// ============================================================================
// FUNCIONES DE CONVERSIÓN A STRING
// ============================================================================
inline const char* signalTypeToString(SignalType type) {
    switch (type) {
        case SignalType::ECG: return "ECG";
        case SignalType::EMG: return "EMG";
        case SignalType::PPG: return "PPG";
        default: return "NONE";
    }
}

inline const char* signalStateToString(SignalState state) {
    switch (state) {
        case SignalState::RUNNING: return "RUNNING";
        case SignalState::PAUSED:  return "PAUSED";
        case SignalState::STOPPED: return "STOPPED";
        case SignalState::ERROR:   return "ERROR";
        default: return "UNKNOWN";
    }
}

inline const char* ecgConditionToString(ECGCondition cond) {
    switch (cond) {
        case ECGCondition::NORMAL:                  return "Normal";
        case ECGCondition::TACHYCARDIA:             return "Taquicardia";
        case ECGCondition::BRADYCARDIA:             return "Bradicardia";
        case ECGCondition::ATRIAL_FIBRILLATION:     return "Fib. Auricular";
        case ECGCondition::VENTRICULAR_FIBRILLATION:return "Fib. Ventricular";
        case ECGCondition::AV_BLOCK_1:              return "BAV1";
        case ECGCondition::ST_ELEVATION:            return "ST Elevado";
        case ECGCondition::ST_DEPRESSION:           return "ST Deprimido";
        default: return "Desconocido";
    }
}

inline const char* emgConditionToString(EMGCondition cond) {
    switch (cond) {
        case EMGCondition::REST:                 return "Reposo";
        case EMGCondition::LOW_CONTRACTION:      return "Baja";
        case EMGCondition::MODERATE_CONTRACTION: return "Moderada";
        case EMGCondition::HIGH_CONTRACTION:     return "Alta";
        case EMGCondition::TREMOR:               return "Temblor";
        case EMGCondition::FATIGUE:              return "Fatiga";
        default: return "Desconocido";
    }
}

inline const char* ppgConditionToString(PPGCondition cond) {
    switch (cond) {
        case PPGCondition::NORMAL:           return "Normal";
        case PPGCondition::ARRHYTHMIA:       return "Arritmia";
        case PPGCondition::WEAK_PERFUSION:   return "Perfusion Debil";
        case PPGCondition::VASODILATION:     return "Vasodilatacion";
        case PPGCondition::STRONG_PERFUSION: return "Perfusion Fuerte";
        case PPGCondition::VASOCONSTRICTION: return "Vasoconstriccion";
        default: return "Desconocido";
    }
}

#endif // SIGNAL_TYPES_H
