/**
 * @file button_handler.h
 * @brief Interrupt-driven push button handler with debouncing
 * @version 1.0.0
 * @date 25 April 2026
 *
 * Handles 3 physical buttons (Mode, Up, Down) using GPIO interrupts.
 * Active-LOW with internal pull-ups. 200ms debounce.
 */

#ifndef BUTTON_HANDLER_H
#define BUTTON_HANDLER_H

#include <Arduino.h>
#include "../config.h"

class ButtonHandler {
public:
    ButtonHandler();

    /**
     * @brief Initialize button GPIO pins and attach interrupts
     * @return true if initialization successful
     */
    bool begin();

    /**
     * @brief Check if Mode button was pressed (consumes the event)
     * @return true if pressed since last check
     */
    bool wasModePressed();

    /**
     * @brief Get the smoothed analog value from the potentiometer
     * @return 12-bit ADC value (0-4095)
     */
    uint16_t getPotValue();

private:
    // ISR handler (must be static for attachInterrupt)
    static void IRAM_ATTR isrMode();

    // Volatile flag set by ISR, consumed by main loop
    static volatile bool _modePressed;

    // Debounce timestamp
    static volatile uint32_t _lastModeTime;
    
    // Potentiometer smoothing filter
    float _potSmoothedValue;
};

// Global instance
extern ButtonHandler buttons;

#endif // BUTTON_HANDLER_H
