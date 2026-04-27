/**
 * @file tft_display.h
 * @brief TFT display driver for 1.8" ST7735 (SPI) — PPG waveform visualization
 * @version 1.0.0
 * @date 25 April 2026
 *
 * Renders PPG waveform using sweep-line approach on a 160x128 TFT display.
 * Layout (landscape, rotation=1):
 *   Row  0–19: Header bar (HR, PI, Condition)
 *   Row 20–117: Waveform area (98px height)
 *   Row 118–127: Footer/status bar
 */

#ifndef TFT_DISPLAY_H
#define TFT_DISPLAY_H

#include <Arduino.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7735.h>
#include <SPI.h>
#include "../config.h"
#include "../data/signal_types.h"

// Color palette (RGB565)
#define COLOR_BG            ST77XX_BLACK
#define COLOR_WAVEFORM      0x07E0      // Bright green (PPG signature color)
#define COLOR_WAVEFORM_DIM  0x0320      // Dim green for trailing waveform
#define COLOR_GRID          0x2104      // Dark gray grid lines
#define COLOR_HEADER_BG     0x0000      // Black header
#define COLOR_TEXT           ST77XX_WHITE
#define COLOR_TEXT_VALUE     0x07FF      // Cyan for values
#define COLOR_TEXT_LABEL     0xBDF7      // Light gray for labels
#define COLOR_HIGHLIGHT      ST77XX_YELLOW
#define COLOR_ERASE          ST77XX_BLACK

class TFTDisplay {
public:
    TFTDisplay();

    /**
     * @brief Initialize TFT display
     * @return true if successful
     */
    bool begin();

    /**
     * @brief Draw a single waveform point (sweep-line approach)
     * @param acValue_mV AC component value in millivolts
     * @param acMax_mV Maximum expected AC value for scaling
     */
    void drawWaveformPoint(float acValue_mV, float acMax_mV);

    /**
     * @brief Update the metrics header bar
     * @param hr Heart rate in BPM
     * @param pi Perfusion index in %
     * @param spo2 SpO2 in %
     * @param rr Respiratory rate in BPM
     * @param conditionName Name of current condition
     */
    void updateMetrics(float hr, float pi, float spo2, float rr, const char* conditionName);

    /**
     * @brief Show parameter editing overlay on footer
     * @param paramName Name of parameter being edited
     * @param value Current value
     * @param minVal Minimum allowed value
     * @param maxVal Maximum allowed value
     */
    void showParamEdit(const char* paramName, float value, float minVal, float maxVal);

    /**
     * @brief Show condition selection on footer
     * @param conditionName Name of current condition
     * @param conditionIndex Index (0–5)
     */
    void showConditionSelect(const char* conditionName, uint8_t conditionIndex);

    /**
     * @brief Clear the entire waveform area
     */
    void clearWaveform();

    /**
     * @brief Draw the initial screen layout (header, grid, footer)
     */
    void drawLayout();

    /**
     * @brief Get the underlying TFT object for advanced use
     */
    Adafruit_ST7735& getTFT() { return _tft; }

private:
    Adafruit_ST7735 _tft;

    // Waveform sweep state
    uint16_t _sweepX;                   // Current X position (0 to width-1)
    uint8_t _prevY;                     // Previous Y coordinate for line drawing
    bool _firstPoint;                   // True if no previous point exists

    // Cached metric values (to avoid redraw when unchanged)
    int _cachedHR;
    int _cachedPI_x10;
    int _cachedSpO2;
    int _cachedRR;
    char _cachedCondition[20];

    // Private helpers
    void drawHeader();
    void drawGrid();
    void drawFooter();
    uint8_t mapToY(float acValue_mV);
    
    // Auto-scaling trackers
    float _currentSweepMin;
    float _currentSweepMax;
    float _displayMin;
    float _displayMax;
};

// Global instance
extern TFTDisplay tftDisplay;

#endif // TFT_DISPLAY_H
