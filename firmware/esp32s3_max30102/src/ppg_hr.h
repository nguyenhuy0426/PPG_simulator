// Heart-rate estimation from one PPG channel (pure C, no ESP-IDF dependency, host-testable).
//
// Pipeline per sample: raw ADC count -> DC (slow EMA) -> band-pass 0.5..5 Hz (two biquads)
// -> polarity-agnostic HR by normalized autocorrelation over the last PPG_WIN_S seconds,
// plus beat marks from an adaptive-threshold peak detector (for the display / RR check).
//
// This is an engineering estimate of pulse rate from a waveform. It is not a validated
// or clinical heart-rate measurement.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#define PPG_FS_HZ        100     // sample rate the estimator is built for
#define PPG_WIN_S        8       // autocorrelation window
#define PPG_WIN          (PPG_FS_HZ * PPG_WIN_S)
#define PPG_HR_MIN_BPM   35.0f
#define PPG_HR_MAX_BPM   220.0f
#define PPG_RR_KEEP      8

typedef enum {
    PPG_STATE_WARMUP = 0,   // window not yet full
    PPG_STATE_SATURATED,    // raw at/near ADC full scale or ALC overflow
    PPG_STATE_NO_SIGNAL,    // no periodic component (flat, or noise only)
    PPG_STATE_LOW_QUALITY,  // periodic but autocorrelation and peak intervals disagree
    PPG_STATE_OK,
} ppg_state_t;

typedef struct { float b0, b1, b2, a1, a2, z1, z2; } ppg_biquad_t;

typedef struct {
    // filters
    ppg_biquad_t hp, lp;
    float dc;
    bool primed;
    // history of the band-passed signal (ring)
    float win[PPG_WIN];
    uint32_t n;            // samples consumed since reset
    // peak detector
    float env;             // amplitude envelope (decays)
    float polarity;        // +1 or -1: sign that makes the systolic excursion positive
    float prev2, prev1;
    uint32_t last_peak_n;
    float rr_s[PPG_RR_KEEP];
    int rr_count;
    bool beat;             // set for the sample at which a peak was confirmed
    // saturation bookkeeping (over the last second)
    uint32_t sat_recent;
    // outputs (refreshed by ppg_hr_update, about once per second)
    float hr_acf;          // bpm, 0 if none
    float acf_peak;        // normalized autocorrelation at the chosen lag (0..1)
    float hr_peaks;        // bpm from median RR, 0 if none
    float hr;              // reported bpm (smoothed), 0 if invalid
    float ac_pp;           // peak-to-peak of band-passed signal over the window (ADC counts)
    float dc_out;          // current DC (ADC counts)
    ppg_state_t state;
} ppg_hr_t;

void ppg_hr_init(ppg_hr_t *p);
// Feed one raw sample. `saturated` = caller-detected saturation/ALC overflow for this sample.
// Returns the band-passed value with the dominant pulse direction made positive (for display).
float ppg_hr_push(ppg_hr_t *p, float raw, bool saturated);
// Recompute HR/state from the current window. Call about once per second.
void ppg_hr_update(ppg_hr_t *p);
const char *ppg_state_name(ppg_state_t s);
