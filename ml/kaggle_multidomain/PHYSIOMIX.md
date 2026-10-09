# PhysioMix improvement round

Work stays on `codex/ppg-multidomain-model-benchmark`. No simulator configuration,
DAC asset, main branch or Git remote is modified by this experiment.

## Question

The previous hybrid reduced MMD but generated narrow morphology distributions.
Test a custom generator combining a periodic PPG prior, multiscale residual TCN,
domain/proxy conditioning, projection critics, lazy R1 and generator EMA.
Compare the extra joint descriptor MMD/covariance and fixed-condition latent
diversity objective against the same custom model without those two losses.
This is an adaptation, not a faithful reproduction of a named published model.

The diffusion candidate reuses the small U-Net with conditioning and clean-sample
prediction, capped SNR weighting, classifier-free condition dropout and EMA.
Compare adding a joint descriptor objective; choose guidance 1/1.5 and 32/64
DDIM steps from development validation. Generated signals use a fixed 0.9–5 Hz
FFT view, consistent with the filtered benchmark target. Band limitation is part
of the custom generator, not evidence of raw-motion or optical-signal fidelity.

## Data and labels

Reuse the checksum-verified frozen multidomain v2 pack without changing its splits.
Add [Wrist PPG During Exercise 1.0.0](https://physionet.org/content/wrist/1.0.0/),
19 records from eight participants, four activities, nominal 256 Hz. Split by
participant with seed 20261010: four train, two validation, two test. Retrieve
the officially advertised S3 mirror and verify every header/data/annotation
against the source SHA256SUMS. Exclude NaN padding or gaps as contiguous finite
spans; never fill missing physiological samples. Auxiliary timestamps wrap each
minute and jitter: the common waveform view uses nominal WFDB indexing and does
not establish absolute clock calibration.

[CapnoBase](https://doi.org/10.5683/SP2/NLB8IT), pinned version 1.1, contains 42
eight-minute cases with PPG, ECG, capnography and expert beat/breath/artifact
annotations. The author recommends against training/tuning on this benchmark.
Keep **all cases external-only**, verifying pinned MAT checksums. MATLAB v7.3
data require h5py. Source case is the grouping unit, not a verified independent
patient identity. Preserve source terms in `capnobase_sources.json`.

The prepared pack has five train domains and four external domains. Its optional
labels are AF/non-AF cohort membership (unknown elsewhere), four Wrist activities
(unknown elsewhere), and ECG R-peak median-IBI rate for Wrist/CapnoBase only.
These are not nine disease classes or synchronized clinical diagnoses.
Training uses normalized 30-second PPG only; it does not learn ECG, CO2, absolute
AC/DC, SpO2 or paired IR/RED. Conditioning uses **PPG-derived** peak rate, IBI CV
and signal standard deviation, with scales and all sampling prompts fitted/drawn
from training only. Reference ECG rate is ancillary context, not conditioning
ground truth or a signal-quality certificate.

## Locked procedure

1. Four custom pilot variants, seed 42, 2000 steps, batch 32.
2. A common validation criterion: macro (ACF + log-PSD + morphology MMD²)
   + 0.25 abs(log generated/train morphology diversity)
   + 0.5 (1 − macro feature recall) + 0.25 (1 − macro feature precision).
   Scales/bandwidths fit on training only.
   Training/pilot evaluators contain no test/external waveform references.
3. Select one GAN variant and one diffusion variant/sampler from validation.
   Save `PILOT_SELECTION.json` and `FROZEN_PROTOCOL.json` before final training.
4. Retrain the five earlier arms plus the two selected custom variants: three
   seeds 42/123/2026, 6000 steps each, batch 32, validation every 500 updates.
   All arms select checkpoints with the same new criterion. This is 21 final
   runs plus four pilot runs; equal updates/batches, not equal compute/FLOPs.
5. Freeze architecture/checkpoint choices, then open held-out metrics once.
   Fresh Wrist test and whole CapnoBase are primary holdouts. Previously viewed
   BIDMC/PERform/PTT tests are explicitly exploratory; do not tune on them.

Require exactly **two T4 GPUs**. Two spawned workers use cuda:0 and cuda:1 for
independent arm/seed jobs. Record worker PID, peak CUDA allocation, per-job and
phase wall time. GPU allocation alone is not proof that both trained.

GAN logs record finite losses, gradient norms/clipping, real−fake critic margin,
lazy R1 count, validation recall and diversity over time. These are measured
stability diagnostics, not a proof of universal GAN convergence. The final
benchmark reports precision/recall, two-sample 1-NN, patient/group bootstrap,
nearest-training screening, CPU latency and controlled-rate proxy probes.
Three seeds and small Wrist/non-AF cohorts limit statistical conclusions.

## Reproduce

```bash
rtk proxy .venv/bin/python -m pytest -q tests/test_physiomix_ppg.py tests/test_multidomain_ppg.py
rtk proxy .venv/bin/python -m ml.kaggle_multidomain.stage_kernel --mode physio_prepare --output ml/runs/physiomix-data-kernel-new
rtk proxy uv tool run --from kaggle kaggle kernels push -p ml/runs/physiomix-data-kernel-new --timeout 7200
```

Verify preparation counts, checksum, source manifest and split isolation before:

```bash
rtk proxy .venv/bin/python -m ml.kaggle_multidomain.stage_kernel --mode physio_train --steps 6000 --output ml/runs/physiomix-train-kernel-new
rtk proxy uv tool run --from kaggle kaggle kernels push -p ml/runs/physiomix-train-kernel-new --accelerator NvidiaTeslaT4 --timeout 10800
```

No result is automatically promoted into the simulator. The custom GAN export
takes `(noise, condition)` and its accompanying condition schema; it is not a
drop-in replacement for the existing single-input DAC/runtime asset. Pi timing,
operator/runtime compatibility and optical/DAC calibration remain unverified.
