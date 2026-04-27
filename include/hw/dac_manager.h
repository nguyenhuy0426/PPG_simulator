/**
 * @file dac_manager.h
 * @brief Manager for dual MCP4725 DACs via I2C
 * @version 2.0.0
 * @date 25 April 2026
 */

#ifndef DAC_MANAGER_H
#define DAC_MANAGER_H

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_MCP4725.h>
#include "../config.h"

// I2C Addresses for the two DACs
#define DAC_ADDR_IR  0x60
#define DAC_ADDR_RED 0x61

class DACManager {
public:
    DACManager();

    /**
     * @brief Initialize both MCP4725 DACs on the I2C bus
     * @return true if both DACs are detected and initialized
     */
    bool begin();

    /**
     * @brief Write 12-bit values directly to the DACs
     */
    void setValues(uint16_t valueIR, uint16_t valueRed);

    /**
     * @brief Map a PPG sample in mV to a 12-bit DAC value, preserving DC baseline
     * @param sample_mV The raw PPG signal sample (DC + AC)
     * @param dcBaseline The DC baseline in mV
     * @param maxAC The expected maximum AC amplitude in mV
     * @return 12-bit mapped DAC value (0-4095)
     */
    uint16_t ppgSampleToDACValue(float sample_mV, float dcBaseline, float maxAC);

    /**
     * @brief Check if both DACs are initialized
     */
    bool isReady() const { return _ready; }

private:
    Adafruit_MCP4725 _dacIR;
    Adafruit_MCP4725 _dacRed;
    bool _ready;
};

// Global instance
extern DACManager dacManager;

#endif // DAC_MANAGER_H
