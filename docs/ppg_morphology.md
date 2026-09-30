# PPG notch model: definition, correction and limitations

## What a dicrotic notch means

In a pulse-up PPG with clearly separated features, the dicrotic notch is the
local minimum on the descending limb between the systolic and diastolic peaks.
Some real pulses exhibit only an inflection/shoulder. Notch visibility varies
with age and measurement site; absence of a pronounced notch alone does not
make a PPG invalid. Reverse polarity before applying pulse-up definitions.

There is no universal `dicrotic_notch = 0.25` clinical standard. The old comment
"notch depth >=20% for normal" was not supported by a traceable reference and
has been removed. Defaults and condition presets are simulation settings, not
diagnostic thresholds or validated disease models.

Evidence:

- [Allen and Murray (2003)](https://pubmed.ncbi.nlm.nih.gov/12812416/): a study of
  116 healthy subjects found age-related changes in pulse shape, including
  damping of the notch, across ears, fingers and toes. This motivates avoiding
  a single mandatory notch depth for every subject.
- [Tang et al. (2020)](https://www.nature.com/articles/s41598-020-69076-x): PPG
  synthesis using two Gaussian components fitted to real templates provides
  precedent for a Gaussian envelope. It does **not** validate this project's
  constants, local attenuation formula, taper or condition presets.

## Implemented engineering convention (2026-09-25)

For phase `phi` in `[0, 1]`, define:

```
B(phi) = A_sys * G_sys(phi) + A_dia * G_dia(phi)
r(phi) = E(phi) * B(phi) * (1 - d * f * G_notch(phi))
p(phi) = r(phi) / max(r)
```

`G_*` are unit-height Gaussians. `d = dicrotic_notch` remains in `[0, 1]`.
`f` is the existing optional notch-fading multiplier, normally in `[0, 1]`.
The product `d*f` is defensively bounded to `[0, 1]`.

- At the notch **component centre**, `d=0.25`, `f=1` removes 25% of the local
  positive envelope **before peak normalization**. It does not remove 25% of
  the systolic peak amplitude.
- `d=0` means no additional indentation. A valley can remain between the two
  positive components. Do not label this control "notch absent".
- `d=1` is an extreme test value: the centre can touch the baseline at an
  isolated point, but a finite interval is not clipped flat. It is not a
  healthy-person preset.
- `d` is not a measured `DN/SP` ratio, nor the prominence `(DP-DN)/SP`.
  Those can be computed separately only when the relevant extrema exist.
- `dn_ms_ir/red` remain component-centre times at a 60 BPM reference cycle,
  not guaranteed measured notch locations. Overlapping components may merge;
  even `SP < DN < DP` does not guarantee three separate extrema.

`E` equals 1 except in the first and last 5% of a cycle. In each edge region
it is `3*u^2 - 2*u^3`, with `u` increasing from 0 at the endpoint to 1 toward
the interior. This makes the value and first derivative zero at both cycle
endpoints, avoiding the previous phase-wrap discontinuity. The 5% taper is
an **engineering choice**, not a physiological normal range. Feature centres
placed inside the edge regions can be shifted by the taper.

With nonnegative component amplitudes, the raw waveform is nonnegative by
construction. The final `[0, 1]` bound is numerical protection, not a repair
for a negative notch. Peak normalization includes the current `f` and is
cached until morphology or `f` changes, preserving AC peak ownership even
when notch and peak components overlap. No third-party dependency was added
to the production waveform code.

## Compatibility and migration

Config and BLE keep the existing key, numeric range, defaults and persisted
values. **Waveform compatibility is intentionally changed**: the former model
used `B - d*f*A_sys*G_notch` and clipped negative values to zero. Old recordings
must not be interpreted as having the new local-fraction semantics, and an
unchanged config does not imply an unchanged waveform. No automatic numerical
conversion is applied because it cannot preserve the entire old pulse across
different morphology and coupling settings. Keep the old source snapshot when
reproducing legacy experiments.

The current `config.json` and PCB changes were left untouched. The complete
pre-change backup is outside the repository:
`/home/huynn/final_project/PPG_simulator_raspi-backup-20260925-143036.tar.gz`.

HR timing, AC/DC, PI/SpO2 amplitude calculations, polarity, noise, respiration,
BLE protocol, and DAC scheduling were not redesigned. The existing optional
SpO2-to-notch factor remains a simulator heuristic, not a universal clinical
law; turn it off to inspect the nominal notch control independently.

## Verification and remaining scope

Regression tests in `tests/test_waveform.py` cover the local fraction, the
entire control range including the old clipping case `d=0.35`, zero-valued
smooth cycle joins, unit peaks under notch fading/overlap, and cache behavior.
Model integration tests cover dual-channel shape propagation and nominal AC
and ratio preservation with dynamics disabled.

These are mathematical/software guarantees, **not clinical validation**. The
default times, component widths and amplitude ratios have not been fitted to
a held-out real PPG cohort. No new physiological feature timing range is
enforced. Timing remains phase-scaled with HR; the model still runs at 100 Hz
before DAC interpolation. Hardware reproduction, optical calibration and
GAN validation require separate measurements.
