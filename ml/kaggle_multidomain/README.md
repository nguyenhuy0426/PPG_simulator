# PPG multidomain model experiment

Branch: `codex/ppg-multidomain-model-benchmark`.
Research artifacts stay under ignored `ml/runs/`; no simulator/DAC asset is replaced.

## Question and fixed protocol

Does additional patient diversity help the existing LSM-GAN? Does a long-receptive-field,
multiscale generator help further, and does distributional spectral matching add value?
Can a small diffusion model provide a useful quality/latency alternative?

| Arm | Training data | Generator / objective |
|---|---|---|
| `lsm_bidmc` | BIDMC train patients | Existing corrected LSM topology, BCE + matching + consistency |
| `lsm_multi` | All four training domains | Same LSM implementation and optimizer as the BIDMC arm |
| `tcn_multi` | All four training domains | Three input scales + dilated residual TCN; multiscale spectral-normalized hinge critic |
| `hybrid_multi` | All four training domains | Same TCN and critic, plus unpaired multiresolution spectral and ACF distribution loss |
| `diffusion_multi` | All four training domains | Small four-resolution 1D U-Net, 100-step cosine DDPM epsilon objective, 32-step DDIM sampling |

These are independent implementations/adaptations, **not** reproductions of Parallel WaveGAN
or Diffusion-TS. Inspiration: [LSM-GAN](https://arxiv.org/abs/2108.05272),
[Parallel WaveGAN](https://arxiv.org/abs/1910.11480),
[Diffusion-TS](https://arxiv.org/abs/2403.01742). In particular, the diffusion arm here does
not use Diffusion-TS's Transformer, decomposition, or clean-sample prediction objective.

Default: three seeds (42, 123, 2026), 2,000 updates per arm/seed, batch 32, validation
every 250 steps, 128 generated evaluation clips. Fifteen trained runs; equal steps and
batch size, **not equal compute**. CPU timings and training time are reported separately.
The staged research job requires **two Tesla T4 GPUs** and assigns independent
arm/seed runs to one spawned process per GPU. Batch 32 and optimizer steps remain
unchanged; this parallelizes the experiment rather than increasing each run's batch.
`configuration.json`, `training_execution.json`, and each `training_result.json`
record allocated GPUs, worker/device identity, peak CUDA memory and elapsed time.
The script fails before training if Kaggle does not allocate exactly two T4 GPUs.
This is a bounded first comparison, not a claim that all arms have converged or that
the winner is globally optimal. No ensemble is assumed superior before measurement.

## Data

- [BIDMC 1.0.0](https://physionet.org/content/bidmc/1.0.0/): retain the earlier patient
  partition in `bidmc_split.json`; ODC-By-1.0, Pimentel et al.
- [MIMIC PERform v2.0](https://zenodo.org/records/15906524): Large Training and Large
  Testing adult cohorts, plus AF and non-AF cohorts. Embedded ODbL-1.0 notices and
  annotation attribution are preserved in the output manifest. Cite Charlton et al.,
  *Detecting beats in the photoplethysmogram: benchmarking open-source algorithms*, 2022.
- [PTT PPG 1.0.0](https://physionet.org/content/pulse-transit-time-ppg/1.0.0/): all
  22 participants × sit/walk/run; channel **pleth_1**, without assuming its wavelength.
  Entire source reserved for external evaluation. Mehrgardt et al.; license copied
  from the pinned source into the manifest.

All files are checksum-checked. MAT sample rates come from source metadata; PTT from
WFDB headers. Shared preprocessing uses the existing LSM 40 Hz / 30 second / 0.9–5 Hz
zero-phase FIR / per-window [0,1] view so that architecture comparisons use identical
signals. Basic screening rejects nonfinite, flat and heavily clipped windows and
counts exclusions. It is not clinical signal-quality screening.

PERform Large stores metadata in `fix.mimic_details`; unmatched seven-digit IDs are
waveform groups, not independently verified clinical patients. AF/non-AF waveform
filenames join known records to matched patient IDs before splitting. Unknown record
groups retain an explicit identity limitation in the manifest. Canonical matched
MIMIC patient IDs are shared across cohorts. Official Large
Testing patients stay test-only. Possible BIDMC numeric-ID matches are excluded from
PERform rather than moved across the frozen BIDMC partition. Other cohorts are split
by unique patient with a fixed seed; overlapping patients inherit an existing split.
Exact normalized waveform duplicates are removed. A complete cross-release identity
crosswalk is unavailable, so related MIMIC datasets are not claimed as independent
external validation. PTT provides that independent source holdout.

Training draws balance **domain → patient → window**, preventing long recordings or
large cohorts from dominating. Each evaluation reference is sampled without replacement
with patient-balanced weights, capped at 128 windows. Reported patient counts refer to
the evaluated sample; full cohort counts are in the manifest. Small-domain uncertainty
must not be read as equivalent to a large external validation study.

## Selection and benchmark

Fit feature scales and RBF bandwidths on training data only. Select each checkpoint
by macro validation ACF MMD² + log-PSD MMD² + morphology MMD²; select an architecture
by the mean validation score over seeds. **Freeze every choice before any test score.**

Then evaluate held-out patients from four training domains and all three PTT activity
domains. Artifacts contain:

- ACF, log-PSD and morphology MMD²; 50 patient-bootstrap replicates per domain/run.
- Standardized Wasserstein distances for beat rate, IBI variability, pulse width/rise,
  skew, amplitude variability, slopes/curvature and residual high-frequency power.
- Feature precision/recall, two-sample 1-NN accuracy, generated diversity and nearest
  training feature/waveform distances against a fixed 512-draw reference.
- Real training replay and the frozen earlier LSM artifact as controls.
- Parameter counts, training seconds and one-thread host CPU median/p95 latency.
- Across-seed mean/SD, paired difference intervals and explicit per-domain regressions.
- `REPORT.md`, `summary.csv`, `improvements.json`, learning-curve/domain plots,
  checkpoints, optimizer/RNG states, generated samples and GAN TorchScript exports.

Three seeds and morphology proxies cannot establish clinical validity. The models are
unconditional: no controllable HR/AF and no calibrated AC/DC, SpO2 or paired IR/RED
claim. CPU timing is not a Raspberry Pi measurement. PTT motion is observed through
the common filtered view, not raw-motion fidelity. Test results must not guide a new
hyperparameter round without new holdout data or a nested evaluation design.

## Run

Use the project environment; optional WFDB dependency is isolated in
`requirements/multidomain.txt`. All shell examples follow the repository RTK convention.

```bash
rtk proxy uv pip install --python .venv/bin/python -r requirements/multidomain.txt
rtk proxy .venv/bin/python -m pytest -q tests/test_multidomain_ppg.py
rtk proxy .venv/bin/python -m ml.kaggle_multidomain.stage_kernel --mode prepare --output ml/runs/multidomain-prepare-kernel-v1
rtk proxy uv tool run --from kaggle kaggle kernels push -p ml/runs/multidomain-prepare-kernel-v1 --timeout 7200
```

After preparation completes, inspect its manifest/counts and then stage the GPU job:

```bash
rtk proxy .venv/bin/python -m ml.kaggle_multidomain.stage_kernel --mode train --output ml/runs/multidomain-train-kernel-v1
rtk proxy uv tool run --from kaggle kaggle kernels push -p ml/runs/multidomain-train-kernel-v1 --accelerator NvidiaTeslaT4 --timeout 10800
rtk proxy uv tool run --from kaggle kaggle kernels status charlesday2612/ppg-multidomain-model-benchmark
rtk proxy uv tool run --from kaggle kaggle kernels output charlesday2612/ppg-multidomain-model-benchmark -p ml/runs/multidomain-result-v1
```

`stage_kernel.py` embeds exact local sources and records their SHA-256 hashes. Output
folders must be new; existing runs are not overwritten. Raw files are cached under
`/tmp` on Kaggle; preparation uses CPU, training uses GPU. New kernels are private and
use separate IDs from the previous BIDMC experiment. `COMPLETE.json` is written only
after every trained arm, control, benchmark and report finishes. Running/queued status
is not completion. No artifacts are automatically promoted into simulator runtime.
