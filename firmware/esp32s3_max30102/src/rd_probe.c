// Bench probe for the MAX30102 module's RD / IRD pins (LED cathodes, to be verified).
//
// Wiring (see docs/hardware/MAX30102_LED_SYNC_DESIGN.md §7): each pin goes through a 100k/100k divider
// to an ADC1 input, with Rp = 10k from the pin to the module's real VLED:
//   RD  -> 100k -> GPIO4 (ADC1_CH3) -> 100k -> GND
//   IRD -> 100k -> GPIO5 (ADC1_CH4) -> 100k -> GND
// The divider keeps the ADC input below 2.5 V even if VLED is 5 V.
//
// Command `rd` captures both inputs with the ADC DMA controller for RD_CAPTURE_MS, then prints
//   P,<pin>,<summary json>       min/max level, number of low pulses, mean width and period
//   D,<pin>,<t_us>,<mv>          every sample (mV at the ADC pin, i.e. half the pin voltage)
// The ADC rate limits edge resolution to RD_SAMPLE_US; it identifies pulses, it does not measure edges.
#include "rd_probe.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_continuous.h"
#include "esp_log.h"

static const char *TAG = "rd_probe";

#define RD_TOTAL_HZ     80000                       // both channels together (S3 max 83333)
#define RD_PER_CH_HZ    (RD_TOTAL_HZ / 2)
#define RD_SAMPLE_US    (1000000 / RD_PER_CH_HZ)    // 25 us
#define RD_CAPTURE_MS   40                          // 8 MAX30102 sample periods at 200 sps
#define RD_PER_CH       (RD_PER_CH_HZ * RD_CAPTURE_MS / 1000)
#define FRAME_BYTES     256
#define READ_TIMEOUT_MS 100

static const struct { const char *name; adc_channel_t ch; int gpio; } PINS[2] = {
    {"RD", ADC_CHANNEL_3, 4},
    {"IRD", ADC_CHANNEL_4, 5},
};

static uint16_t s_raw[2][RD_PER_CH];

static void summarize(int k, const int *mv, int n)
{
    int mn = mv[0], mx = mv[0];
    for (int i = 1; i < n; i++) { if (mv[i] < mn) mn = mv[i]; if (mv[i] > mx) mx = mv[i]; }
    const int thr = (mn + mx) / 2;
    int pulses = 0, width_sum = 0, period_sum = 0, periods = 0, last_fall = -1, fall = -1;
    for (int i = 1; i < n; i++) {
        if (mv[i - 1] >= thr && mv[i] < thr) {           // falling edge: LED turns on
            if (last_fall >= 0) { period_sum += i - last_fall; periods++; }
            last_fall = fall = i;
        } else if (fall >= 0 && mv[i - 1] < thr && mv[i] >= thr) {   // rising edge
            width_sum += i - fall; pulses++; fall = -1;
        }
    }
    printf("P,%s,{\"gpio\":%d,\"min_mv\":%d,\"max_mv\":%d,\"swing_mv\":%d,\"pulses\":%d,"
           "\"width_us\":%d,\"period_us\":%d,\"res_us\":%d}\n",
           PINS[k].name, PINS[k].gpio, mn, mx, mx - mn, pulses,
           pulses ? width_sum * RD_SAMPLE_US / pulses : 0,
           periods ? period_sum * RD_SAMPLE_US / periods : 0, RD_SAMPLE_US);
}

esp_err_t rd_probe_capture(void)
{
    adc_continuous_handle_t h = NULL;
    adc_cali_handle_t cali = NULL;
    const adc_continuous_handle_cfg_t hc = {.max_store_buf_size = 4096, .conv_frame_size = FRAME_BYTES};
    esp_err_t e = adc_continuous_new_handle(&hc, &h);
    if (e != ESP_OK) return e;

    adc_digi_pattern_config_t pat[2];
    for (int k = 0; k < 2; k++) {
        pat[k] = (adc_digi_pattern_config_t){
            .atten = ADC_ATTEN_DB_12, .channel = PINS[k].ch, .unit = ADC_UNIT_1, .bit_width = 12};
    }
    const adc_continuous_config_t cfg = {
        .pattern_num = 2, .adc_pattern = pat, .sample_freq_hz = RD_TOTAL_HZ,
        .conv_mode = ADC_CONV_SINGLE_UNIT_1, .format = ADC_DIGI_OUTPUT_FORMAT_TYPE2,
    };
    int n[2] = {0, 0};
    if ((e = adc_continuous_config(h, &cfg)) != ESP_OK) goto out;
    const adc_cali_curve_fitting_config_t cc = {
        .unit_id = ADC_UNIT_1, .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12};
    if ((e = adc_cali_create_scheme_curve_fitting(&cc, &cali)) != ESP_OK) goto out;
    if ((e = adc_continuous_start(h)) != ESP_OK) goto out;

    uint8_t frame[FRAME_BYTES];
    while (n[0] < RD_PER_CH || n[1] < RD_PER_CH) {
        uint32_t got = 0;
        e = adc_continuous_read(h, frame, sizeof frame, &got, READ_TIMEOUT_MS);
        if (e != ESP_OK) break;
        for (uint32_t i = 0; i + SOC_ADC_DIGI_RESULT_BYTES <= got; i += SOC_ADC_DIGI_RESULT_BYTES) {
            const adc_digi_output_data_t *d = (const adc_digi_output_data_t *)&frame[i];
            const int k = d->type2.channel == PINS[0].ch ? 0 : d->type2.channel == PINS[1].ch ? 1 : -1;
            if (k >= 0 && n[k] < RD_PER_CH) s_raw[k][n[k]++] = d->type2.data;
        }
    }
    adc_continuous_stop(h);
    if (e != ESP_OK) goto out;

    static int mv[RD_PER_CH];
    for (int k = 0; k < 2; k++) {
        for (int i = 0; i < n[k]; i++) adc_cali_raw_to_voltage(cali, s_raw[k][i], &mv[i]);
        summarize(k, mv, n[k]);
        for (int i = 0; i < n[k]; i++) printf("D,%s,%d,%d\n", PINS[k].name, i * RD_SAMPLE_US, mv[i]);
    }
out:
    if (e != ESP_OK) ESP_LOGE(TAG, "capture failed: %s", esp_err_to_name(e));
    if (cali) adc_cali_delete_scheme_curve_fitting(cali);
    adc_continuous_deinit(h);
    return e;
}
