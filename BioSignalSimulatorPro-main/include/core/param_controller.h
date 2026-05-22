/**
 * @file param_controller.h
 * @brief Controlador de parámetros con aplicación diferida
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Gestiona parámetros Tipo A (inmediatos) y Tipo B (diferidos).
 */

#ifndef PARAM_CONTROLLER_H
#define PARAM_CONTROLLER_H

#include <Arduino.h>
#include "../data/signal_types.h"
#include "../data/param_limits.h"

// ============================================================================
// TIPOS DE PARÁMETROS
// ============================================================================
enum class ParamType : uint8_t {
    IMMEDIATE,      // Tipo A: Se aplica inmediatamente
    DEFERRED        // Tipo B: Se aplica en próximo ciclo
};

// ============================================================================
// ESTRUCTURA DE PARÁMETRO PENDIENTE
// ============================================================================
template<typename T>
struct PendingParam {
    bool hasPending;
    T pendingValue;
    unsigned long requestTime;
    
    PendingParam() : hasPending(false), requestTime(0) {}
};

// ============================================================================
// CLASE ParamController
// ============================================================================
class ParamController {
private:
    // Parámetros actuales
    ECGParameters currentECG;
    EMGParameters currentEMG;
    PPGParameters currentPPG;
    
    // Parámetros pendientes
    PendingParam<ECGParameters> pendingECG;
    PendingParam<EMGParameters> pendingEMG;
    PendingParam<PPGParameters> pendingPPG;
    
    // Tipo de señal actual
    SignalType activeSignalType;
    
    // Helpers
    float clamp(float value, float min, float max);
    bool validateECGParams(const ECGParameters& params);
    bool validateEMGParams(const EMGParameters& params);
    bool validatePPGParams(const PPGParameters& params);
    
public:
    ParamController();
    
    // Establecer tipo de señal activa
    void setActiveSignal(SignalType type, uint8_t condition);
    
    // === PARÁMETROS TIPO A (Inmediatos) ===
    void setNoiseLevel(float noise);
    void setAmplitude(float amplitude);
    void setSTShift(float shift);           // Solo ECG
    void setDicroticNotch(float notch);     // Solo PPG
    
    // === PARÁMETROS TIPO B (Diferidos) ===
    void setHeartRate(float hr);            // ECG, PPG
    void setCondition(uint8_t condition);   // Todos
    void setExcitationLevel(float level);   // Solo EMG
    void setHRVariability(float hrv);       // Solo ECG
    void setPerfusionIndex(float pi);       // Solo PPG
    
    // Aplicar parámetros pendientes (llamar en fin de ciclo)
    bool applyPendingParams();
    bool hasPendingParams() const;
    
    // Getters
    ECGParameters getECGParams() const { return currentECG; }
    EMGParameters getEMGParams() const { return currentEMG; }
    PPGParameters getPPGParams() const { return currentPPG; }
    
    // Obtener límites para UI
    ECGLimits getCurrentECGLimits() const;
    EMGLimits getCurrentEMGLimits() const;
    PPGLimits getCurrentPPGLimits() const;
    
    // Reset a defaults de condición
    void resetToDefaults();
};

#endif // PARAM_CONTROLLER_H
