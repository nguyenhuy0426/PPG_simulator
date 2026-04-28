/**
 * @file tft_display.h
 * @brief OLED display driver for 1.3" I2C U8g2 — PPG waveform visualization
 * @version 1.0.0
 * @date 25 April 2026
 */

#ifndef TFT_DISPLAY_H
#define TFT_DISPLAY_H

#include <Arduino.h>
#include <U8g2lib.h>
#include <Wire.h>
#include "../config.h"
#include "../data/signal_types.h"

class TFTDisplay {
public:
    TFTDisplay();

    /**
     * @brief Initialize display
     * @return true if successful
     */
    bool begin();

    /**
     * @brief Render the entire frame to OLED (must be called periodically)
     */
    void renderFrame();

    /**
     * @brief Set a single waveform point to the internal buffer
     * @param acValue_mV AC component value in millivolts
     * @param acMax_mV Maximum expected AC value for scaling
     */
    void drawWaveformPoint(float acValue_mV, float acMax_mV);

    /**
     * @brief Update the metrics state
     * @param hr Heart rate in BPM
     * @param pi Perfusion index in %
     * @param conditionName Name of current condition
     */
    void updateMetrics(float hr, float pi, const char* conditionName);

    /**
     * @brief Show parameter editing overlay on footer state
     * @param paramName Name of parameter being edited
     * @param value Current value
     * @param minVal Minimum allowed value
     * @param maxVal Maximum allowed value
     */
    void showParamEdit(const char* paramName, float value, float minVal, float maxVal);

    /**
     * @brief Show condition selection on footer state
     * @param conditionName Name of current condition
     * @param conditionIndex Index (0–5)
     */
    void showConditionSelect(const char* conditionName, uint8_t conditionIndex);

    /**
     * @brief Clear the entire waveform area buffer
     */
    void clearWaveform();

    /**
     * @brief Get the underlying U8g2 object
     */
    U8G2& getU8g2() { return u8g2; }

private:
    U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2;

    // Waveform state
    uint16_t _sweepX;                   // Current X position (0 to width-1)
    uint8_t _waveformY[TFT_WAVEFORM_WIDTH]; // Y values for waveform

    // Metrics state
    int _cachedHR;
    int _cachedPI_x10;
    char _cachedCondition[20];

    // Footer mode state
    enum FooterMode {
        FOOTER_NORMAL,
        FOOTER_PARAM_EDIT,
        FOOTER_COND_SELECT
    } _footerMode;

    char _paramEditName[16];
    float _paramEditValue;

    uint8_t _condSelectIndex;

    // Private helpers
    void drawHeader();
    void drawGrid();
    void drawFooter();
    uint8_t mapToY(float acValue_mV, float acMax_mV);
};

// Global instance
extern TFTDisplay tftDisplay;

#endif // TFT_DISPLAY_H
