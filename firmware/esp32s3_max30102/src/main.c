// ESP32-S3 + MAX30102 (I2C GPIO8/9) + ST7789 240x240: pulse rate and PPG waveform.
//
// Tasks:
//   sensor  (prio 5) owns the I2C bus and the MAX30102: polls the FIFO, runs the HR estimator
//                    on both channels, streams samples/reports on the serial console.
//   display (prio 3) owns the panel: sweeps the waveform and shows HR / state.
//   console (prio 2) parses serial commands and forwards configuration to the sensor task.
//   sensor and display never use their pins at the same time: each I2C transfer and each LCD
//   transfer holds s_pin_mtx (see APP_USE_LCD below).
//
// Serial output (115200 8N1, UART0 via the board's USB-UART bridge):
//   S,<seq>,<red>,<ir>,<ppg>,<beat>  one line per sample when streaming is on: raw 18-bit counts, the
//                                 band-passed waveform of the channel in use (pulse up) and a beat mark
//   R,<json>                      once per second
// Commands (one per line): led <red_mA> <ir_mA> | range <0-3> | stream <0|1> | ch <auto|red|ir> | info
//                           rd  (capture the module's RD/IRD pins, see rd_probe.c)
//                           sr <0-3> | avg <0-5>  (bench only; HR estimator assumes 100 Hz output)
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_rom_sys.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lcd.h"
#include "max30102.h"
#include "ppg_hr.h"
#include "rd_probe.h"

static const char *TAG = "app";

// The ST7789 is optional (0 = serial output only). On the bench PCB, SPI2 driving GPIO11/12 holds the
// I2C SCL (GPIO9) low, so the LCD and the sensor take turns on s_pin_mtx: the LCD drives its pins only
// during a transfer (lcd.c), the sensor task does its I2C transfers while they are released.
#ifndef APP_USE_LCD
#define APP_USE_LCD        1
#endif

#define I2C_PIN_A          8     // tried as SDA first, then swapped if nothing answers
#define I2C_PIN_B          9
#define SENSOR_POLL_MS     10
#define SENSOR_RETRY_MS    1000
#define MAX_READ_ERRORS    5     // consecutive I2C errors before re-initialising the sensor
#define SAT_MARGIN         512u  // counts below full scale treated as saturated
#define DISP_DECIM         2     // 100 Hz samples -> 50 columns/s -> 4.8 s across the screen
#define DISP_QUEUE_LEN     64
#define CONSOLE_BAUD       115200
#define CONSOLE_LINE_MAX   64
#define MA_TO_PA(ma)       ((uint8_t)fminf(255.0f, fmaxf(0.0f, (ma) / 0.2f + 0.5f)))

// Defaults: SpO2 mode, 200 sps averaged by 2 -> 100 Hz, 411 us (18-bit), 16384 nA full scale.
// LEDs off: this bench firmware receives the simulator's red flicker (bench/pi_red_flicker.py), the
// configuration measured on 23 Nov 2026. For a finger, set the LEDs with `led 7.2 7.2`.
static const max30102_cfg_t DEFAULT_CFG = {
    .led_red_pa = 0x00, .led_ir_pa = 0x00,
    .adc_range = 3, .sample_rate = 2, .sample_avg = 1, .pulse_width = 3,
};

typedef enum { CH_AUTO = 0, CH_RED, CH_IR } ch_sel_t;

typedef struct { float v; bool beat; } disp_point_t;

typedef struct {
    bool sensor_ok;
    uint8_t part_id;
    const char *ch_name;
    ppg_state_t state;
    float hr;
    float dc;
    float ac_pp;
    float acf;
    uint32_t lost_total;
    uint32_t i2c_errors;
    bool alc_ovf_recent;
} status_t;

static QueueHandle_t s_disp_q;
static QueueHandle_t s_cfg_q;
static SemaphoreHandle_t s_status_mtx;
static SemaphoreHandle_t s_pin_mtx;   // GPIO11/12 driven by SPI xor I2C transfer in progress
static status_t s_status;
static volatile bool s_stream = true;
static volatile ch_sel_t s_ch_sel = CH_AUTO;

// ---------------------------------------------------------------- sensor

static void i2c_lock(void) { xSemaphoreTake(s_pin_mtx, portMAX_DELAY); }
static void i2c_unlock(void) { xSemaphoreGive(s_pin_mtx); }

static esp_err_t open_bus(int sda, int scl, i2c_master_bus_handle_t *bus)
{
    const i2c_master_bus_config_t cfg = {
        .i2c_port = I2C_NUM_0, .sda_io_num = sda, .scl_io_num = scl,
        .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    return i2c_new_master_bus(&cfg, bus);
}

// Diagnostic: list every address that ACKs on this pin pair (printed when the sensor is missing).
static void scan_bus(i2c_master_bus_handle_t bus, int sda, int scl)
{
    char found[128] = "";
    int len = 0;
    for (uint16_t a = 0x08; a < 0x78; a++) {
        if (i2c_master_probe(bus, a, 20) == ESP_OK && len < (int)sizeof found - 6)
            len += snprintf(found + len, sizeof found - len, "%s\"0x%02X\"", len ? "," : "", a);
    }
    printf("R,{\"scan\":{\"sda\":%d,\"scl\":%d,\"found\":[%s]}}\n", sda, scl, found);
}

// Diagnostic: idle level of each line with the internal pull-up, then pull-down (bus not open).
// A line that reads 0 with the pull-up is held low (short, unpowered module, wrong pin).
static void line_test(void)
{
    const int pins[2] = {I2C_PIN_A, I2C_PIN_B};
    int up[2], down[2];
    for (int i = 0; i < 2; i++) {
        gpio_reset_pin(pins[i]);
        gpio_set_direction(pins[i], GPIO_MODE_INPUT);
        gpio_set_pull_mode(pins[i], GPIO_PULLUP_ONLY);
        esp_rom_delay_us(200);
        up[i] = gpio_get_level(pins[i]);
        gpio_set_pull_mode(pins[i], GPIO_PULLDOWN_ONLY);
        esp_rom_delay_us(200);
        down[i] = gpio_get_level(pins[i]);
        gpio_set_pull_mode(pins[i], GPIO_FLOATING);
    }
    printf("R,{\"lines\":{\"gpio%d\":{\"pu\":%d,\"pd\":%d},\"gpio%d\":{\"pu\":%d,\"pd\":%d}}}\n",
           pins[0], up[0], down[0], pins[1], up[1], down[1]);

    // Bus recovery (I2C spec 3.1.16): if one line is held low and the other is high, the low one
    // is probably SDA held by a slave stopped mid-byte. Clock the high line (SCL) up to 16 times
    // as open drain until SDA is released, then send a STOP.
    for (int i = 0; i < 2; i++) {
        const int sda = pins[i], scl = pins[1 - i];
        if (!(up[i] == 0 && up[1 - i] == 1)) continue;
        gpio_set_pull_mode(sda, GPIO_PULLUP_ONLY);
        gpio_set_direction(scl, GPIO_MODE_INPUT_OUTPUT_OD);
        gpio_set_pull_mode(scl, GPIO_PULLUP_ONLY);
        int clocks = 0;
        for (; clocks < 16 && gpio_get_level(sda) == 0; clocks++) {
            gpio_set_level(scl, 0); esp_rom_delay_us(10);
            gpio_set_level(scl, 1); esp_rom_delay_us(10);
        }
        gpio_set_direction(sda, GPIO_MODE_INPUT_OUTPUT_OD);
        gpio_set_level(scl, 0); esp_rom_delay_us(10);
        gpio_set_level(sda, 0); esp_rom_delay_us(10);
        gpio_set_level(scl, 1); esp_rom_delay_us(10);
        gpio_set_level(sda, 1); esp_rom_delay_us(10);   // STOP
        gpio_set_direction(sda, GPIO_MODE_INPUT);
        esp_rom_delay_us(50);
        printf("R,{\"recover\":{\"sda\":%d,\"scl\":%d,\"clocks\":%d,\"sda_after\":%d,\"scl_after\":%d}}\n",
               sda, scl, clocks, gpio_get_level(sda), gpio_get_level(scl));
        gpio_reset_pin(sda);
        gpio_reset_pin(scl);
    }
}

static void set_status(void (*fn)(status_t *, void *), void *arg)
{
    xSemaphoreTake(s_status_mtx, portMAX_DELAY);
    fn(&s_status, arg);
    xSemaphoreGive(s_status_mtx);
}

static void st_sensor(status_t *s, void *arg) { s->sensor_ok = arg != NULL; }

static void sensor_task(void *arg)
{
    i2c_master_bus_handle_t bus = NULL;
    max30102_t dev = {0};
    max30102_cfg_t cfg = DEFAULT_CFG;
    static ppg_hr_t hr_red, hr_ir;
    max30102_sample_t buf[32];
    uint32_t seq = 0, lost_total = 0, i2c_err_total = 0;
    int consecutive_err = 0, decim = 0, since_update = 0;
    bool alc_recent = false;
    float disp_acc = 0.0f;
    bool disp_beat = false;

    for (;;) {
        // --- (re)initialise: try GPIO8=SDA/9=SCL, then swapped
        if (!dev.dev) {
            esp_err_t e = ESP_ERR_NOT_FOUND;
            const int pins[2][2] = {{I2C_PIN_A, I2C_PIN_B}, {I2C_PIN_B, I2C_PIN_A}};
            i2c_lock();
            for (int i = 0; i < 2 && e == ESP_ERR_NOT_FOUND; i++) {
                if (bus) { i2c_del_master_bus(bus); bus = NULL; }
                if (open_bus(pins[i][0], pins[i][1], &bus) != ESP_OK) continue;
                e = max30102_init(&dev, bus, &cfg);
                if (e != ESP_OK) scan_bus(bus, pins[i][0], pins[i][1]);
                if (e == ESP_OK) ESP_LOGI(TAG, "MAX30102 on SDA=GPIO%d SCL=GPIO%d", pins[i][0], pins[i][1]);
            }
            if (e != ESP_OK) {
                if (dev.dev) { i2c_master_bus_rm_device(dev.dev); dev.dev = NULL; }
                if (bus) { i2c_del_master_bus(bus); bus = NULL; }
                line_test();
                i2c_unlock();
                xSemaphoreTake(s_status_mtx, portMAX_DELAY);
                s_status.sensor_ok = false;
                s_status.part_id = dev.part_id;
                xSemaphoreGive(s_status_mtx);
                printf("R,{\"sensor\":false,\"err\":\"%s\",\"part_id\":%u}\n", esp_err_to_name(e), dev.part_id);
                vTaskDelay(pdMS_TO_TICKS(SENSOR_RETRY_MS));
                continue;
            }
            i2c_unlock();
            set_status(st_sensor, (void *)1);
            ppg_hr_init(&hr_red);
            ppg_hr_init(&hr_ir);
            consecutive_err = 0;
        }

        // --- configuration change from the console
        max30102_cfg_t nc;
        if (xQueueReceive(s_cfg_q, &nc, 0) == pdTRUE) {
            i2c_lock();
            const esp_err_t ce = max30102_apply_cfg(&dev, &nc);
            i2c_unlock();
            if (ce == ESP_OK) {
                cfg = nc;
                ppg_hr_init(&hr_red);
                ppg_hr_init(&hr_ir);
                printf("R,{\"cfg\":{\"red_ma\":%.1f,\"ir_ma\":%.1f,\"range\":%u,\"fs\":%.0f}}\n",
                       cfg.led_red_pa * 0.2f, cfg.led_ir_pa * 0.2f, cfg.adc_range, max30102_output_rate(&cfg));
                if (max30102_output_rate(&cfg) != PPG_FS_HZ)
                    printf("R,{\"warn\":\"output rate is not %d Hz: HR/state lines are not valid\"}\n", PPG_FS_HZ);
            } else {
                ESP_LOGE(TAG, "config write failed");
            }
        }

        // --- read the FIFO
        int n = 0, lost = 0;
        bool alc = false;
        i2c_lock();
        esp_err_t e = max30102_read_fifo(&dev, buf, 32, &n, &lost, &alc);
        i2c_unlock();
        if (e != ESP_OK) {
            i2c_err_total++;
            if (++consecutive_err >= MAX_READ_ERRORS) {
                ESP_LOGE(TAG, "MAX30102 not answering (%s), re-initialising", esp_err_to_name(e));
                i2c_master_bus_rm_device(dev.dev);
                dev.dev = NULL;
                set_status(st_sensor, NULL);
            }
            vTaskDelay(pdMS_TO_TICKS(SENSOR_POLL_MS));
            continue;
        }
        consecutive_err = 0;
        if (lost) { lost_total += lost; seq += lost; }   // keep seq honest about the gap
        alc_recent |= alc;

        for (int i = 0; i < n; i++, seq++) {
            const bool sat_r = alc || buf[i].red >= MAX30102_FULL_SCALE - SAT_MARGIN;
            const bool sat_i = alc || buf[i].ir >= MAX30102_FULL_SCALE - SAT_MARGIN;
            const float yr = ppg_hr_push(&hr_red, (float)buf[i].red, sat_r);
            const float yi = ppg_hr_push(&hr_ir, (float)buf[i].ir, sat_i);
            // channel shown/used: the one in a better state, IR on a tie
            const ppg_hr_t *use;
            if (s_ch_sel == CH_RED) use = &hr_red;
            else if (s_ch_sel == CH_IR) use = &hr_ir;
            else use = (hr_red.state > hr_ir.state ||
                        (hr_red.state == hr_ir.state && hr_red.acf_peak > hr_ir.acf_peak)) ? &hr_red : &hr_ir;
            const float y_use = (use == &hr_red) ? yr : yi;
            if (s_stream)
                printf("S,%" PRIu32 ",%" PRIu32 ",%" PRIu32 ",%.1f,%d\n", seq, buf[i].red, buf[i].ir, y_use, use->beat);
            disp_acc += y_use;
            disp_beat |= use->beat;
            if (++decim >= DISP_DECIM) {
                const disp_point_t pt = {disp_acc / DISP_DECIM, disp_beat};
                if (s_disp_q) xQueueSend(s_disp_q, &pt, 0);   // drop if the display falls behind
                decim = 0; disp_acc = 0.0f; disp_beat = false;
            }

            if (++since_update >= PPG_FS_HZ) {
                since_update = 0;
                ppg_hr_update(&hr_red);
                ppg_hr_update(&hr_ir);
                xSemaphoreTake(s_status_mtx, portMAX_DELAY);
                s_status.sensor_ok = true;
                s_status.part_id = dev.part_id;
                s_status.ch_name = (use == &hr_red) ? "RED" : "IR";
                s_status.state = use->state;
                s_status.hr = use->hr;
                s_status.dc = use->dc_out;
                s_status.ac_pp = use->ac_pp;
                s_status.acf = use->acf_peak;
                s_status.lost_total = lost_total;
                s_status.i2c_errors = i2c_err_total;
                s_status.alc_ovf_recent = alc_recent;
                xSemaphoreGive(s_status_mtx);
                printf("R,{\"t_ms\":%" PRId64 ",\"ch\":\"%s\",\"state\":\"%s\",\"hr\":%.1f,"
                       "\"red\":{\"state\":\"%s\",\"hr_acf\":%.1f,\"r\":%.2f,\"hr_rr\":%.1f,\"dc\":%.0f,\"ac_pp\":%.1f},"
                       "\"ir\":{\"state\":\"%s\",\"hr_acf\":%.1f,\"r\":%.2f,\"hr_rr\":%.1f,\"dc\":%.0f,\"ac_pp\":%.1f},"
                       "\"alc_ovf\":%d,\"lost\":%" PRIu32 ",\"i2c_err\":%" PRIu32 "}\n",
                       esp_timer_get_time() / 1000, s_status.ch_name, ppg_state_name(use->state), use->hr,
                       ppg_state_name(hr_red.state), hr_red.hr_acf, hr_red.acf_peak, hr_red.hr_peaks, hr_red.dc_out, hr_red.ac_pp,
                       ppg_state_name(hr_ir.state), hr_ir.hr_acf, hr_ir.acf_peak, hr_ir.hr_peaks, hr_ir.dc_out, hr_ir.ac_pp,
                       alc_recent, lost_total, i2c_err_total);
                alc_recent = false;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(SENSOR_POLL_MS));
    }
}

// ---------------------------------------------------------------- display
#if APP_USE_LCD

#define HDR_Y     0
#define HR_Y      16
#define HR_DW     34
#define HR_DH     60
#define HR_T      7
#define HR_GAP    9
#define STATE_Y   84
#define WAVE_Y    104
#define WAVE_H    (LCD_H - WAVE_Y)
#define SCALE_WIN LCD_W

static void draw_static(void)
{
    lcd_fill_rect(0, 0, LCD_W, LCD_H, C_BLACK);
    lcd_text(3 * (HR_DW + HR_GAP) + 4, HR_Y + HR_DH - 16, "BPM", 2, C_WHITE, C_BLACK);
    lcd_fill_rect(0, WAVE_Y - 2, LCD_W, 1, C_DGREY);
}

static void display_task(void *arg)
{
    if (lcd_init() != ESP_OK) {
        ESP_LOGE(TAG, "LCD init failed");
        vTaskDelete(NULL);
    }
    draw_static();

    static uint16_t col[WAVE_H];
    static float hist[SCALE_WIN];
    int x = 0, hist_n = 0, prev_y = WAVE_H / 2, beat_flash = 0;
    float lo = -1.0f, hi = 1.0f;
    char last_hr[4] = "", last_state[24] = "", last_hdr[40] = "";
    int64_t last_txt = 0;

    for (;;) {
        disp_point_t pt;
        if (xQueueReceive(s_disp_q, &pt, pdMS_TO_TICKS(100)) == pdTRUE) {
            hist[hist_n++ % SCALE_WIN] = pt.v;
            // autoscale over the last screen width, recomputed every 25 columns, eased
            if (hist_n % 25 == 0) {
                const int m = hist_n < SCALE_WIN ? hist_n : SCALE_WIN;
                float mn = hist[0], mx = hist[0];
                for (int i = 1; i < m; i++) { mn = fminf(mn, hist[i]); mx = fmaxf(mx, hist[i]); }
                const float pad = 0.1f * (mx - mn) + 1.0f;
                lo += 0.5f * ((mn - pad) - lo);
                hi += 0.5f * ((mx + pad) - hi);
            }
            int y = (int)((hi - pt.v) / (hi - lo) * (WAVE_H - 1));
            if (y < 0) y = 0;
            if (y >= WAVE_H) y = WAVE_H - 1;
            const int y0 = prev_y < y ? prev_y : y, y1 = prev_y < y ? y : prev_y;
            for (int i = 0; i < WAVE_H; i++) col[i] = (i == WAVE_H / 2 && (x & 3) == 0) ? C_DGREY : C_BLACK;
            for (int i = y0; i <= y1; i++) col[i] = C_GREEN;
            if (pt.beat) { col[0] = col[1] = col[2] = C_RED; beat_flash = 8; }
            lcd_blit(x, WAVE_Y, 1, WAVE_H, col);
            // erase bar ahead of the cursor
            for (int i = 0; i < WAVE_H; i++) col[i] = C_BLACK;
            lcd_blit((x + 6) % LCD_W, WAVE_Y, 1, WAVE_H, col);
            prev_y = y;
            x = (x + 1) % LCD_W;
            if (beat_flash > 0 && --beat_flash == 0) lcd_fill_rect(LCD_W - 22, HR_Y, 18, 18, C_BLACK);
            else if (beat_flash == 7) lcd_fill_rect(LCD_W - 22, HR_Y, 18, 18, C_RED);
        }

        const int64_t now = esp_timer_get_time();
        if (now - last_txt < 250000) continue;
        last_txt = now;
        status_t st;
        xSemaphoreTake(s_status_mtx, portMAX_DELAY);
        st = s_status;
        xSemaphoreGive(s_status_mtx);

        char hdr[40], hr[4], state[24];
        uint16_t scol = C_AMBER;
        if (!st.sensor_ok) {
            snprintf(hdr, sizeof hdr, "MAX30102 NOT FOUND");
            snprintf(state, sizeof state, st.part_id == MAX30100_PART_ID ? "MAX30100?" : "CHECK I2C");
            snprintf(hr, sizeof hr, "---");
            scol = C_RED;
        } else {
            snprintf(hdr, sizeof hdr, "%s DC %.0f", st.ch_name ? st.ch_name : "--", st.dc);
            if (st.state == PPG_STATE_OK && st.hr > 0.0f) snprintf(hr, sizeof hr, "%3d", (int)lroundf(st.hr));
            else snprintf(hr, sizeof hr, "---");
            snprintf(state, sizeof state, "%s%s", ppg_state_name(st.state), st.alc_ovf_recent ? " ALC" : "");
            if (st.state == PPG_STATE_OK) scol = C_GREEN;
            else if (st.state == PPG_STATE_SATURATED) scol = C_RED;
        }
        if (strcmp(hdr, last_hdr)) {
            const int ex = lcd_text(0, HDR_Y, hdr, 2, C_CYAN, C_BLACK);
            lcd_fill_rect(ex, HDR_Y, LCD_W - ex, 16, C_BLACK);
            strcpy(last_hdr, hdr);
        }
        if (strcmp(hr, last_hr)) {
            lcd_seg_number(0, HR_Y + 4, hr, HR_DW, HR_DH - 8, HR_T, HR_GAP,
                           strcmp(hr, "---") ? C_WHITE : C_GREY, C_BLACK);
            strcpy(last_hr, hr);
        }
        if (strcmp(state, last_state)) {
            const int ex = lcd_text(0, STATE_Y, state, 2, scol, C_BLACK);
            lcd_fill_rect(ex, STATE_Y, LCD_W - ex, 16, C_BLACK);
            strcpy(last_state, state);
        }
    }
}

#endif  // APP_USE_LCD

// ---------------------------------------------------------------- console

static void console_task(void *arg)
{
    char line[CONSOLE_LINE_MAX];
    int len = 0;
    max30102_cfg_t cfg = DEFAULT_CFG;
    for (;;) {
        uint8_t c;
        if (uart_read_bytes(UART_NUM_0, &c, 1, portMAX_DELAY) != 1) continue;
        if (c != '\n' && c != '\r') {
            if (len < CONSOLE_LINE_MAX - 1) line[len++] = (char)c;
            continue;
        }
        if (len == 0) continue;
        line[len] = '\0';
        len = 0;
        float a, b;
        int i;
        char w[8];
        if (sscanf(line, "led %f %f", &a, &b) == 2) {
            cfg.led_red_pa = MA_TO_PA(a);
            cfg.led_ir_pa = MA_TO_PA(b);
            xQueueSend(s_cfg_q, &cfg, portMAX_DELAY);
        } else if (sscanf(line, "range %d", &i) == 1 && i >= 0 && i <= 3) {
            cfg.adc_range = (uint8_t)i;
            xQueueSend(s_cfg_q, &cfg, portMAX_DELAY);
        } else if (sscanf(line, "sr %d", &i) == 1 && i >= 0 && i <= 3) {
            // Bench use: the HR estimator assumes 100 Hz output; other rates only make raw data sense.
            cfg.sample_rate = (uint8_t)i;
            xQueueSend(s_cfg_q, &cfg, portMAX_DELAY);
        } else if (sscanf(line, "avg %d", &i) == 1 && i >= 0 && i <= 5) {
            cfg.sample_avg = (uint8_t)i;
            xQueueSend(s_cfg_q, &cfg, portMAX_DELAY);
        } else if (sscanf(line, "stream %d", &i) == 1) {
            s_stream = i != 0;
        } else if (sscanf(line, "ch %7s", w) == 1) {
            s_ch_sel = !strcmp(w, "red") ? CH_RED : !strcmp(w, "ir") ? CH_IR : CH_AUTO;
        } else if (!strcmp(line, "rd")) {
            const bool was = s_stream;
            s_stream = false;                 // keep the dump readable; the sensor keeps running
            vTaskDelay(pdMS_TO_TICKS(50));
            const esp_err_t e = rd_probe_capture();
            printf("R,{\"rd\":\"%s\"}\n", esp_err_to_name(e));
            s_stream = was;
        } else if (!strcmp(line, "info")) {
            printf("R,{\"info\":{\"red_ma\":%.1f,\"ir_ma\":%.1f,\"range\":%u,\"fs\":%.0f,\"stream\":%d,\"ch\":%d}}\n",
                   cfg.led_red_pa * 0.2f, cfg.led_ir_pa * 0.2f, cfg.adc_range, max30102_output_rate(&cfg),
                   s_stream, s_ch_sel);
        } else {
            printf("R,{\"error\":\"unknown command\"}\n");
        }
    }
}

void app_main(void)
{
    // UART0 driver so the console task can read lines; stdout goes through the driver too.
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 1024, 8192, 0, NULL, 0));
    uart_vfs_dev_use_driver(UART_NUM_0);
    setvbuf(stdout, NULL, _IOLBF, 256);

    s_status_mtx = xSemaphoreCreateMutex();
    s_pin_mtx = xSemaphoreCreateMutex();
    configASSERT(s_pin_mtx);
#if APP_USE_LCD
    lcd_set_pin_lock(s_pin_mtx);
#endif
#if APP_USE_LCD
    s_disp_q = xQueueCreate(DISP_QUEUE_LEN, sizeof(disp_point_t));
    configASSERT(s_disp_q);
#endif
    s_cfg_q = xQueueCreate(2, sizeof(max30102_cfg_t));
    configASSERT(s_status_mtx && s_cfg_q);
    if (max30102_output_rate(&DEFAULT_CFG) != PPG_FS_HZ) ESP_LOGE(TAG, "sensor rate != estimator rate");

    xTaskCreatePinnedToCore(sensor_task, "sensor", 6144, NULL, 5, NULL, 1);
#if APP_USE_LCD
    xTaskCreatePinnedToCore(display_task, "display", 4096, NULL, 3, NULL, 0);
#endif
    xTaskCreatePinnedToCore(console_task, "console", 4096, NULL, 2, NULL, 0);
}
