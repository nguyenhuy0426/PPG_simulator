// Host test for ppg_hr.c with synthetic PPG (not sensor data).
// Build: gcc -O2 -Wall -Wextra -fsanitize=address,undefined -I../src host_test_ppg_hr.c ../src/ppg_hr.c -lm
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "ppg_hr.h"

static float frand(void) { return (float)rand() / (float)RAND_MAX * 2.0f - 1.0f; }

// Two-Gaussian pulse (systolic peak + diastolic wave), phase in [0,1).
static float pulse(float ph)
{
    float a = expf(-powf((ph - 0.20f) / 0.07f, 2.0f));
    float b = 0.45f * expf(-powf((ph - 0.48f) / 0.10f, 2.0f));
    return a + b;
}

static int run(float hr, float ac, float noise, float polarity, bool expect_ok, float seconds)
{
    ppg_hr_t p;
    ppg_hr_init(&p);
    float ph = 0.0f;
    int n = (int)(seconds * PPG_FS_HZ);
    for (int i = 0; i < n; i++) {
        float raw = 100000.0f + polarity * ac * pulse(ph) + noise * frand() + 500.0f * sinf(2 * 3.14159f * 0.2f * i / PPG_FS_HZ);
        ph += hr / 60.0f / PPG_FS_HZ;
        if (ph >= 1.0f) ph -= 1.0f;
        ppg_hr_push(&p, raw, false);
        if ((i + 1) % PPG_FS_HZ == 0) ppg_hr_update(&p);
    }
    bool ok;
    if (expect_ok) ok = p.state == PPG_STATE_OK && fabsf(p.hr - hr) <= 2.0f;
    else ok = p.state != PPG_STATE_OK;
    printf("%s hr_set=%5.1f ac=%6.0f noise=%5.0f pol=%+.0f -> state=%-11s hr=%6.1f acf=%6.1f (r=%.2f) rr=%6.1f\n",
           ok ? "PASS" : "FAIL", hr, ac, noise, polarity, ppg_state_name(p.state), p.hr, p.hr_acf, p.acf_peak, p.hr_peaks);
    return ok ? 0 : 1;
}

int main(void)
{
    srand(1);
    int fail = 0;
    const float hrs[] = {40, 60, 75, 90, 120, 150, 180};
    for (unsigned i = 0; i < sizeof hrs / sizeof hrs[0]; i++) {
        fail += run(hrs[i], 2000, 50, +1, true, 20);
        fail += run(hrs[i], 2000, 50, -1, true, 20);
    }
    fail += run(75, 2000, 400, +1, true, 20);   // SNR ~ 5:1 pp
    fail += run(75, 0, 50, +1, false, 20);      // noise only -> must not report OK
    fail += run(75, 0, 0, +1, false, 20);       // flat -> must not report OK
    printf("%d failures\n", fail);
    return fail ? 1 : 0;
}
