/**
 * @file state_machine.cpp
 * @brief Implementación de la máquina de estados
 * @version 1.0.0
 * @date 18 Diciembre 2025
 * 
 * Flujo: INIT → PORTADA → MENU → SELECT_CONDITION → SIMULATING
 *        (portada)  (menu)  (ecg_sim/emg_sim/ppg_sim)  (ecg_wave/emg_wave/ppg_wave)
 */

#include "core/state_machine.h"

// ============================================================================
// CONSTRUCTOR
// ============================================================================
StateMachine::StateMachine() {
    currentState = SystemState::INIT;
    selectedSignal = SignalType::NONE;
    selectedCondition = 0xFF; // sin selección
    onStateChange = nullptr;
}

// ============================================================================
// PROCESAR EVENTOS
// ============================================================================
void StateMachine::processEvent(SystemEvent event, uint8_t param) {
    SystemState oldState = currentState;
    SystemState newState = currentState;
    
    switch (currentState) {
        case SystemState::INIT:
            if (event == SystemEvent::INIT_COMPLETE) {
                newState = SystemState::PORTADA;
            }
            break;
            
        case SystemState::PORTADA:
            if (event == SystemEvent::GO_TO_MENU) {
                newState = SystemState::MENU;
            }
            break;
            
        case SystemState::MENU:
            switch (event) {
                case SystemEvent::SELECT_ECG:
                    selectedSignal = SignalType::ECG;
                    selectedCondition = 0xFF;
                    break;
                case SystemEvent::SELECT_EMG:
                    selectedSignal = SignalType::EMG;
                    selectedCondition = 0xFF;
                    break;
                case SystemEvent::SELECT_PPG:
                    selectedSignal = SignalType::PPG;
                    selectedCondition = 0xFF;
                    break;
                case SystemEvent::GO_TO_CONDITION:
                    if (selectedSignal != SignalType::NONE) {
                        selectedCondition = 0xFF;  // sin selección
                        newState = SystemState::SELECT_CONDITION;
                    }
                    break;
                case SystemEvent::BACK:
                    selectedSignal = SignalType::NONE;
                    selectedCondition = 0xFF;
                    newState = SystemState::PORTADA;
                    break;
                default:
                    break;
            }
            break;
            
        case SystemState::SELECT_CONDITION:
            switch (event) {
                case SystemEvent::SELECT_CONDITION:
                    selectedCondition = param;  // 0-8 para ECG
                    break;
                case SystemEvent::GO_TO_WAVEFORM:
                    newState = SystemState::SIMULATING;
                    break;
                case SystemEvent::BACK:
                    newState = SystemState::MENU;
                    break;
                default:
                    break;
            }
            break;
            
        case SystemState::SIMULATING:
            switch (event) {
                case SystemEvent::SELECT_CONDITION:
                    // Cambio de condición durante simulación
                    selectedCondition = param;
                    break;
                case SystemEvent::PAUSE:
                    newState = SystemState::PAUSED;
                    break;
                case SystemEvent::STOP:
                case SystemEvent::BACK:
                    newState = SystemState::SELECT_CONDITION;
                    break;
                default:
                    break;
            }
            break;
            
        case SystemState::PAUSED:
            switch (event) {
                case SystemEvent::RESUME:
                    newState = SystemState::SIMULATING;
                    break;
                case SystemEvent::STOP:
                case SystemEvent::BACK:
                    newState = SystemState::SELECT_CONDITION;
                    break;
                default:
                    break;
            }
            break;
            
        case SystemState::ERROR:
            if (event == SystemEvent::INIT_COMPLETE) {
                newState = SystemState::PORTADA;
            }
            break;
    }
    
    // Notificar cambio de estado
    if (newState != oldState) {
        currentState = newState;
        if (onStateChange != nullptr) {
            onStateChange(oldState, newState);
        }
    }
}

// ============================================================================
// CALLBACK
// ============================================================================
void StateMachine::setStateChangeCallback(void (*callback)(SystemState, SystemState)) {
    onStateChange = callback;
}

// ============================================================================
// CONVERSIÓN A STRING
// ============================================================================
const char* StateMachine::stateToString(SystemState state) {
    switch (state) {
        case SystemState::INIT:              return "INIT";
        case SystemState::PORTADA:           return "PORTADA";
        case SystemState::MENU:              return "MENU";
        case SystemState::SELECT_CONDITION:  return "SELECT_CONDITION";
        case SystemState::SIMULATING:        return "SIMULATING";
        case SystemState::PAUSED:            return "PAUSED";
        case SystemState::ERROR:             return "ERROR";
        default:                             return "UNKNOWN";
    }
}

const char* StateMachine::eventToString(SystemEvent event) {
    switch (event) {
        case SystemEvent::INIT_COMPLETE:     return "INIT_COMPLETE";
        case SystemEvent::GO_TO_MENU:        return "GO_TO_MENU";
        case SystemEvent::SELECT_ECG:        return "SELECT_ECG";
        case SystemEvent::SELECT_EMG:        return "SELECT_EMG";
        case SystemEvent::SELECT_PPG:        return "SELECT_PPG";
        case SystemEvent::GO_TO_CONDITION:   return "GO_TO_CONDITION";
        case SystemEvent::SELECT_CONDITION:  return "SELECT_CONDITION";
        case SystemEvent::GO_TO_WAVEFORM:    return "GO_TO_WAVEFORM";
        case SystemEvent::START_SIMULATION:  return "START_SIMULATION";
        case SystemEvent::PAUSE:             return "PAUSE";
        case SystemEvent::RESUME:            return "RESUME";
        case SystemEvent::STOP:              return "STOP";
        case SystemEvent::ERROR_OCCURRED:    return "ERROR_OCCURRED";
        case SystemEvent::BACK:              return "BACK";
        default:                             return "UNKNOWN";
    }
}
