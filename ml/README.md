# PPG cWGAN-GP pilot

Run v1 completed on Kaggle T4. **Not approved for deployment**: notch recall
was 2/103 (1.94%) on the evaluated test subset and boundary ripples remain.
See the [Vietnamese results report](../docs/ppg_gan_report_2026-09-26.md).

The additional [LSM-GAN experiment](kaggle_lsm/README.md) uses 30-second
40 Hz strips, trains/exports both G and D, and includes paper-objective,
corrected author-code-objective and no-spectral ablation arms. It is separate
from the conditional single-pulse interface; see the
[LSM report](../docs/ppg_lsm_gan_report_2026-09-26.md).

The follow-up [conditional architecture sweep](kaggle_arch/README.md) compares
five G/D configurations over three seeds. TCN-FiLM with a projection critic won
by validation and is the current research candidate; see the
[architecture report](../docs/ppg_architecture_sweep_report_2026-09-26.md).
It has not replaced the live generator or Gaussian fallback.

The training pipeline remains **offline research**, not a replacement for the
live PPG engine or an independently learned IR/Red model. The app now has an
optional **04 Neural** screen for original Gaussian / cWGAN-GP / LSM-GAN / TCN-FiLM CPU inference,
side-by-side preview, model switching and native-rate CSV export. It never
drives the DAC. PyTorch is loaded only when the user requests generation.
Install `requirements/neural.txt` in the app environment, then run
`scripts/prepare_neural_preview.py` with the downloaded runs present (or copy
the prepared `assets/neural` bundle). See the
[verified results and Pi preview guide](../docs/ppg_neural_preview_report_2026-09-28.md).

The [round 2 report](../docs/ppg_round2_report_2026-09-28.md) supersedes the
two-model UI instructions: four modes, two simultaneous plots, independent
validation metrics, a 240-pulse human-review page, and a gated three-arm
fine-tuning pipeline. Only the two-step pipeline smoke has run; human-reviewed
fine-tuning and an unseen external cohort remain pending.

The [Gaussian fit](../docs/ppg_gaussian_fit_2026-09-28.md) tunes the existing
three-Gaussian formula on train data and evaluates all validation pulses.
`ml.fit_gaussian` reproduces the fit; `assets/gaussian/profiles.json` supplies
stdlib-only fitted previews alongside the unchanged original Gaussian.

## Reproduce

From the repository root (an isolated Python environment is recommended):

```bash
uv venv .venv-ml
uv pip install --python .venv-ml/bin/python -r requirements/ml.txt
.venv-ml/bin/python -m pytest tests/test_ml_ppg.py -q
.venv-ml/bin/python ml/kaggle/train_ppg.py --prepare-only --output ml/runs/prepared
.venv-ml/bin/python ml/kaggle/train_ppg.py --steps 1500 --output ml/runs/pilot-local
```

The local command can run on CPU; Kaggle refuses to train without a GPU. The
verified public MAT file can be cached at `dataset/bidmc/bidmc_data.mat`.
Otherwise the script downloads it from PhysioNet, then checks SHA-256. Use a
new output directory for each experiment. Keep dataset and run artifacts out
of Git. Python 3.11/3.12 is preferable to 3.14 for TorchScript compatibility.

Kaggle CLI, after authenticating locally (never put credentials in this repo):

```bash
uv tool run --from kaggle kaggle quota
uv tool run --from kaggle kaggle kernels push -p ml/kaggle --timeout 1800 --accelerator NvidiaTeslaT4
uv tool run --from kaggle kaggle kernels status charlesday2612/ppg-cwgan-gp-bidmc-pilot
uv tool run --from kaggle kaggle kernels logs charlesday2612/ppg-cwgan-gp-bidmc-pilot
uv tool run --from kaggle kaggle kernels output charlesday2612/ppg-cwgan-gp-bidmc-pilot -p ml/runs/kaggle-v1
.venv-ml/bin/python -m ml.evaluate_run ml/runs/kaggle-v1/ppg_run
```

Metadata makes the kernel private. Only the standalone training script is
uploaded; project configuration, PCB files and secrets are not inputs. The
timeout includes environment startup, downloads, preprocessing and training.
GPU usage consumes the account's Kaggle quota.

## Data and morphology contract

[BIDMC PPG and Respiration Dataset 1.0.0](https://physionet.org/content/bidmc/1.0.0/),
Pimentel et al., *Toward a Robust Estimation of Respiratory Rate From Pulse
Oximeters*, IEEE TBME 2017, DOI:10.1109/TBME.2016.2613126. License: Open Data
Commons Attribution 1.0. It provides critical-care PPG, not paired raw red and
infrared optical waveforms or manually labelled dicrotic notches. Retain this
attribution with derived data and models.

- Input sampling rate comes from each record's `ppg.fs` (125 Hz here).
- Group by **original MIMIC patient ID**, not recording number or individual
  beat. Multiple BIDMC recordings can belong to one patient. Seed 42 assigns
  70/15/15% of unique patients to train/validation/test (rounded down).
- NeuroKit2 Elgendi cleaning/peak detection locates systolic beats. A separate
  fourth-order, zero-phase 12 Hz lowpass trace supplies morphology, followed
  by foot-to-foot segmentation, linear baseline subtraction, peak scaling
  and PCHIP interpolation to 256 phase points, including both endpoints.
- Engineering inclusion: HR 40–180 BPM, SP phase 0.05–0.55; reject flat traces,
  baseline undershoot worse than 5% of pulse height and more than three large
  peaks. Lesser negative baseline residuals are clipped before interpolation.
  These rules are **not clinical normal ranges** and are not a complete motion
  artifact or arrhythmia screen. Filtering and segmentation can alter notches.
- SP = global pulse maximum. DP = first later local peak with at least 2% SP
  prominence, more than 6% cycle after SP and before phase 0.90. DN = local
  minimum between them. Peak separation is at least 3% cycle. Inflections
  without a resolvable second peak receive `has_notch=0`; they are not labelled
  unhealthy. Pseudo-labels still need visual/manual review.
- Condition: `[HR/200, SP_phase, DN_phase, DP_phase, DN/SP, DP/SP, has_notch]`.
  Missing DN/DP fields are zero, with a separate presence flag. These are
  measured extrema, **not Gaussian component centers or `dicrotic_depth`**.
- No age, disease, SpO2 or sensor-site conditioning is learned in this pilot.
  Conditions must stay in training support; independent min/max bounds do not
  establish that an arbitrary combination is feasible.

## Training and evaluation

Lightweight 1D conditional generator: 32-dimensional latent vector, 7
conditions, dense layers followed by three linear upsampling/convolution
stages. Output is one nonnegative unit-height pulse with zero endpoints.
Critic has strided convolutions and no batch normalization. There are 284,321
generator parameters. This is a project-specific architecture, not a claim
that one published PPG model has been reproduced.

Wasserstein objective with gradient penalty 10, five critic updates per
generator update, Adam `lr=1e-4, betas=(0,0.9)`, batch 64. A weak differentiable
landmark penalty (weight 10) encourages condition adherence; it is an
experimental addition, not a physiological theorem. There is no paired
waveform L1 loss. Reference: [Gulrajani et al. (2017)](https://arxiv.org/abs/1704.00028).

Checkpoint selection uses a fixed validation subset and condition error only;
the final selected checkpoint is evaluated once on 512 held-out test beats.
That selection score alone is insufficient to establish realistic shape.
The two-step local smoke test verifies execution, not model quality.

Comparators:

1. **Current default Gaussian**: the corrected project's default morphology,
   sampled on the same phase grid. A regression test checks equality. It is
   neither condition-matched nor fitted, so beating it is not evidence of
   beating an optimized Gaussian model or the user's saved config.
2. **Real replay**: nearest condition vector from training patients only.
   This is a strong practical baseline; it intentionally reuses real pulses.
3. **Held-out real**: reference morphology; it is not used as the replay bank.

Report SP/DN/DP errors, notch presence accuracy, SP distribution distance,
pointwise variation, fixed-condition variation, roughness and distance to a
seeded 2,048-pulse training subset. DN/DP error is conditional on both target
and output having a detected notch, so it must be read alongside recall and
the matched count. Nearest-neighbor distance to a subset is only a limited
memorization diagnostic, not a privacy guarantee. Aggregate beat metrics
weight patients unequally; patient-level confidence intervals, repeat seeds,
optimized Gaussian fitting and external-cohort tests remain future validation.

Outputs include `manifest.json`, `prepared.npz`, `history.json`,
`generator_best.pt`, `generator_cpu.ts`, `metrics.json`, `test_samples.npz`,
`comparison.png`, and IR/Red CSV examples. `manifest.json` retains source Fs,
patient splits, per-record rejection counts, condition schema and train bounds.
`metrics.json` records software versions, device, seed and training-code hash.

## Fs, IR/RED and Raspberry Pi

`256` is a phase-grid length, **not 256 Hz**. For clock `Fs` and heart rate `HR`:

```text
t[n] = n/Fs
phase[n] = (t[n] * HR/60) mod 1
p[n] = interpolate(G(z, condition), phase[n])
samples_per_cycle = Fs * 60/HR
IR[n]  = DC_IR  + polarity * AC_IR  * p[n]
RED[n] = DC_RED + polarity * AC_RED * p[n]
R = max(0, (A - SpO2)/B)
AC_RED = R * AC_IR * DC_RED/DC_IR
```

Example: `HR=75`, `Fs=100` gives 80 samples/beat; `Fs=1000` gives 800.
With A=110, B=25, SpO2=98, equal DC=1.5 V, and AC_IR=45 mV, R=0.48 and
AC_RED=21.6 mV. These coefficients are the simulator's assumed calibration,
not a universal physiological law. DC means the existing pedestal parameter,
not the time-average voltage. Pinning AC_RED or using actual optical hardware
requires preserving/rechecking the existing calibration policy.

The CSV renderer exports exact configured timestamps and rejects voltage rail
violations. It does not measure a physical clock, validate optical SpO2, add
respiration/noise, or anti-alias for arbitrary low output Fs. Exporting 1000 Hz
does not recover information absent from the 125 Hz source. Evaluate bandwidth
and filtering before changing the production sample-rate path.

Deployment direction: load the CPU artifact on Pi, generate/cache a pulse
outside the DAC timing loop, then let the existing phase/AC/DC/polarity pipeline
render it. Current model rate is 100 Hz and timer configuration is 1000 Hz;
their physical accuracy has not been measured in this work. Keep the Gaussian
engine as fallback. Do not install GPU training dependencies in the live app.
Benchmark on the actual Pi model, OS and architecture before choosing a runtime;
TorchScript export alone is not proof of Pi compatibility or real-time safety.
No default engine switch, UI/BLE contract change, optical output or Pi
deployment is performed by this pipeline.
