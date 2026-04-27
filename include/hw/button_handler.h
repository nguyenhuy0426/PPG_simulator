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
     * @brief Check if Up button was pressed (consumes the event)
     * @return true if pressed since last check
     */
    bool wasUpPressed();

    /**
     * @brief Check if Down button was pressed (consumes the event)
     * @return true if pressed since last check
     */
    bool wasDownPressed();

private:
    // ISR handlers (must be static for attachInterrupt)
    static void IRAM_ATTR isrMode();
    static void IRAM_ATTR isrUp();
    static void IRAM_ATTR isrDown();

    // Volatile flags set by ISRs, consumed by main loop
    static volatile bool _modePressed;
    static volatile bool _upPressed;
    static volatile bool _downPressed;

    // Debounce timestamps
    static volatile uint32_t _lastModeTime;
    static volatile uint32_t _lastUpTime;
    static volatile uint32_t _lastDownTime;
};

// Global instance
extern ButtonHandler buttons;

#endif // BUTTON_HANDLER_H
