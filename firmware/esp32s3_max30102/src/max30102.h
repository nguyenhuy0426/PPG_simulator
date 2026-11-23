// MAX30102 driver over the ESP-IDF 5.x I2C master API (register map: Maxim MAX30102 datasheet).
#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "esp_err.h"

#define MAX30102_ADDR        0x57
#define MAX30102_PART_ID     0x15
#define MAX30100_PART_ID     0x11   // older part, different register map: refused
#define MAX30102_FULL_SCALE  262143u   // 18-bit

typedef struct {
    uint8_t led_red_pa;   // LED1 (red) pulse amplitude, 0.2 mA per LSB (0..255 -> 0..51 mA)
    uint8_t led_ir_pa;    // LED2 (IR)
    uint8_t adc_range;    // 0: 2048 nA, 1: 4096, 2: 8192, 3: 16384 full scale
    uint8_t sample_rate;  // SPO2_SR code: 0:50 1:100 2:200 3:400 sps
    uint8_t sample_avg;   // SMP_AVE code: 0:1 1:2 2:4 3:8 4:16 5:32
    uint8_t pulse_width;  // LED_PW code: 0:69us/15bit 1:118/16 2:215/17 3:411/18
} max30102_cfg_t;

typedef struct {
    i2c_master_dev_handle_t dev;
    max30102_cfg_t cfg;
    uint8_t part_id, rev_id;
} max30102_t;

typedef struct { uint32_t red, ir; } max30102_sample_t;

// Probe and configure. Returns ESP_ERR_NOT_FOUND if nothing answers, ESP_ERR_NOT_SUPPORTED for a
// wrong part ID (part_id is filled in so the caller can report it).
esp_err_t max30102_init(max30102_t *m, i2c_master_bus_handle_t bus, const max30102_cfg_t *cfg);
esp_err_t max30102_apply_cfg(max30102_t *m, const max30102_cfg_t *cfg);
// Read every sample waiting in the FIFO (up to `max`). `*lost` gets the FIFO overflow count.
// `*alc_ovf` is set when the ambient-light-cancellation overflow flag was raised since the last read.
esp_err_t max30102_read_fifo(max30102_t *m, max30102_sample_t *out, int max, int *n, int *lost, bool *alc_ovf);
// Output sample rate after averaging, in Hz.
float max30102_output_rate(const max30102_cfg_t *cfg);
