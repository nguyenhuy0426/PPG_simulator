#include "lcd.h"

#include <string.h>

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_log.h"
#include "esp_rom_gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "soc/spi_periph.h"
#include "font5x7.h"

static const char *TAG = "lcd";

// Wiring (ESP32-S3-DevKitC-1). GPIO11/12 are the SPI2 IO_MUX MOSI/CLK pins.
#define PIN_MOSI 11
#define PIN_SCLK 12
#define PIN_DC   13
#define PIN_RST  14
#define PIN_BLK  15
#define LCD_HOST SPI2_HOST
// Modules without a CS pin have CS tied low on the board; the ST7789 then needs SPI mode 3
// to see the first clock edge correctly.
#define LCD_SPI_MODE     3
#define LCD_PCLK_HZ      (20 * 1000 * 1000)   // conservative for jumper wires
#define LCD_INVERT       true                  // IPS ST7789 modules show inverted colors otherwise
#define BUF_PIXELS       (LCD_W * 16)
#define DMA_WAIT_MS      200

static esp_lcd_panel_handle_t s_panel;
static uint16_t *s_buf;
static SemaphoreHandle_t s_done;
static SemaphoreHandle_t s_pin_lock;

void lcd_set_pin_lock(SemaphoreHandle_t lock) { s_pin_lock = lock; }

// Take the shared lock and route MOSI/SCLK back to SPI2 through the IO_MUX, as spi_bus_initialize()
// does for these native pins. SCLK idles high in mode 3, so attaching makes no clock edge.
static void pins_attach(void)
{
    if (s_pin_lock) xSemaphoreTake(s_pin_lock, portMAX_DELAY);
    gpio_iomux_out(PIN_MOSI, spi_periph_signal[LCD_HOST].func, false);
    gpio_iomux_out(PIN_SCLK, spi_periph_signal[LCD_HOST].func, false);
}

// Hand MOSI/SCLK back as inputs with pull-up and give the lock. Output is disabled before the pad
// leaves the SPI function so SCLK never drops low: with CS tied low the panel would count the edge.
static void pins_release(void)
{
    const int pins[2] = {PIN_MOSI, PIN_SCLK};
    for (int i = 0; i < 2; i++) {
        gpio_set_pull_mode(pins[i], GPIO_PULLUP_ONLY);
        gpio_set_direction(pins[i], GPIO_MODE_INPUT);
        esp_rom_gpio_pad_select_gpio(pins[i]);
    }
    if (s_pin_lock) xSemaphoreGive(s_pin_lock);
}

static bool on_done(esp_lcd_panel_io_handle_t io, esp_lcd_panel_io_event_data_t *ev, void *ctx)
{
    BaseType_t woken = pdFALSE;
    xSemaphoreGiveFromISR(s_done, &woken);
    return woken == pdTRUE;
}

esp_err_t lcd_init(void)
{
    s_done = xSemaphoreCreateBinary();
    s_buf = heap_caps_malloc(BUF_PIXELS * sizeof(uint16_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!s_done || !s_buf) return ESP_ERR_NO_MEM;

    const gpio_config_t bl = {.pin_bit_mask = 1ULL << PIN_BLK, .mode = GPIO_MODE_OUTPUT};
    ESP_ERROR_CHECK(gpio_config(&bl));
    gpio_set_level(PIN_BLK, 0);

    // The SPI pins are driven from spi_bus_initialize() on, so hold the lock through the panel setup.
    if (s_pin_lock) xSemaphoreTake(s_pin_lock, portMAX_DELAY);
    const spi_bus_config_t bus = {
        .mosi_io_num = PIN_MOSI, .miso_io_num = -1, .sclk_io_num = PIN_SCLK,
        .quadwp_io_num = -1, .quadhd_io_num = -1,
        .max_transfer_sz = BUF_PIXELS * sizeof(uint16_t),
    };
    esp_err_t e = spi_bus_initialize(LCD_HOST, &bus, SPI_DMA_CH_AUTO);

    esp_lcd_panel_io_handle_t io;
    const esp_lcd_panel_io_spi_config_t io_cfg = {
        .cs_gpio_num = -1, .dc_gpio_num = PIN_DC, .spi_mode = LCD_SPI_MODE,
        .pclk_hz = LCD_PCLK_HZ, .trans_queue_depth = 4,
        .on_color_trans_done = on_done, .lcd_cmd_bits = 8, .lcd_param_bits = 8,
    };
    if (e == ESP_OK) e = esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST, &io_cfg, &io);

    const esp_lcd_panel_dev_config_t pcfg = {
        .reset_gpio_num = PIN_RST, .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB, .bits_per_pixel = 16,
    };
    if (e == ESP_OK) e = esp_lcd_new_panel_st7789(io, &pcfg, &s_panel);
    if (e == ESP_OK) e = esp_lcd_panel_reset(s_panel);
    if (e == ESP_OK) e = esp_lcd_panel_init(s_panel);
    if (e == ESP_OK) e = esp_lcd_panel_invert_color(s_panel, LCD_INVERT);
    pins_release();
    if (e != ESP_OK) return e;
    lcd_fill_rect(0, 0, LCD_W, LCD_H, C_BLACK);
    pins_attach();
    e = esp_lcd_panel_disp_on_off(s_panel, true);
    pins_release();
    if (e != ESP_OK) return e;
    gpio_set_level(PIN_BLK, 1);
    ESP_LOGI(TAG, "ST7789 %dx%d ready (SPI mode %d, %d MHz, no CS)", LCD_W, LCD_H, LCD_SPI_MODE, LCD_PCLK_HZ / 1000000);
    return ESP_OK;
}

static void push(int x, int y, int w, int h)
{
    // The color transfer is queued (DMA); wait for it before the buffer is reused and the pins released.
    pins_attach();
    if (esp_lcd_panel_draw_bitmap(s_panel, x, y, x + w, y + h, s_buf) == ESP_OK &&
        xSemaphoreTake(s_done, pdMS_TO_TICKS(DMA_WAIT_MS)) != pdTRUE)
        ESP_LOGW(TAG, "DMA done timeout");
    pins_release();
}

void lcd_fill_rect(int x, int y, int w, int h, uint16_t color)
{
    if (w <= 0 || h <= 0) return;
    const int rows = BUF_PIXELS / w;
    const int fill = (rows < h ? rows : h) * w;
    for (int i = 0; i < fill; i++) s_buf[i] = color;
    for (int r = 0; r < h; r += rows) push(x, y + r, w, (h - r) < rows ? (h - r) : rows);
}

void lcd_blit(int x, int y, int w, int h, const uint16_t *px)
{
    if (w <= 0 || h <= 0 || w * h > BUF_PIXELS) return;
    memcpy(s_buf, px, (size_t)w * h * sizeof(uint16_t));
    push(x, y, w, h);
}

int lcd_text(int x, int y, const char *s, int scale, uint16_t fg, uint16_t bg)
{
    const int cw = 6 * scale, ch = 8 * scale;
    for (; *s; s++, x += cw) {
        if (x + cw > LCD_W) break;
        char c = *s;
        if (c >= 'a' && c <= 'z') c -= 32;
        if (c < FONT_FIRST || c > FONT_LAST) c = '?';
        const uint8_t *g = font5x7[c - FONT_FIRST];
        for (int py = 0; py < ch; py++) {
            const int row = py / scale;
            for (int px = 0; px < cw; px++) {
                const int col = px / scale;
                const bool on = col < 5 && row < 7 && (g[col] >> row) & 1;
                s_buf[py * cw + px] = on ? fg : bg;
            }
        }
        push(x, y, cw, ch);
    }
    return x;
}

// Segment bits: a b c d e f g (bit 0 = a)
static const uint8_t SEG[10] = {0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F};

void lcd_seg_number(int x, int y, const char *digits, int dw, int dh, int t, int gap, uint16_t fg, uint16_t bg)
{
    const int hh = dh / 2;
    for (; *digits; digits++, x += dw + gap) {
        uint8_t m = 0;
        if (*digits >= '0' && *digits <= '9') m = SEG[*digits - '0'];
        else if (*digits == '-') m = 0x40;
        lcd_fill_rect(x, y, dw, dh, bg);
        if (m & 0x01) lcd_fill_rect(x + t, y, dw - 2 * t, t, fg);                  // a
        if (m & 0x02) lcd_fill_rect(x + dw - t, y + t, t, hh - t, fg);             // b
        if (m & 0x04) lcd_fill_rect(x + dw - t, y + hh, t, hh - t, fg);            // c
        if (m & 0x08) lcd_fill_rect(x + t, y + dh - t, dw - 2 * t, t, fg);         // d
        if (m & 0x10) lcd_fill_rect(x, y + hh, t, hh - t, fg);                     // e
        if (m & 0x20) lcd_fill_rect(x, y + t, t, hh - t, fg);                      // f
        if (m & 0x40) lcd_fill_rect(x + t, y + hh - t / 2, dw - 2 * t, t, fg);     // g
    }
}
