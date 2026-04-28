/**
 * @file tft_display.cpp
 * @brief OLED display driver implementation for 1.3" I2C U8g2
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
    : u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE)
    , _sweepX(0)
    , _cachedHR(-1)
    , _cachedPI_x10(-1)
    , _footerMode(FOOTER_NORMAL)
    , _paramEditValue(0.0f)
    , _condSelectIndex(0)
{
    memset(_cachedCondition, 0, sizeof(_cachedCondition));
    memset(_waveformY, 0, sizeof(_waveformY));
    memset(_paramEditName, 0, sizeof(_paramEditName));
}

// ============================================================================
// INITIALIZATION
// ============================================================================
bool TFTDisplay::begin() {
    u8g2.begin();
    u8g2.setContrast(255);
    
    clearWaveform();

    Serial.printf("[OLED] Display initialized: %dx%d, orientation=%d\n",
                  TFT_SCREEN_WIDTH, TFT_SCREEN_HEIGHT, TFT_ROTATION);
    return true;
}

// ============================================================================
// COMPUTE Y COORDINATE (Helper)
// ============================================================================
uint8_t TFTDisplay::mapToY(float acValue_mV, float acMax_mV) {
    if (acMax_mV <= 0.0f) acMax_mV = 150.0f;  // Fallback

    float normalized = acValue_mV / acMax_mV;
    if (normalized < 0.0f) normalized = 0.0f;
    if (normalized > 1.0f) normalized = 1.0f;

    uint16_t yBottom = TFT_WAVEFORM_Y_START + TFT_WAVEFORM_HEIGHT - 1;
    uint8_t y = yBottom - (uint8_t)(normalized * (TFT_WAVEFORM_HEIGHT - 1));

    return y;
}

// ============================================================================
// ADD WAVEFORM POINT
// ============================================================================
void TFTDisplay::drawWaveformPoint(float acValue_mV, float acMax_mV) {
    uint8_t y = mapToY(acValue_mV, acMax_mV);
    _waveformY[_sweepX] = y;

    _sweepX++;
    if (_sweepX >= TFT_SCREEN_WIDTH) {
        _sweepX = 0;
    }
}

// ============================================================================
// STATE MUTATORS
// ============================================================================
void TFTDisplay::updateMetrics(float hr, float pi, const char* conditionName) {
    _cachedHR = (int)(hr + 0.5f);
    _cachedPI_x10 = (int)(pi * 10.0f + 0.5f);
    strncpy(_cachedCondition, conditionName, sizeof(_cachedCondition) - 1);
    _cachedCondition[sizeof(_cachedCondition) - 1] = '\0';
    _footerMode = FOOTER_NORMAL;
}

void TFTDisplay::showParamEdit(const char* paramName, float value, float minVal, float maxVal) {
    _footerMode = FOOTER_PARAM_EDIT;
    strncpy(_paramEditName, paramName, sizeof(_paramEditName) - 1);
    _paramEditName[sizeof(_paramEditName) - 1] = '\0';
    _paramEditValue = value;
}

void TFTDisplay::showConditionSelect(const char* conditionName, uint8_t conditionIndex) {
    _footerMode = FOOTER_COND_SELECT;
    _condSelectIndex = conditionIndex;
    strncpy(_cachedCondition, conditionName, sizeof(_cachedCondition) - 1);
    _cachedCondition[sizeof(_cachedCondition) - 1] = '\0';
}

void TFTDisplay::clearWaveform() {
    uint8_t baseline = TFT_WAVEFORM_Y_START + TFT_WAVEFORM_HEIGHT / 2;
    for (int i = 0; i < TFT_SCREEN_WIDTH; i++) {
        _waveformY[i] = baseline;
    }
    _sweepX = 0;
}

// ============================================================================
// RENDER FRAME TO OLED
// ============================================================================
void TFTDisplay::renderFrame() {
    u8g2.clearBuffer();
    
    // Draw components
    drawHeader();
    drawGrid();
    drawFooter();

    // Draw waveform lines
    u8g2.setDrawColor(1);
    for (int i = 0; i < TFT_SCREEN_WIDTH - 1; i++) {
        // Skip drawing the line segment across the sweep break
        if (i == _sweepX || i + 1 == _sweepX) continue;
        
        u8g2.drawLine(i, _waveformY[i], i + 1, _waveformY[i + 1]);
    }
    
    // Draw sweep cursor dot
    u8g2.drawPixel(_sweepX, _waveformY[_sweepX]);

    u8g2.sendBuffer();
}

// ============================================================================
// DRAW HEADER (Internal)
// ============================================================================
void TFTDisplay::drawHeader() {
    u8g2.setDrawColor(1);
    u8g2.setFont(u8g2_font_5x7_tf);

    // HR and PI Values
    char hrBuf[16];
    char piBuf[16];
    snprintf(hrBuf, sizeof(hrBuf), "HR:%d", _cachedHR);
    snprintf(piBuf, sizeof(piBuf), "PI:%d.%d", _cachedPI_x10 / 10, _cachedPI_x10 % 10);

    u8g2.drawStr(0, 8, hrBuf);
    u8g2.drawStr(36, 8, piBuf);

    // Condition right aligned (approx)
    u8g2.drawStr(72, 8, _cachedCondition);

    // Separator
    u8g2.drawHLine(0, TFT_HEADER_HEIGHT - 1, TFT_SCREEN_WIDTH);
}

// ============================================================================
// DRAW GRID (Internal)
// ============================================================================
void TFTDisplay::drawGrid() {
    // Only light grid lines for monochrome to avoid clutter
    uint16_t yStart = TFT_WAVEFORM_Y_START;
    uint16_t yEnd = TFT_WAVEFORM_Y_START + TFT_WAVEFORM_HEIGHT;
    uint16_t yMid = yStart + TFT_WAVEFORM_HEIGHT / 2;

    u8g2.setDrawColor(1);

    // Center Baseline (dotted)
    for (int x = 0; x < TFT_SCREEN_WIDTH; x += 4) {
        u8g2.drawPixel(x, yMid);
    }
    
    // Bottom border
    u8g2.drawHLine(0, yEnd, TFT_SCREEN_WIDTH);
}

// ============================================================================
// DRAW FOOTER (Internal)
// ============================================================================
void TFTDisplay::drawFooter() {
    u8g2.setDrawColor(1);
    u8g2.setFont(u8g2_font_5x7_tf);

    char footerBuf[32];

    switch (_footerMode) {
        case FOOTER_NORMAL:
            u8g2.drawStr(0, TFT_SCREEN_HEIGHT - 1, "PPG Simulator");
            break;
        case FOOTER_PARAM_EDIT:
            if (_paramEditValue == (int)_paramEditValue) {
                snprintf(footerBuf, sizeof(footerBuf), "< %s: %.0f >", _paramEditName, _paramEditValue);
            } else {
                snprintf(footerBuf, sizeof(footerBuf), "< %s: %.1f >", _paramEditName, _paramEditValue);
            }
            u8g2.drawStr(0, TFT_SCREEN_HEIGHT - 1, footerBuf);
            break;
        case FOOTER_COND_SELECT:
            snprintf(footerBuf, sizeof(footerBuf), "< %d: %s >", _condSelectIndex + 1, _cachedCondition);
            u8g2.drawStr(0, TFT_SCREEN_HEIGHT - 1, footerBuf);
            break;
    }
}
