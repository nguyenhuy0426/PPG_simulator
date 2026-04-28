/**
 * @file button_handler.cpp
 * @brief Interrupt-driven push button handler implementation
 * @version 1.0.0
 * @date 25 April 2026
 */

#include "hw/button_handler.h"

// ============================================================================
// GLOBAL INSTANCE
// ============================================================================
ButtonHandler buttons;

// ============================================================================
// STATIC MEMBER INITIALIZATION
// ============================================================================
volatile bool ButtonHandler::_modePressed = false;
volatile bool ButtonHandler::_upPressed = false;
volatile bool ButtonHandler::_downPressed = false;
volatile uint32_t ButtonHandler::_lastModeTime = 0;
volatile uint32_t ButtonHandler::_lastUpTime = 0;
volatile uint32_t ButtonHandler::_lastDownTime = 0;

// ============================================================================
// CONSTRUCTOR
// ============================================================================
ButtonHandler::ButtonHandler() {}

// ============================================================================
// INITIALIZATION
// ============================================================================
bool ButtonHandler::begin() {
    // Configure pins as input with internal pull-up (active LOW)
    pinMode(BTN_MODE_PIN, INPUT_PULLUP);
    pinMode(BTN_UP_PIN, INPUT_PULLUP);
    pinMode(BTN_DOWN_PIN, INPUT_PULLUP);

    // Attach falling-edge interrupts (button press = HIGH → LOW)
    attachInterrupt(digitalPinToInterrupt(BTN_MODE_PIN), isrMode, FALLING);
    attachInterrupt(digitalPinToInterrupt(BTN_UP_PIN), isrUp, FALLING);
    attachInterrupt(digitalPinToInterrupt(BTN_DOWN_PIN), isrDown, FALLING);

    Serial.println("[Buttons] Initialized: Mode=GPIO" + String(BTN_MODE_PIN) +
                   " Up=GPIO" + String(BTN_UP_PIN) +
                   " Down=GPIO" + String(BTN_DOWN_PIN));
    return true;
}

// ============================================================================
// ISR HANDLERS (in IRAM)
// ============================================================================
void IRAM_ATTR ButtonHandler::isrMode() {
    uint32_t now = millis();
    if (now - _lastModeTime > BTN_DEBOUNCE_MS) {
        _modePressed = true;
        _lastModeTime = now;
    }
}

void IRAM_ATTR ButtonHandler::isrUp() {
    uint32_t now = millis();
    if (now - _lastUpTime > BTN_DEBOUNCE_MS) {
        _upPressed = true;
        _lastUpTime = now;
    }
}

void IRAM_ATTR ButtonHandler::isrDown() {
    uint32_t now = millis();
    if (now - _lastDownTime > BTN_DEBOUNCE_MS) {
        _downPressed = true;
        _lastDownTime = now;
    }
}

// ============================================================================
// POLLING METHODS (consume event flags)
// ============================================================================
bool ButtonHandler::wasModePressed() {
    if (_modePressed) {
        _modePressed = false;
        return true;
    }
    return false;
}

bool ButtonHandler::wasUpPressed() {
    if (_upPressed) {
        _upPressed = false;
        return true;
    }
    return false;
}

bool ButtonHandler::wasDownPressed() {
    if (_downPressed) {
        _downPressed = false;
        return true;
    }
    return false;
}
