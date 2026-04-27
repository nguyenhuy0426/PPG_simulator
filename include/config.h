/**
 * @file config.h
 * @brief Global system configuration for PPG Signal Simulator
 * @version 2.0.0
 * @date 25 April 2026
 *
 * Hardware: ESP32-S3-DevKitC-1 + 1.8" TFT ST7735 (SPI) + MCP4725 DAC (I2C)
 * Control: 3 push buttons with interrupts
 */

#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// ============================================================================
// SYSTEM IDENTIFICATION
// ============================================================================
#define DEVICE_NAME "PPG Signal Simulator"
#define FIRMWARE_VERSION "2.0.0"
#define FIRMWARE_DATE "25 April 2026"
#ifndef HARDWARE_MODEL
#define HARDWARE_MODEL "ESP32-S3"
#endif

// ============================================================================
// PIN CONFIGURATION — TFT DISPLAY (SPI, ST7735 1.8" 160x128)
// ============================================================================
// Defined directly for Adafruit ST7735:
#define TFT_MOSI 11
#define TFT_SCLK 12
#define TFT_CS 10
#define TFT_DC 4
#define TFT_RST 5
// ============================================================================
// PIN CONFIGURATION — MCP4725 DAC (I2C)
// ============================================================================
#define I2C_SDA_PIN 8         // GPIO8  — I2C SDA
#define I2C_SCL_PIN 9         // GPIO9  — I2C SCL
#define MCP4725_I2C_ADDR 0x60 // MCP4725 default address

// ============================================================================
// PIN CONFIGURATION — PUSH BUTTONS (Active LOW, internal pull-up)
// ============================================================================
#define BTN_MODE_PIN 7      // GPIO7 — Mode button
#define POT_PIN 15          // GPIO15 (ADC2_CH4) — Potentiometer input
#define BTN_DEBOUNCE_MS 200 // Debounce interval in ms

// ============================================================================
// PIN CONFIGURATION — STATUS LED
// ============================================================================
#define LED_STATUS_PIN 2 // GPIO2 (onboard LED)

// ============================================================================
// SIGNAL SAMPLING CONFIGURATION
// ============================================================================

// Timer master frequency (internal buffer rate)
// MCP4725 I2C can sustain ~1 kHz writes in fast mode
const uint16_t FS_TIMER_HZ = 1000;           // Hz — DAC output rate
const uint16_t SAMPLE_RATE_HZ = FS_TIMER_HZ; // Alias

// PPG model generation rate
// PPG bandwidth: 0.5–10 Hz → Nyquist = 20 Hz
// Using 100 Hz for smooth waveform display
const uint16_t MODEL_SAMPLE_RATE_PPG = 100; // Hz

// deltaTime for model (seconds)
const float MODEL_DT_PPG = 1.0f / MODEL_SAMPLE_RATE_PPG; // 10 ms

// Model tick interval in microseconds
const uint32_t MODEL_TICK_US_PPG = 1000000 / MODEL_SAMPLE_RATE_PPG; // 10000 us

// Upsample ratio: interpolation from model rate to timer rate
// Ratio = FS_TIMER_HZ / MODEL_SAMPLE_RATE_PPG = 1000/100 = 10
const uint8_t UPSAMPLE_RATIO_PPG = FS_TIMER_HZ / MODEL_SAMPLE_RATE_PPG;

// Display output rate for TFT waveform
const uint16_t TFT_DISPLAY_RATE_HZ = 50; // Hz — waveform update rate

// ============================================================================
// MCP4725 DAC CONFIGURATION (12-bit)
// ============================================================================
#define DAC_RESOLUTION_BITS 12
#define DAC_MAX_VALUE 4095
#define DAC_CENTER_VALUE 2048
#define DAC_VOLTAGE_MAX 3.3f                                  // Volts
#define DAC_MV_PER_STEP (DAC_VOLTAGE_MAX * 1000.0f / 4096.0f) // ~0.806 mV

// ============================================================================
// TFT DISPLAY CONFIGURATION (1.8" ST7735, landscape 160x128)
// ============================================================================
#define TFT_SCREEN_WIDTH 160  // Pixels (landscape)
#define TFT_SCREEN_HEIGHT 128 // Pixels (landscape)
#define TFT_ROTATION 1        // Landscape rotation

// Layout zones
#define TFT_HEADER_HEIGHT 20 // Top metrics bar height
#define TFT_FOOTER_HEIGHT 10 // Bottom status bar height
#define TFT_WAVEFORM_Y_START TFT_HEADER_HEIGHT
#define TFT_WAVEFORM_HEIGHT                                                    \
  (TFT_SCREEN_HEIGHT - TFT_HEADER_HEIGHT - TFT_FOOTER_HEIGHT)
#define TFT_WAVEFORM_WIDTH TFT_SCREEN_WIDTH

// ============================================================================
// BUFFER CONFIGURATION
// ============================================================================
#define SIGNAL_BUFFER_SIZE 1024 // Samples (~1 second at 1 kHz)

// ============================================================================
// FREERTOS TASK CONFIGURATION
// ============================================================================
#define CORE_SIGNAL_GENERATION 1 // Core 1: Real-time signal generation
#define CORE_UI_COMMUNICATION 0  // Core 0: UI and communication

#define STACK_SIZE_SIGNAL 4096
#define STACK_SIZE_UI 4096

#define TASK_PRIORITY_SIGNAL 5 // High priority
#define TASK_PRIORITY_UI 2     // Medium priority

// ============================================================================
// UI TIMING (millis-based, not timer-based)
// ============================================================================
#define METRICS_UPDATE_MS 250 // 4 Hz text metrics update
#define WAVEFORM_UPDATE_MS 20 // 50 Hz waveform drawing

// ============================================================================
// DEBUG CONFIGURATION
// ============================================================================
#ifdef DEBUG_ENABLED
#define DEBUG_PRINT(x) Serial.print(x)
#define DEBUG_PRINTLN(x) Serial.println(x)
#define DEBUG_PRINTF(...) Serial.printf(__VA_ARGS__)
#else
#define DEBUG_PRINT(x)
#define DEBUG_PRINTLN(x)
#define DEBUG_PRINTF(...)
#endif

// Memory check macro
#define CHECK_HEAP(min_kb) (ESP.getFreeHeap() >= ((min_kb) * 1024))

#endif // CONFIG_H
