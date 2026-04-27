/**
 * @file mcp4725_dac.h
 * @brief MCP4725 12-bit DAC wrapper via I2C
 * @version 1.0.0
 * @date 25 April 2026
 *
 * Provides a simple interface over the Adafruit MCP4725 library
 * for outputting analog PPG signal via I2C DAC.
 */

#ifndef MCP4725_DAC_H
#define MCP4725_DAC_H

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_MCP4725.h>
#include "../config.h"

class MCP4725DAC {
public:
    MCP4725DAC();

    /**
     * @brief Initialize the MCP4725 DAC on I2C bus
     * @param addr I2C address (default 0x60)
     * @return true if DAC detected and initialized
     */
    bool begin(uint8_t addr = MCP4725_I2C_ADDR);

    /**
     * @brief Set DAC output value (12-bit)
     * @param value 0–4095
     */
    void setValue(uint16_t value);

    /**
     * @brief Set DAC output voltage in millivolts
     * @param mV 0–3300 mV
     */
    void setVoltageMV(float mV);

    /**
     * @brief Set DAC to center value (mid-scale)
     */
    void setCenter();

    /**
     * @brief Check if DAC is initialized
     */
    bool isReady() const { return _ready; }

private:
    Adafruit_MCP4725 _dac;
    bool _ready;
};

// Global instance
extern MCP4725DAC ppgDAC;

#endif // MCP4725_DAC_H
