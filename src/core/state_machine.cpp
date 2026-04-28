/**
 * @file state_machine.cpp
 * @brief System state machine implementation
 * @version 2.0.0
 * @date 25 April 2026
 *
 * State flow: INIT → SELECT_CONDITION → SIMULATING ↔ PAUSED
 */

#include "core/state_machine.h"

// ============================================================================
// CONSTRUCTOR
// ============================================================================
StateMachine::StateMachine() {
    currentState = SystemState::INIT;
    selectedCondition = 0;  // Default: Normal
    currentEditMode = UIEditMode::CONDITION_SELECT;
    onStateChange = nullptr;
}

// ============================================================================
// PROCESS EVENTS
// ============================================================================
void StateMachine::processEvent(SystemEvent event, uint8_t param) {
    SystemState oldState = currentState;
    SystemState newState = currentState;

    switch (currentState) {
        case SystemState::INIT:
            if (event == SystemEvent::INIT_COMPLETE) {
                newState = SystemState::SELECT_CONDITION;
            }
            break;

        case SystemState::SELECT_CONDITION:
            switch (event) {
                case SystemEvent::SELECT_CONDITION:
                    selectedCondition = param;
                    break;
                case SystemEvent::START_SIMULATION:
                    newState = SystemState::SIMULATING;
                    break;
                case SystemEvent::BTN_MODE_PRESS:
                    // In condition select, mode starts simulation
                    newState = SystemState::SIMULATING;
                    break;
                case SystemEvent::BTN_UP_PRESS:
                    // Next condition
                    selectedCondition = (selectedCondition + 1) % (uint8_t)PPGCondition::COUNT;
                    break;
                case SystemEvent::BTN_DOWN_PRESS:
                    // Previous condition
                    if (selectedCondition == 0)
                        selectedCondition = (uint8_t)PPGCondition::COUNT - 1;
                    else
                        selectedCondition--;
                    break;
                default:
                    break;
            }
            break;

        case SystemState::SIMULATING:
            switch (event) {
                case SystemEvent::BTN_MODE_PRESS:
                    // Cycle edit mode
                    currentEditMode = (UIEditMode)(((uint8_t)currentEditMode + 1) % (uint8_t)UIEditMode::COUNT);
                    break;
                case SystemEvent::PAUSE:
                    newState = SystemState::PAUSED;
                    break;
                case SystemEvent::STOP:
                    newState = SystemState::SELECT_CONDITION;
                    currentEditMode = UIEditMode::CONDITION_SELECT;
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
                case SystemEvent::BTN_MODE_PRESS:
                    // Resume on mode press
                    newState = SystemState::SIMULATING;
                    break;
                case SystemEvent::STOP:
                    newState = SystemState::SELECT_CONDITION;
                    currentEditMode = UIEditMode::CONDITION_SELECT;
                    break;
                default:
                    break;
            }
            break;

        case SystemState::ERROR:
            if (event == SystemEvent::INIT_COMPLETE) {
                newState = SystemState::SELECT_CONDITION;
            }
            break;
    }

    // Notify state change
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
// STRING CONVERSION
// ============================================================================
const char* StateMachine::stateToString(SystemState state) {
    switch (state) {
        case SystemState::INIT:              return "INIT";
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
        case SystemEvent::BTN_MODE_PRESS:    return "BTN_MODE";
        case SystemEvent::BTN_UP_PRESS:      return "BTN_UP";
        case SystemEvent::BTN_DOWN_PRESS:    return "BTN_DOWN";
        case SystemEvent::SELECT_CONDITION:  return "SELECT_CONDITION";
        case SystemEvent::START_SIMULATION:  return "START_SIMULATION";
        case SystemEvent::PAUSE:             return "PAUSE";
        case SystemEvent::RESUME:            return "RESUME";
        case SystemEvent::STOP:              return "STOP";
        case SystemEvent::ERROR_OCCURRED:    return "ERROR";
        default:                             return "UNKNOWN";
    }
}

const char* StateMachine::editModeToString(UIEditMode mode) {
    switch (mode) {
        case UIEditMode::CONDITION_SELECT:   return "Condition";
        case UIEditMode::EDIT_HR:            return "Heart Rate";
        case UIEditMode::EDIT_PI:            return "Perf. Index";
        case UIEditMode::EDIT_NOISE:         return "Noise";
        default:                             return "Unknown";
    }
}
