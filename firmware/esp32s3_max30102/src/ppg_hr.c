#include "ppg_hr.h"

#include <math.h>
#include <string.h>

#define PI_F 3.14159265358979f

// Filters
#define HP_CUTOFF_HZ     0.5f
#define LP_CUTOFF_HZ     5.0f
#define DC_TAU_S         1.0f
// Peak detector
#define REFRACTORY_S     0.27f     // ~220 bpm
#define ENV_DECAY_PER_S  0.5f      // envelope falls to 50 % in 1 s without a new peak
#define PEAK_FRACTION    0.45f     // a peak must reach this fraction of the envelope
// Decision thresholds
#define ACF_MIN          0.50f     // below this the window has no clear period
#define AGREE_FRAC       0.12f     // ACF and RR HRs must agree within 12 %
#define HR_SMOOTH        0.35f     // EMA weight of a new HR value
#define SAT_MAX_PER_S    5         // more saturated samples than this in 1 s -> SATURATED
#define AC_MIN_COUNTS    8.0f      // band-passed peak-to-peak below this is treated as flat

static void biquad_set(ppg_biquad_t *q, bool highpass, float fc, float fs)
{
    // RBJ cookbook, Q = 1/sqrt(2) (Butterworth)
    const float w0 = 2.0f * PI_F * fc / fs;
    const float cw = cosf(w0), sw = sinf(w0);
    const float alpha = sw / (2.0f * 0.70710678f);
    const float a0 = 1.0f + alpha;
    float b0, b1, b2;
    if (highpass) {
        b0 = (1.0f + cw) / 2.0f; b1 = -(1.0f + cw); b2 = (1.0f + cw) / 2.0f;
    } else {
        b0 = (1.0f - cw) / 2.0f; b1 = 1.0f - cw; b2 = (1.0f - cw) / 2.0f;
    }
    q->b0 = b0 / a0; q->b1 = b1 / a0; q->b2 = b2 / a0;
    q->a1 = -2.0f * cw / a0; q->a2 = (1.0f - alpha) / a0;
    q->z1 = q->z2 = 0.0f;
}

static inline float biquad_run(ppg_biquad_t *q, float x)
{
    // transposed direct form II
    const float y = q->b0 * x + q->z1;
    q->z1 = q->b1 * x - q->a1 * y + q->z2;
    q->z2 = q->b2 * x - q->a2 * y;
    return y;
}

void ppg_hr_init(ppg_hr_t *p)
{
    memset(p, 0, sizeof(*p));
    biquad_set(&p->hp, true, HP_CUTOFF_HZ, PPG_FS_HZ);
    biquad_set(&p->lp, false, LP_CUTOFF_HZ, PPG_FS_HZ);
    p->state = PPG_STATE_WARMUP;
    p->polarity = 1.0f;
}

static void push_rr(ppg_hr_t *p, float rr)
{
    if (p->rr_count < PPG_RR_KEEP) {
        p->rr_s[p->rr_count++] = rr;
    } else {
        memmove(p->rr_s, p->rr_s + 1, sizeof(float) * (PPG_RR_KEEP - 1));
        p->rr_s[PPG_RR_KEEP - 1] = rr;
    }
}

float ppg_hr_push(ppg_hr_t *p, float raw, bool saturated)
{
    if (!p->primed) {
        // Start the filters from the first value so the DC step does not ring for seconds.
        p->dc = raw;
        p->primed = true;
    }
    const float k = 1.0f / (DC_TAU_S * PPG_FS_HZ);
    p->dc += k * (raw - p->dc);
    p->dc_out = p->dc;

    const float y = biquad_run(&p->lp, biquad_run(&p->hp, raw - p->dc));
    p->win[p->n % PPG_WIN] = y;
    p->n++;
    if (saturated) p->sat_recent++;

    // Peak detector relative to a decaying envelope. The pulse direction depends on the optics
    // (light rising or falling at systole), so ppg_hr_update picks the polarity whose
    // excursions are larger (the sharp systolic side) and the detector looks for maxima there.
    p->beat = false;
    const float yp = y * p->polarity;   // dominant pulse direction made positive
    const float a = fabsf(y);
    const float decay = powf(ENV_DECAY_PER_S, 1.0f / PPG_FS_HZ);
    p->env = (a > p->env) ? a : p->env * decay;
    // local maximum of the signal (one-sample delay): prev1 > prev2 and prev1 >= y
    if (p->prev1 > p->prev2 && p->prev1 >= yp && p->prev1 > PEAK_FRACTION * p->env && p->prev1 > 0.0f) {
        const uint32_t peak_n = p->n - 2;
        const float dt = (float)(peak_n - p->last_peak_n) / PPG_FS_HZ;
        if (p->last_peak_n == 0 || dt >= REFRACTORY_S) {
            if (p->last_peak_n != 0 && dt <= 60.0f / PPG_HR_MIN_BPM) push_rr(p, dt);
            else if (p->last_peak_n != 0) p->rr_count = 0;   // gap too long: restart RR history
            p->last_peak_n = peak_n;
            p->beat = true;
        }
    }
    p->prev2 = p->prev1;
    p->prev1 = yp;
    return yp;
}

static float median(float *v, int n)
{
    float t[PPG_RR_KEEP];
    memcpy(t, v, sizeof(float) * n);
    for (int i = 1; i < n; i++) {        // insertion sort, n <= 8
        float x = t[i]; int j = i - 1;
        while (j >= 0 && t[j] > x) { t[j + 1] = t[j]; j--; }
        t[j + 1] = x;
    }
    return (n & 1) ? t[n / 2] : 0.5f * (t[n / 2 - 1] + t[n / 2]);
}

// Normalized autocorrelation of the window at integer lag k (window in chronological order).
static float acf_at(const float *x, int n, int k, float e0)
{
    float s = 0.0f;
    for (int i = 0; i + k < n; i++) s += x[i] * x[i + k];
    return s / e0;
}

void ppg_hr_update(ppg_hr_t *p)
{
    const uint32_t sat = p->sat_recent;
    p->sat_recent = 0;

    if (p->n < PPG_WIN) { p->state = PPG_STATE_WARMUP; p->hr = 0.0f; return; }
    if (sat > SAT_MAX_PER_S) { p->state = PPG_STATE_SATURATED; p->hr = 0.0f; p->rr_count = 0; return; }

    // Unroll the ring into chronological order (static: 3.2 kB is too much for a small task stack).
    static float x[PPG_WIN];
    const uint32_t start = p->n % PPG_WIN;
    float mn = 1e30f, mx = -1e30f, e0 = 0.0f;
    for (int i = 0; i < PPG_WIN; i++) {
        const float v = p->win[(start + i) % PPG_WIN];
        x[i] = v;
        if (v < mn) mn = v;
        if (v > mx) mx = v;
        e0 += v * v;
    }
    p->ac_pp = mx - mn;
    // Dominant polarity: the systolic excursion is the larger one after the band-pass.
    if (mx + mn < -0.1f * p->ac_pp) p->polarity = -1.0f;
    else if (mx + mn > 0.1f * p->ac_pp) p->polarity = 1.0f;
    if (p->ac_pp < AC_MIN_COUNTS || e0 <= 0.0f) {
        p->state = PPG_STATE_NO_SIGNAL; p->hr = 0.0f; p->hr_acf = 0.0f; p->acf_peak = 0.0f;
        return;
    }

    // Autocorrelation peak in the HR lag range.
    const int kmin = (int)floorf(PPG_FS_HZ * 60.0f / PPG_HR_MAX_BPM);
    const int kmax = (int)ceilf(PPG_FS_HZ * 60.0f / PPG_HR_MIN_BPM);
    static float r[PPG_FS_HZ * 2 + 4];   // kmax = 172 at 35 bpm, 100 Hz
    for (int k = kmin - 1; k <= kmax + 1; k++) r[k] = acf_at(x, PPG_WIN, k, e0);
    int best = -1;
    float rbest = -1.0f;
    for (int k = kmin; k <= kmax; k++) {
        if (r[k] > r[k - 1] && r[k] >= r[k + 1] && r[k] > rbest) { rbest = r[k]; best = k; }
    }
    // Prefer the fundamental: if a local max at about half the lag is nearly as strong, take it.
    if (best > 0) {
        for (int k = best / 2 - 2; k <= best / 2 + 2; k++) {
            if (k >= kmin && k <= kmax && r[k] > r[k - 1] && r[k] >= r[k + 1] && r[k] > 0.85f * rbest) {
                best = k; rbest = r[k]; break;
            }
        }
    }
    p->acf_peak = rbest > 0.0f ? rbest : 0.0f;
    if (best > 0) {
        // parabolic interpolation around the peak
        const float ym = r[best - 1], y0 = r[best], yp = r[best + 1];
        const float den = ym - 2.0f * y0 + yp;
        const float d = (fabsf(den) > 1e-9f) ? 0.5f * (ym - yp) / den : 0.0f;
        p->hr_acf = 60.0f * PPG_FS_HZ / ((float)best + d);
    } else {
        p->hr_acf = 0.0f;
    }

    // Peak-interval HR (beats seen in the last few seconds only).
    const bool recent_beat = (p->n - p->last_peak_n) < (uint32_t)(PPG_FS_HZ * 60.0f / PPG_HR_MIN_BPM);
    p->hr_peaks = (recent_beat && p->rr_count >= 3) ? 60.0f / median(p->rr_s, p->rr_count) : 0.0f;

    if (p->hr_acf <= 0.0f || p->acf_peak < ACF_MIN) {
        p->state = PPG_STATE_NO_SIGNAL; p->hr = 0.0f;
        return;
    }
    const bool agree = p->hr_peaks > 0.0f && fabsf(p->hr_peaks - p->hr_acf) <= AGREE_FRAC * p->hr_acf;
    if (!agree) {
        p->state = PPG_STATE_LOW_QUALITY; p->hr = 0.0f;
        return;
    }
    p->state = PPG_STATE_OK;
    p->hr = (p->hr <= 0.0f) ? p->hr_acf : p->hr + HR_SMOOTH * (p->hr_acf - p->hr);
}

const char *ppg_state_name(ppg_state_t s)
{
    switch (s) {
    case PPG_STATE_WARMUP:      return "WARMUP";
    case PPG_STATE_SATURATED:   return "SATURATED";
    case PPG_STATE_NO_SIGNAL:   return "NO SIGNAL";
    case PPG_STATE_LOW_QUALITY: return "LOW QUALITY";
    case PPG_STATE_OK:          return "OK";
    }
    return "?";
}
