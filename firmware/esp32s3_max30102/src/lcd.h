// ST7789 SPI display (no CS pin) through ESP-IDF esp_lcd, plus minimal drawing helpers.
// Only one task may call these functions (the display task owns the panel and its DMA buffer).
#pragma once
#include <stdint.h>

#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

#define LCD_W 240
#define LCD_H 240

// RGB565, byte-swapped for the panel's big-endian pixel order.
#define RGB(r, g, b) ((uint16_t)(((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)) >> 8 | \
                                 ((((r) & 0xF8) << 8) | (((g) & 0xFC) << 3) | ((b) >> 3)) << 8))
#define C_BLACK RGB(0, 0, 0)
#define C_WHITE RGB(255, 255, 255)
#define C_GREEN RGB(0, 230, 90)
#define C_RED   RGB(255, 40, 40)
#define C_GREY  RGB(90, 90, 90)
#define C_DGREY RGB(30, 30, 30)
#define C_AMBER RGB(255, 170, 0)
#define C_CYAN  RGB(0, 200, 255)

// On the bench board the MAX30102's I2C SCL (GPIO9) was held low while SPI2 owned GPIO11/12, also with
// the LCD unplugged; it read high again within ~20 us of releasing the pins (measured 23 Nov 2026). The panel's MOSI/SCLK are therefore driven only for the
// length of each transfer, holding `lock`; between transfers they are inputs with pull-up and the
// holder of the same lock (the I2C sensor task) has the pins quiet. Call before lcd_init(); NULL = no lock.
void lcd_set_pin_lock(SemaphoreHandle_t lock);
esp_err_t lcd_init(void);
void lcd_fill_rect(int x, int y, int w, int h, uint16_t color);
// Copy a w*h pixel block (byte-swapped RGB565) to the panel; returns when the DMA has finished.
void lcd_blit(int x, int y, int w, int h, const uint16_t *px);
// 5x7 font scaled by `scale`; advance is 6*scale per character. Returns the end x.
int lcd_text(int x, int y, const char *s, int scale, uint16_t fg, uint16_t bg);
// Seven-segment number: each of `digits` characters may be '0'..'9', '-' or ' '.
void lcd_seg_number(int x, int y, const char *digits, int dw, int dh, int t, int gap, uint16_t fg, uint16_t bg);
