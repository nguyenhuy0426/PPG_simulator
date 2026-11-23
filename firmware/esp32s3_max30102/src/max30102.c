#include "max30102.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "max30102";

// Registers
#define REG_INTR_STATUS_1  0x00
#define REG_INTR_STATUS_2  0x01
#define REG_INTR_ENABLE_1  0x02
#define REG_INTR_ENABLE_2  0x03
#define REG_FIFO_WR_PTR    0x04
#define REG_OVF_COUNTER    0x05
#define REG_FIFO_RD_PTR    0x06
#define REG_FIFO_DATA      0x07
#define REG_FIFO_CONFIG    0x08
#define REG_MODE_CONFIG    0x09
#define REG_SPO2_CONFIG    0x0A
#define REG_LED1_PA        0x0C
#define REG_LED2_PA        0x0D
#define REG_REV_ID         0xFE
#define REG_PART_ID        0xFF

#define MODE_RESET         0x40
#define MODE_SPO2          0x03     // red + IR
#define INTR1_ALC_OVF      0x20
#define FIFO_ROLLOVER_EN   0x10
#define FIFO_DEPTH         32
#define BYTES_PER_SAMPLE   6        // 3 bytes red + 3 bytes IR in SpO2 mode
#define I2C_TIMEOUT_MS     20
#define I2C_SPEED_HZ       100000   // modules with 4.7k pull-ups to 1.8 V have slow edges
#define RESET_POLL_MS      5
#define RESET_TIMEOUT_MS   100

static esp_err_t wr(max30102_t *m, uint8_t reg, uint8_t val)
{
    const uint8_t b[2] = {reg, val};
    return i2c_master_transmit(m->dev, b, sizeof b, I2C_TIMEOUT_MS);
}

static esp_err_t rd(max30102_t *m, uint8_t reg, uint8_t *buf, size_t len)
{
    return i2c_master_transmit_receive(m->dev, &reg, 1, buf, len, I2C_TIMEOUT_MS);
}

float max30102_output_rate(const max30102_cfg_t *cfg)
{
    static const float sr[] = {50, 100, 200, 400, 800, 1000, 1600, 3200};
    return sr[cfg->sample_rate & 7] / (float)(1u << (cfg->sample_avg > 5 ? 5 : cfg->sample_avg));
}

esp_err_t max30102_apply_cfg(max30102_t *m, const max30102_cfg_t *cfg)
{
    esp_err_t e;
    m->cfg = *cfg;
    // Disable interrupts we do not use (no INT pin wired); flags are still readable by polling.
    if ((e = wr(m, REG_INTR_ENABLE_1, 0x00)) != ESP_OK) return e;
    if ((e = wr(m, REG_INTR_ENABLE_2, 0x00)) != ESP_OK) return e;
    if ((e = wr(m, REG_FIFO_CONFIG, (uint8_t)((cfg->sample_avg & 7) << 5) | FIFO_ROLLOVER_EN | 0x0F)) != ESP_OK) return e;
    if ((e = wr(m, REG_SPO2_CONFIG, (uint8_t)(((cfg->adc_range & 3) << 5) | ((cfg->sample_rate & 7) << 2) | (cfg->pulse_width & 3)))) != ESP_OK) return e;
    if ((e = wr(m, REG_LED1_PA, cfg->led_red_pa)) != ESP_OK) return e;
    if ((e = wr(m, REG_LED2_PA, cfg->led_ir_pa)) != ESP_OK) return e;
    // Empty the FIFO so old samples taken with the previous settings are not mixed in.
    if ((e = wr(m, REG_FIFO_WR_PTR, 0)) != ESP_OK) return e;
    if ((e = wr(m, REG_OVF_COUNTER, 0)) != ESP_OK) return e;
    if ((e = wr(m, REG_FIFO_RD_PTR, 0)) != ESP_OK) return e;
    return wr(m, REG_MODE_CONFIG, MODE_SPO2);
}

esp_err_t max30102_init(max30102_t *m, i2c_master_bus_handle_t bus, const max30102_cfg_t *cfg)
{
    esp_err_t e = i2c_master_probe(bus, MAX30102_ADDR, I2C_TIMEOUT_MS);
    if (e != ESP_OK) return ESP_ERR_NOT_FOUND;
    if (!m->dev) {
        const i2c_device_config_t dc = {
            .dev_addr_length = I2C_ADDR_BIT_LEN_7,
            .device_address = MAX30102_ADDR,
            .scl_speed_hz = I2C_SPEED_HZ,
        };
        if ((e = i2c_master_bus_add_device(bus, &dc, &m->dev)) != ESP_OK) return e;
    }
    if ((e = rd(m, REG_PART_ID, &m->part_id, 1)) != ESP_OK) return e;
    if ((e = rd(m, REG_REV_ID, &m->rev_id, 1)) != ESP_OK) return e;
    if (m->part_id != MAX30102_PART_ID) {
        ESP_LOGE(TAG, "part id 0x%02X at 0x%02X is not a MAX30102 (0x15)%s", m->part_id, MAX30102_ADDR,
                 m->part_id == MAX30100_PART_ID ? " - this is a MAX30100" : "");
        return ESP_ERR_NOT_SUPPORTED;
    }
    if ((e = wr(m, REG_MODE_CONFIG, MODE_RESET)) != ESP_OK) return e;
    uint8_t mode = MODE_RESET;
    for (int t = 0; t < RESET_TIMEOUT_MS && (mode & MODE_RESET); t += RESET_POLL_MS) {
        vTaskDelay(pdMS_TO_TICKS(RESET_POLL_MS));
        if ((e = rd(m, REG_MODE_CONFIG, &mode, 1)) != ESP_OK) return e;
    }
    if (mode & MODE_RESET) return ESP_ERR_TIMEOUT;
    uint8_t st[2];
    rd(m, REG_INTR_STATUS_1, st, 2);   // clear power-ready flag
    ESP_LOGI(TAG, "MAX30102 rev 0x%02X found", m->rev_id);
    return max30102_apply_cfg(m, cfg);
}

esp_err_t max30102_read_fifo(max30102_t *m, max30102_sample_t *out, int max, int *n, int *lost, bool *alc_ovf)
{
    *n = 0; *lost = 0; *alc_ovf = false;
    uint8_t st;
    esp_err_t e = rd(m, REG_INTR_STATUS_1, &st, 1);   // reading clears the flags
    if (e != ESP_OK) return e;
    *alc_ovf = (st & INTR1_ALC_OVF) != 0;

    uint8_t ptr[3];   // WR_PTR, OVF_COUNTER, RD_PTR are consecutive
    if ((e = rd(m, REG_FIFO_WR_PTR, ptr, 3)) != ESP_OK) return e;
    int avail = (ptr[0] - ptr[2]) & (FIFO_DEPTH - 1);
    *lost = ptr[1];
    if (ptr[1] != 0 && avail == 0) avail = FIFO_DEPTH;   // full FIFO wraps WR == RD
    if (avail > max) avail = max;
    if (avail == 0) return ESP_OK;

    uint8_t buf[FIFO_DEPTH * BYTES_PER_SAMPLE];
    if ((e = rd(m, REG_FIFO_DATA, buf, (size_t)avail * BYTES_PER_SAMPLE)) != ESP_OK) return e;
    for (int i = 0; i < avail; i++) {
        const uint8_t *b = &buf[i * BYTES_PER_SAMPLE];
        out[i].red = (((uint32_t)b[0] << 16) | ((uint32_t)b[1] << 8) | b[2]) & MAX30102_FULL_SCALE;
        out[i].ir  = (((uint32_t)b[3] << 16) | ((uint32_t)b[4] << 8) | b[5]) & MAX30102_FULL_SCALE;
    }
    *n = avail;
    return ESP_OK;
}
