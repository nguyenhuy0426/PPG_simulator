# LSM-GAN comparison: implementation contract

Independent research reimplementation informed by [Ding et al., arXiv v2](https://arxiv.org/abs/2108.05272v2)
and [author code](https://github.com/chengding0713/Log-Spectral-matching-GAN/tree/d2d01feab0cec7c129bae0b63c56277adc4f48cc).
This is not a reproduction of the paper's AF classifier results. Source code
from the author repository is not vendored; implementation differences are
explicit below. Existing cWGAN code and v1 results remain unchanged.

Kaggle version 2 completed all three 1,500-step arms on T4. Artifacts are in
`ml/runs/lsm-kaggle-v2/lsm_comparison/`; see the [Vietnamese results report](../../docs/ppg_lsm_gan_report_2026-09-26.md).
The matched BCE spectral-loss arm reduced mean log-PSD RMSE from 2.03235 to
1.73491, but ACF MMD² did not improve and real/generated spectra still differ.
All exports passed local G/D parity checks; no model is approved for DAC use.

## Why a separate experiment

The current product learns a **conditioned single pulse** at 256 phase points.
LSM uses **30-second segments at 40 Hz**, with noise and output length 1200.
Spectral block self-consistency concerns multiple beats. Applying it blindly
to systolic and diastolic parts of one pulse would impose the wrong target.

LSM here has no condition inputs. In particular, it does not yet offer HR,
SP/DN/DP, SpO2 or disease controls. Its output length has a physical time scale
because its training windows retain Fs=40 Hz, unlike the phase-only cWGAN.
Resampling output does not make arbitrary clock rates learned capabilities.

## Discriminator/critic architecture

| Model | Network | Parameters | Output |
|---|---|---:|---|
| Existing cWGAN v1 critic | Conv1D 8→16→32→32, kernel 7/stride 2, LeakyReLU; Flatten→Linear 1024→1 | 12,753 | Unbounded score; no sigmoid/BatchNorm |
| LSM discriminator | Conv1D 1→64→128→256→512, kernel 4/stride 2; BN after stages 2–4, LeakyReLU; Conv 512→1; Linear 72→2 | 692,370 | Two sigmoid real/fake scores |

The critic's 8 input channels are one waveform plus seven broadcast condition
values. LSM's two outputs BOTH use real=1/fake=0 targets; they are **not AF
and non-AF classes**, and do not sum to one. This unusual head is retained
from the reference topology. Discriminator size alone does not establish
that it is superior. The larger D is used only for training/evaluation, not
needed in the Pi generation loop.

LSM generator: parallel same-length convolution branches (kernel/channels
5/80, 21/40, 61/20), concatenation, 15/50 merge, 4/50 then 2/1 output
convolutions with tanh and per-window minmax. No upsampling. Parameter count
117,940. Denominator guards are added for numerical stability.

## Paper and code are not identical

| Arm | Adversarial objective | Spectral matching | Weights match/self |
|---|---|---|---|
| `lsm_paper` | Least squares, following paper equation 3 | Same-position blocks | 1 / 1 |
| `lsm_repo_corrected` | BCE, as in released training script | All real/fake block pairs | 1 / 1 |
| `dcgan1200_no_spectral` | BCE | Disabled | 0 / 0 |

The paper supplies the objective and multi-block matching concept; the
released `models_1200.py` supplies the detailed layer dimensions. All three
arms use the same G and D topology, initialization, batches, seeds, validation
noise, training budget and selection metric. The code-matched arm and
no-spectral control isolate adding spectral loss; comparing paper vs code
arms changes both adversarial loss and pairing, so cannot isolate either one.
Equation 3 explicitly specifies the generator objective. For `lsm_paper`,
the matching least-squares D objective is a declared implementation choice;
the released training script instead supplies BCE for both networks.

Spectral implementation follows the released loss's log-power interpretation:
400-sample periodic Hann windows multiplied by 2, hop 200, five blocks per
segment; `torch.fft.rfft`, squared magnitude, clamped log, per-sample/block
frequency minmax. Mean squared distances are averaged across batch and
frequency; block aggregation is mean. Self-consistency compares distinct
generated blocks (i<j). It is NOT the logarithm of an MSE waveform loss.

Corrections/adaptations rather than literal source replication:

- Reference `torch.rfft` is obsolete; replaced by `torch.fft.rfft`.
- Reference frequency normalization reshapes memory using `view(-1,batch)`,
  mixing observations; normalization here preserves batch independence.
- Clamp power before log and guard ranges instead of permitting log(0)/NaN.
- Revision 2 keeps D in train mode during the G-only update while freezing
  parameter gradients, consistent with the reference. Revision 1 instead
  used eval-mode D for this step, creating a train/eval objective mismatch;
  that run is retained as a diagnostic, not the primary comparison.
- Adam 5e-4, betas (.5,.999) from released script; batch 64, 1,500 G/D update
  pairs and fixed weights 1/1 for this bounded pilot. No original large grid
  search, AF-specific weights, learning-rate schedule or AF classifier.
- Checkpoint selection uses validation ACF-MMD² + log-PSD-MMD², not the exact
  original hyperparameter search. No test-based checkpoint selection.

Thus `lsm_paper` means a **paper-objective variant on the reference topology**,
not exact paper replication. The original clinical dataset and private AF
annotations are not available here. No AF efficacy claim is made.

## Data and comparison limits

[BIDMC 1.0.0](https://physionet.org/content/bidmc/1.0.0/), Pimentel et al.,
DOI:10.1109/TBME.2016.2613126, ODC Attribution 1.0. Reuse frozen v1 patient
groups: 32/7/7 train/validation/test, including repeated recordings grouped
under the same person. 125 Hz source → `resample_poly(8,25)` → 161-tap
zero-phase FIR 0.9–5 Hz → non-overlapping 30 s → minmax per segment.
The FIR tap count/phase choice is an explicit project choice, not an exact
filter specification given by the paper. 624/112/112 windows result. No
filtering of AF/NSR or manual artifact labels is claimed.

Metrics: biased RBF MMD² of normalized ACF (lags 1..200 at 40 Hz), MMD² of
normalized log-Welch power, mean log-spectrum RMSE, dominant frequency in
0.5–3 Hz expressed as BPM, power >5 Hz, roughness and pointwise diversity.
Kernel bandwidths are median squared distances on **training** features only.
Dominant frequency can be a harmonic and is not an ECG-validated heart rate.
Discriminator real/fake scores are diagnostics, not clinical quality labels.

The same test patients were inspected in the earlier pilot. This is an
exploratory engineering comparison, not a new independent confirmation.
Single seed, limited data, no confidence intervals, and unequal contributions
per patient limit conclusions. No-spectral ablation is the strongest matched
comparison; all checkpoints are selected without reading test metrics.

Existing cWGAN is additionally evaluated by drawing conditions from TRAIN,
rendering repeated pulses at constant HR for 30 s, applying the FIR view and
normalizing. Real train pulses use the same adapter. Real train 30 s windows
are a separate replay baseline. These adapters impose periodicity and a
band limit, unlike raw LSM outputs; they cannot establish which GAN is better
at generating full rhythm variability or notch control. Their previous
training budget and checkpoint criterion also differ. Filtered 40 Hz strips
must not inherit the prior 256-point notch scores without fresh validation.

## Run

```bash
# CPU smoke test; choose a new directory each time
.venv-ml/bin/python -m pytest tests/test_ml_ppg.py tests/test_lsm_gan.py -q
.venv-ml/bin/python ml/kaggle_lsm/train_lsm.py --steps 2 --batch 4 --output ml/runs/lsm-smoke-new

# Private Kaggle run; consumes GPU quota, bounded to 30 minutes
uv tool run --from kaggle kaggle kernels push -p ml/kaggle_lsm --timeout 1800 --accelerator NvidiaTeslaT4
uv tool run --from kaggle kaggle kernels status charlesday2612/ppg-lsm-gan-bidmc-comparison
uv tool run --from kaggle kaggle kernels logs charlesday2612/ppg-lsm-gan-bidmc-comparison
uv tool run --from kaggle kaggle kernels output charlesday2612/ppg-lsm-gan-bidmc-comparison -p ml/runs/lsm-kaggle-v2
.venv-ml/bin/python -m ml.audit_lsm_run ml/runs/lsm-kaggle-v2/lsm_comparison
```

Only the standalone new script is uploaded. Prior pilot artifacts are mounted
through `kernel_sources`. The mounted prior training-code hash is checked;
its generator hash is recorded. The MAT source checksum is verified again.
Private user config/hardware/credentials are not uploaded.

Each arm saves `best.pt` (G **and D**), `last_training_state.pt` (G/D,
optimizers and RNG states), `generator_cpu.ts`, `discriminator_cpu.ts`, logs,
metrics and samples. RNG states are saved for future resume support; the CLI
does not implement `--resume` yet. Comparison outputs include `configuration.json`,
`manifest.json`, `windows.npz`, `comparison.json` and `comparison.png`.
The local audit also creates a 30 s `example_ir_red_40hz.csv` per arm, using
one shared learned shape, 1.5 V pedestals, AC_IR=45 mV and AC_RED=21.6 mV.
These are offline examples under nominal calibration, not learned paired
optical channels, commanded HR traces, or signals sent to the DAC.
No automatic update of the production engine or DAC output occurs.
