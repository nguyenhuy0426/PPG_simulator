/**
 * @file dac_manager.cpp
 * @brief Manager for dual MCP4725 DACs implementation
 * @version 2.0.0
 * @date 25 April 2026
 */

#include "hw/dac_manager.h"

// ============================================================================
// GLOBAL INSTANCE
// ============================================================================
DACManager dacManager;

// ============================================================================
// CONSTRUCTOR
// ============================================================================
DACManager::DACManager() : _ready(false) {}

// ============================================================================
// INITIALIZATION
// ============================================================================
bool DACManager::begin() {
    bool irReady = _dacIR.begin(DAC_ADDR_IR, &Wire);
    bool redReady = _dacRed.begin(DAC_ADDR_RED, &Wire);

    if (irReady && redReady) {
        _ready = true;
        // Set initial output to center
        setValues(DAC_CENTER_VALUE, DAC_CENTER_VALUE);
        Serial.printf("[DACManager] Both DACs initialized (IR: 0x%02X, Red: 0x%02X)\n", DAC_ADDR_IR, DAC_ADDR_RED);
        return true;
    }

    Serial.println("[DACManager] ERROR: Failed to initialize one or both DACs.");
    if (!irReady) Serial.printf(" - IR DAC not found at 0x%02X\n", DAC_ADDR_IR);
    if (!redReady) Serial.printf(" - Red DAC not found at 0x%02X\n", DAC_ADDR_RED);
    
    _ready = false;
    return false;
}

// ============================================================================
// OUTPUT CONTROL
// ============================================================================
void DACManager::setValues(uint16_t valueIR, uint16_t valueRed) {
    if (!_ready) return;
    
    if (valueIR > DAC_MAX_VALUE) valueIR = DAC_MAX_VALUE;
    if (valueRed > DAC_MAX_VALUE) valueRed = DAC_MAX_VALUE;
    
    // Write values to both DACs sequentially
    _dacIR.setVoltage(valueIR, false);
    _dacRed.setVoltage(valueRed, false);
}

// ============================================================================
// SAMPLE MAPPING
// ============================================================================
uint16_t DACManager::ppgSampleToDACValue(float sample_mV, float dcBaseline, float maxAC) {
    float minV = dcBaseline - maxAC;
    float maxV = dcBaseline + maxAC;
    
    // Prevent division by zero
    if (maxV <= minV) {
        return DAC_CENTER_VALUE;
    }
    
    float normalized = (sample_mV - minV) / (maxV - minV);
    
    if (normalized < 0.0f) normalized = 0.0f;
    if (normalized > 1.0f) normalized = 1.0f;
    
    return (uint16_t)(normalized * 4095.0f);
}
