/**
 * @file state_machine.h
 * @brief System state machine for PPG Signal Simulator
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Simplified state flow: INIT → SELECT_CONDITION → SIMULATING ↔ PAUSED
 */

#ifndef STATE_MACHINE_H
#define STATE_MACHINE_H

#include <Arduino.h>
#include "data/signal_types.h"

class StateMachine {
private:
    SystemState currentState;
    uint8_t selectedCondition;          // 0–5 (PPGCondition)
    UIEditMode currentEditMode;         // What parameter buttons control

    // State change callback
    void (*onStateChange)(SystemState oldState, SystemState newState);

public:
    StateMachine();

    /**
     * @brief Process a system event
     * @param event The event to process
     * @param param Optional event parameter
     */
    void processEvent(SystemEvent event, uint8_t param = 0);

    // Getters
    SystemState getState() const { return currentState; }
    uint8_t getSelectedCondition() const { return selectedCondition; }
    UIEditMode getEditMode() const { return currentEditMode; }

    // Setters
    void setSelectedCondition(uint8_t cond) { selectedCondition = cond; }
    void setEditMode(UIEditMode mode) { currentEditMode = mode; }

    // Callback
    void setStateChangeCallback(void (*callback)(SystemState, SystemState));

    // Utility
    static const char* stateToString(SystemState state);
    static const char* eventToString(SystemEvent event);
    static const char* editModeToString(UIEditMode mode);
};

#endif // STATE_MACHINE_H
