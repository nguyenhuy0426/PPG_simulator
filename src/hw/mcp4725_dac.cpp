/**
 * @file mcp4725_dac.cpp
 * @brief MCP4725 12-bit DAC implementation
 * @version 1.0.0
 * @date 25 April 2026
 */

#include "hw/mcp4725_dac.h"

// ============================================================================
// GLOBAL INSTANCE
// ============================================================================
MCP4725DAC ppgDAC;

// ============================================================================
// CONSTRUCTOR
// ============================================================================
MCP4725DAC::MCP4725DAC() : _ready(false) {}

// ============================================================================
// INITIALIZATION
// ============================================================================
bool MCP4725DAC::begin(uint8_t addr) {
    if (_dac.begin(addr, &Wire)) {
        _ready = true;
        // Set initial output to center (mid-scale)
        setCenter();
        Serial.printf("[MCP4725] DAC initialized at address 0x%02X\n", addr);
        return true;
    }

    Serial.printf("[MCP4725] ERROR: DAC not found at address 0x%02X\n", addr);
    _ready = false;
    return false;
}

// ============================================================================
// OUTPUT CONTROL
// ============================================================================
void MCP4725DAC::setValue(uint16_t value) {
    if (!_ready) return;
    if (value > DAC_MAX_VALUE) value = DAC_MAX_VALUE;
    _dac.setVoltage(value, false);  // false = don't write to EEPROM
}

void MCP4725DAC::setVoltageMV(float mV) {
    if (!_ready) return;
    // Convert mV to 12-bit DAC value: value = mV / 3300 * 4096
    float normalized = mV / (DAC_VOLTAGE_MAX * 1000.0f);
    if (normalized < 0.0f) normalized = 0.0f;
    if (normalized > 1.0f) normalized = 1.0f;
    uint16_t value = (uint16_t)(normalized * 4095.0f);
    _dac.setVoltage(value, false);
}

void MCP4725DAC::setCenter() {
    setValue(DAC_CENTER_VALUE);
}
