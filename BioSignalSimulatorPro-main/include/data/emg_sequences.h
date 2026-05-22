/**
 * @file emg_sequences.h
 * @brief Estados EMG estáticos para control manual desde Nextion
 * @version 2.0.0
 * 
 * CAMBIO CRÍTICO v2.0:
 * Las "secuencias" ahora son ESTADOS ESTÁTICOS que permanecen indefinidamente
 * hasta que el usuario cambie manualmente desde la interfaz Nextion.
 * 
 * ELIMINADO: Transiciones automáticas con duraciones fijas
 * RAZÓN: En simulador tiempo real, la pantalla no puede "terminar" después de X segundos
 */

#ifndef EMG_SEQUENCES_H
#define EMG_SEQUENCES_H

#include "signal_types.h"

// ============================================================================
// NOTA: El sistema de secuencias se mantiene para compatibilidad,
// pero TODAS las "secuencias" son ahora ESTADOS ESTÁTICOS de 1 evento infinito
// ============================================================================

/**
 * @brief Estado: Reposo continuo
 * Permanece en reposo hasta cambio manual
 */
const EMGSequence SEQ_REST_STATIC = {
    .type = EMGSequenceType::STATIC,
    .numEvents = 1,
    .events = {
        {0.0f, 9999.0f, EMGCondition::REST, 0.0f}  // Infinito hasta cambio manual
    },
    .loop = false  // No necesita loop, ya es infinito
};

/**
 * @brief Estado: Contracción leve continua
 * Permanece en contracción leve hasta cambio manual
 */
const EMGSequence SEQ_LOW_STATIC = {
    .type = EMGSequenceType::STATIC,
    .numEvents = 1,
    .events = {
        {0.0f, 9999.0f, EMGCondition::LOW_CONTRACTION, 0.0f}
    },
    .loop = false
};

/**
 * @brief Estado: Contracción moderada continua
 * Permanece en contracción moderada hasta cambio manual
 */
const EMGSequence SEQ_MODERATE_STATIC = {
    .type = EMGSequenceType::STATIC,
    .numEvents = 1,
    .events = {
        {0.0f, 9999.0f, EMGCondition::MODERATE_CONTRACTION, 0.0f}
    },
    .loop = false
};

/**
 * @brief Estado: Contracción alta continua
 * Permanece en contracción alta hasta cambio manual
 */
const EMGSequence SEQ_HIGH_STATIC = {
    .type = EMGSequenceType::STATIC,
    .numEvents = 1,
    .events = {
        {0.0f, 9999.0f, EMGCondition::HIGH_CONTRACTION, 0.0f}
    },
    .loop = false
};

/**
 * @brief Estado: Temblor continuo
 * Permanece en temblor hasta cambio manual
 */
const EMGSequence SEQ_TREMOR_STATIC = {
    .type = EMGSequenceType::STATIC,
    .numEvents = 1,
    .events = {
        {0.0f, 9999.0f, EMGCondition::TREMOR, 0.0f}
    },
    .loop = false
};

/**
 * @brief Estado: Fatiga continua
 * Permanece en fatiga (con decay progresivo) hasta cambio manual
 */
const EMGSequence SEQ_FATIGUE_STATIC = {
    .type = EMGSequenceType::STATIC,
    .numEvents = 1,
    .events = {
        {0.0f, 9999.0f, EMGCondition::FATIGUE, 0.0f}
    },
    .loop = false
};

// ============================================================================
// SECUENCIAS DINÁMICAS - Ciclos REST → CONTRACCIÓN
// ============================================================================
// Ciclos de 4 segundos optimizados para visualización en Nextion (50 Hz)
// Permite ver 3-4 bursts de contracción en una ventana de 15 segundos

/**
 * @brief Secuencia dinámica: REST → LOW → REST → LOW (loop)
 * Muestra claramente la diferencia en envelope entre reposo y contracción leve
 * 
 * Ciclo de 4s: REST 1s + LOW 3s
 * RMS: 0.001 mV (reposo) → 0.52 mV (contracción) → 0.001 mV
 */
const EMGSequence SEQ_LOW_DYNAMIC = {
    .type = EMGSequenceType::REST_TO_LOW,
    .numEvents = 2,
    .events = {
        {0.0f,  1.0f, EMGCondition::REST,           0.0f},  // 0-1s: Reposo
        {1.0f,  3.0f, EMGCondition::LOW_CONTRACTION, 0.0f}  // 1-4s: Contracción leve (3s)
    },
    .loop = true  // Repetir indefinidamente
};

/**
 * @brief Secuencia dinámica: REST → MODERATE → REST → MODERATE (loop)
 * Muestra claramente la diferencia en envelope entre reposo y contracción moderada
 * 
 * Ciclo de 4s: REST 1s + MODERATE 3s
 * RMS: 0.001 mV (reposo) → 1.7 mV (contracción) → 0.001 mV
 */
const EMGSequence SEQ_MODERATE_DYNAMIC = {
    .type = EMGSequenceType::REST_TO_MODERATE,
    .numEvents = 2,
    .events = {
        {0.0f,  1.0f, EMGCondition::REST,                0.0f},  // 0-1s: Reposo
        {1.0f,  3.0f, EMGCondition::MODERATE_CONTRACTION, 0.0f}  // 1-4s: Contracción moderada (3s)
    },
    .loop = true
};

/**
 * @brief Secuencia dinámica: REST → HIGH → REST → HIGH (loop)
 * Muestra claramente la diferencia en envelope entre reposo y contracción alta
 * 
 * Ciclo de 4s: REST 1s + HIGH 3s
 * RMS: 0.001 mV (reposo) → 2.8 mV (contracción) → 0.001 mV
 */
const EMGSequence SEQ_HIGH_DYNAMIC = {
    .type = EMGSequenceType::REST_TO_HIGH,
    .numEvents = 2,
    .events = {
        {0.0f,  1.0f, EMGCondition::REST,             0.0f},  // 0-1s: Reposo
        {1.0f,  3.0f, EMGCondition::HIGH_CONTRACTION, 0.0f}   // 1-4s: Contracción alta (3s)
    },
    .loop = true
};

// ============================================================================
// CONTROL DESDE NEXTION - EJEMPLO
// ============================================================================
/*
void onNextionButton(String btn) {
    if (btn == "btn_rest") {
        emgModel.startSequence(SEQ_REST_STATIC);
    }
    else if (btn == "btn_low") {
        emgModel.startSequence(SEQ_LOW_STATIC);
    }
    else if (btn == "btn_moderate") {
        emgModel.startSequence(SEQ_MODERATE_STATIC);
    }
    else if (btn == "btn_high") {
        emgModel.startSequence(SEQ_HIGH_STATIC);
    }
    else if (btn == "btn_tremor") {
        emgModel.startSequence(SEQ_TREMOR_STATIC);
    }
    else if (btn == "btn_fatigue") {
        emgModel.startSequence(SEQ_FATIGUE_STATIC);
    }
}
*/

#endif // EMG_SEQUENCES_H
