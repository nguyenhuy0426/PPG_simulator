/**
 * @file tft_display.cpp
 * @brief TFT display driver implementation for 1.8" ST7735
 * @version 1.0.0
 * @date 25 April 2026
 */

#include "hw/tft_display.h"

// ============================================================================
// GLOBAL INSTANCE
// ============================================================================
TFTDisplay tftDisplay;

// ============================================================================
// CONSTRUCTOR
// ============================================================================
TFTDisplay::TFTDisplay()
    : _tft(TFT_CS, TFT_DC, TFT_RST)
    , _sweepX(0)
    , _prevY(TFT_WAVEFORM_Y_START + TFT_WAVEFORM_HEIGHT / 2)
    , _firstPoint(true)
    , _cachedHR(-1)
    , _cachedPI_x10(-1)
    , _cachedSpO2(-1)
    , _cachedRR(-1)
{
    memset(_cachedCondition, 0, sizeof(_cachedCondition));
}

// ============================================================================
// INITIALIZATION
// ============================================================================
bool TFTDisplay::begin() {
    SPI.begin(TFT_SCLK, -1, TFT_MOSI, TFT_CS);   // SCK, MISO none, MOSI, SS
    delay(50);

    _tft.initR(INITR_BLACKTAB);
    delay(50);
    _tft.fillScreen(ST77XX_RED);
    delay(500);
    _tft.fillScreen(ST77XX_GREEN);
    delay(500);
    _tft.fillScreen(ST77XX_BLUE);
    delay(500);
    _tft.setRotation(TFT_ROTATION);
    _tft.fillScreen(COLOR_BG);

    drawLayout();

    Serial.printf("[TFT] Display initialized: %dx%d, rotation=%d\n",
                  TFT_SCREEN_WIDTH, TFT_SCREEN_HEIGHT, TFT_ROTATION);
    return true;
}

// ============================================================================
// DRAW INITIAL LAYOUT
// ============================================================================
void TFTDisplay::drawLayout() {
    _tft.fillScreen(COLOR_BG);
    drawHeader();
    drawGrid();
    drawFooter();
}

// ============================================================================
// DRAW HEADER BAR (top 20px)
// ============================================================================
void TFTDisplay::drawHeader() {
    _tft.fillRect(0, 0, TFT_SCREEN_WIDTH, TFT_HEADER_HEIGHT, COLOR_HEADER_BG);

    // Draw separator line
    _tft.drawFastHLine(0, TFT_HEADER_HEIGHT - 1, TFT_SCREEN_WIDTH, COLOR_GRID);

    // Labels and initial values will be drawn by updateMetrics
}

// ============================================================================
// DRAW GRID LINES IN WAVEFORM AREA
// ============================================================================
void TFTDisplay::drawGrid() {
    uint16_t yStart = TFT_WAVEFORM_Y_START;
    uint16_t yEnd = TFT_WAVEFORM_Y_START + TFT_WAVEFORM_HEIGHT;
    uint16_t yMid = yStart + TFT_WAVEFORM_HEIGHT / 2;

    // Horizontal center line (baseline)
    _tft.drawFastHLine(0, yMid, TFT_SCREEN_WIDTH, COLOR_GRID);

    // Horizontal quarter lines
    uint16_t yQ1 = yStart + TFT_WAVEFORM_HEIGHT / 4;
    uint16_t yQ3 = yStart + 3 * TFT_WAVEFORM_HEIGHT / 4;
    for (int x = 0; x < TFT_SCREEN_WIDTH; x += 4) {
        _tft.drawPixel(x, yQ1, COLOR_GRID);
        _tft.drawPixel(x, yQ3, COLOR_GRID);
    }

    // Vertical grid lines (every 40 pixels)
    for (int x = 40; x < TFT_SCREEN_WIDTH; x += 40) {
        for (int y = yStart; y < yEnd; y += 4) {
            _tft.drawPixel(x, y, COLOR_GRID);
        }
    }

    // Bottom border
    _tft.drawFastHLine(0, yEnd, TFT_SCREEN_WIDTH, COLOR_GRID);
}

// ============================================================================
// DRAW FOOTER BAR (bottom 10px)
// ============================================================================
void TFTDisplay::drawFooter() {
    uint16_t yFooter = TFT_SCREEN_HEIGHT - TFT_FOOTER_HEIGHT;
    _tft.fillRect(0, yFooter, TFT_SCREEN_WIDTH, TFT_FOOTER_HEIGHT, COLOR_HEADER_BG);
    _tft.setTextColor(COLOR_TEXT_LABEL, COLOR_HEADER_BG);
    _tft.setTextSize(1);
    _tft.setCursor(2, yFooter + 1);
    _tft.print("PPG Simulator");
}

// ============================================================================
// DRAW WAVEFORM POINT (sweep-line approach)
// ============================================================================
void TFTDisplay::drawWaveformPoint(float acValue_mV, float acMax_mV) {
    uint8_t y = mapToY(acValue_mV, acMax_mV);

    // Erase column ahead (2px wide for visibility)
    uint16_t eraseX = (_sweepX + 2) % TFT_SCREEN_WIDTH;
    _tft.drawFastVLine(eraseX, TFT_WAVEFORM_Y_START, TFT_WAVEFORM_HEIGHT, COLOR_BG);
    uint16_t eraseX2 = (_sweepX + 3) % TFT_SCREEN_WIDTH;
    _tft.drawFastVLine(eraseX2, TFT_WAVEFORM_Y_START, TFT_WAVEFORM_HEIGHT, COLOR_BG);

    // Draw sweep cursor (bright vertical line 1px ahead)
    uint16_t cursorX = (_sweepX + 1) % TFT_SCREEN_WIDTH;
    _tft.drawFastVLine(cursorX, TFT_WAVEFORM_Y_START, TFT_WAVEFORM_HEIGHT, COLOR_GRID);

    // Draw waveform line segment
    if (_firstPoint) {
        _tft.drawPixel(_sweepX, y, COLOR_WAVEFORM);
        _firstPoint = false;
    } else {
        _tft.drawLine(_sweepX - 1, _prevY, _sweepX, y, COLOR_WAVEFORM);
    }

    _prevY = y;

    // Advance sweep position
    _sweepX++;
    if (_sweepX >= TFT_SCREEN_WIDTH) {
        _sweepX = 0;
        _firstPoint = true;
        // Redraw grid when wrapping
        drawGrid();
    }
}

// ============================================================================
// MAP AC VALUE TO Y COORDINATE
// ============================================================================
uint8_t TFTDisplay::mapToY(float acValue_mV, float acMax_mV) {
    // We want the waveform to fit completely in the waveform area
    // The peak is positive, the valley is 0 or negative
    // Give a 10% margin at top and bottom to prevent clipping
    float margin = acMax_mV * 0.1f;
    float rangeMax = acMax_mV + margin;
    float rangeMin = -margin;
    
    if (rangeMax <= rangeMin) rangeMax = rangeMin + 1.0f;

    float normalized = (acValue_mV - rangeMin) / (rangeMax - rangeMin);
    if (normalized < 0.0f) normalized = 0.0f;
    if (normalized > 1.0f) normalized = 1.0f;

    // Invert Y axis (TFT Y=0 is top)
    uint16_t yBottom = TFT_WAVEFORM_Y_START + TFT_WAVEFORM_HEIGHT - 1;
    uint8_t y = yBottom - (uint8_t)(normalized * (TFT_WAVEFORM_HEIGHT - 1));

    return y;
}

// ============================================================================
// UPDATE METRICS HEADER
// ============================================================================
void TFTDisplay::updateMetrics(float hr, float pi, float spo2, float rr, const char* conditionName) {
    int hrInt = (int)(hr + 0.5f);
    int piX10 = (int)(pi * 10.0f + 0.5f);
    int spo2Int = (int)(spo2 + 0.5f);
    int rrInt = (int)(rr + 0.5f);

    bool changed = (hrInt != _cachedHR) || (piX10 != _cachedPI_x10) || 
                   (spo2Int != _cachedSpO2) || (rrInt != _cachedRR);

    if (changed) {
        _cachedHR = hrInt;
        _cachedPI_x10 = piX10;
        _cachedSpO2 = spo2Int;
        _cachedRR = rrInt;

        // Clear header text area
        _tft.fillRect(0, 0, TFT_SCREEN_WIDTH, TFT_HEADER_HEIGHT - 1, COLOR_HEADER_BG);
        _tft.setTextColor(COLOR_TEXT_VALUE, COLOR_HEADER_BG);
        _tft.setTextSize(1);
        _tft.setCursor(2, 6);

        char buf[64];
        snprintf(buf, sizeof(buf), "HR:%d PI:%d.%d%% O2:%d RR:%d", 
                 hrInt, piX10 / 10, piX10 % 10, spo2Int, rrInt);
                 
        // Estimate width (6px per char with default font)
        int width = strlen(buf) * 6;
        if (width > 160) {
            snprintf(buf, sizeof(buf), "H:%d P:%d.%d O2:%d R:%d", 
                     hrInt, piX10 / 10, piX10 % 10, spo2Int, rrInt);
        }
        _tft.print(buf);
    }
}

// ============================================================================
// SHOW PARAMETER EDIT ON FOOTER
// ============================================================================
void TFTDisplay::showParamEdit(const char* paramName, float value, float minVal, float maxVal) {
    uint16_t yFooter = TFT_SCREEN_HEIGHT - TFT_FOOTER_HEIGHT;
    _tft.fillRect(0, yFooter, TFT_SCREEN_WIDTH, TFT_FOOTER_HEIGHT, COLOR_HEADER_BG);
    _tft.setTextColor(COLOR_HIGHLIGHT, COLOR_HEADER_BG);
    _tft.setTextSize(1);
    _tft.setCursor(2, yFooter + 1);

    char buf[40];
    snprintf(buf, sizeof(buf), "< %s: %.1f >", paramName, value);
    _tft.print(buf);
}

// ============================================================================
// SHOW CONDITION SELECTION ON FOOTER
// ============================================================================
void TFTDisplay::showConditionSelect(const char* conditionName, uint8_t conditionIndex) {
    uint16_t yFooter = TFT_SCREEN_HEIGHT - TFT_FOOTER_HEIGHT;
    _tft.fillRect(0, yFooter, TFT_SCREEN_WIDTH, TFT_FOOTER_HEIGHT, COLOR_HEADER_BG);
    _tft.setTextColor(COLOR_HIGHLIGHT, COLOR_HEADER_BG);
    _tft.setTextSize(1);
    _tft.setCursor(2, yFooter + 1);

    char buf[40];
    snprintf(buf, sizeof(buf), "< %d: %s >", conditionIndex + 1, conditionName);
    _tft.print(buf);
}

// ============================================================================
// CLEAR WAVEFORM AREA
// ============================================================================
void TFTDisplay::clearWaveform() {
    _tft.fillRect(0, TFT_WAVEFORM_Y_START, TFT_SCREEN_WIDTH, TFT_WAVEFORM_HEIGHT, COLOR_BG);
    drawGrid();
    _sweepX = 0;
    _firstPoint = true;
    _prevY = TFT_WAVEFORM_Y_START + TFT_WAVEFORM_HEIGHT / 2;
}
