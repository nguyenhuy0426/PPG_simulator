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
volatile uint32_t ButtonHandler::_lastModeTime = 0;

// ============================================================================
// CONSTRUCTOR
// ============================================================================
ButtonHandler::ButtonHandler() : _potSmoothedValue(0.0f) {}

// ============================================================================
// INITIALIZATION
// ============================================================================
bool ButtonHandler::begin() {
  // Configure pins as input with internal pull-up (active LOW)
  pinMode(BTN_MODE_PIN, INPUT_PULLUP);
  
  // Configure ADC for potentiometer
  // ESP32-S3 default ADC resolution is 12 bits (0-4095)
  analogReadResolution(12);
  
  // Initialize smoothed value
  _potSmoothedValue = analogRead(POT_PIN);

  // Attach falling-edge interrupts (button press = HIGH → LOW)
  attachInterrupt(digitalPinToInterrupt(BTN_MODE_PIN), isrMode, FALLING);

  Serial.println("[Buttons] Initialized: Mode=GPIO" + String(BTN_MODE_PIN) +
                 " POT=GPIO" + String(POT_PIN));
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

uint16_t ButtonHandler::getPotValue() {
    uint16_t raw = analogRead(POT_PIN);
    // Exponential Moving Average filter (alpha = 0.2)
    _potSmoothedValue = 0.8f * _potSmoothedValue + 0.2f * (float)raw;
    return (uint16_t)_potSmoothedValue;
}
