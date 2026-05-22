/**
 * @file state_machine.h
 * @brief Máquina de estados del sistema
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Gestiona las transiciones de estado de la aplicación.
 */

#ifndef STATE_MACHINE_H
#define STATE_MACHINE_H

#include <Arduino.h>
#include "../data/signal_types.h"

// ============================================================================
// ESTADOS DEL SISTEMA
// ============================================================================
enum class SystemState : uint8_t {
    INIT,               // Inicializando
    PORTADA,            // En pantalla de bienvenida
    MENU,               // En menú de selección de señal
    SELECT_CONDITION,   // Seleccionando condición (ecg_sim/emg_sim/ppg_sim)
    SIMULATING,         // Generando señal (en ecg_wave/emg_wave/ppg_wave)
    PAUSED,             // Señal pausada
    ERROR               // Error del sistema
};

// ============================================================================
// EVENTOS DEL SISTEMA
// ============================================================================
enum class SystemEvent : uint8_t {
    INIT_COMPLETE,
    GO_TO_MENU,         // bt_comenzar en portada
    SELECT_ECG,
    SELECT_EMG,
    SELECT_PPG,
    GO_TO_CONDITION,    // bt_ir en menu → ir a ecg_sim/emg_sim/ppg_sim
    SELECT_CONDITION,   // Seleccionar condición (param = 0-8 para ECG)
    GO_TO_WAVEFORM,     // bt_ir en ecg_sim → ir a ecg_wave
    START_SIMULATION,
    PAUSE,
    RESUME,
    STOP,
    ERROR_OCCURRED,
    BACK
};

// ============================================================================
// CLASE StateMachine
// ============================================================================
class StateMachine {
private:
    SystemState currentState;
    SignalType selectedSignal;
    uint8_t selectedCondition;
    
    // Callback para notificar cambios
    void (*onStateChange)(SystemState oldState, SystemState newState);
    
public:
    StateMachine();
    
    // Procesar eventos
    void processEvent(SystemEvent event, uint8_t param = 0);
    
    // Getters
    SystemState getState() const { return currentState; }
    SignalType getSelectedSignal() const { return selectedSignal; }
    uint8_t getSelectedCondition() const { return selectedCondition; }
    
    // Callback
    void setStateChangeCallback(void (*callback)(SystemState, SystemState));
    
    // Debug
    const char* stateToString(SystemState state);
    const char* eventToString(SystemEvent event);
};

#endif // STATE_MACHINE_H
