# APFT-GAN v3: why the GAN stage did not help, what changed, and the next run

Engineering evaluation of normalised 30 s, 40 Hz PPG shape (0.5-8 Hz view, per-window min-max). Nothing here is
clinical validation or a Pi/DAC/OPT101 measurement. **v3 has not been trained yet**: every v3 number below is a
plan or a CPU smoke result, not a result.

## 1. Where the models stand (from `results.json`, 180 held-out MIMIC people, 22 features)

| Model | Mean 1-KS | Tree acc. | Below floor |
|---|---|---|---|
| V1 large (AR patch transformer + flow head) | 0.9379 | 0.638 | power 5-8 Hz, rise_time |
| APFT-GAN v1 (V1 + adversarial fine-tune) | 0.9363 | 0.658 | 3 (template_corr 0.851) |
| RSR-Flow (app) | 0.9040 | 0.780 | 8 |
| RSH-GAN (app) | 0.8882 | 0.975 | 11 |
| real vs other real people | 0.9583 | 0.50 | |
| target | >= 0.95 | <= 0.60 | none below 0.90 |

## 2. Literature: is there a better GAN to switch to?

What the published PPG/biosignal generators use (sources at the end):

- **PPG GANs** are almost all *translation* or *augmentation* models on small sets: PulseGAN (rPPG -> PPG, U-Net G,
  CNN D, adversarial + time-domain loss), Welch-GAN (Bi-LSTM G, 1-D CNN D), ECG->PPG U-Net GAN with a Markovian
  (PatchGAN) D, PPG->BP UNet3+ with PatchGAN D, P2E-WGAN (PPG->ECG, WGAN-GP). None reports a held-out, people-level
  two-sample test like the strict judge, and none generates unconditional 30 s PPG from noise at this scale.
- **ECG generation benchmarks**: SSSD-ECG (diffusion with S4) beats the GANs WaveGAN* and Pulse2Pulse on PTB-XL in
  its authors' experiments; FlowECG (flow matching) and later diffusion work take SSSD-ECG as the state of the art.
  TTS-CGAN (transformer G and D) is dataset-dependent against SSSD on wearable signals.
- **PPG-specific diffusion/flow**: VAMP-Diff (preprint) reports better heart-rate preservation than Gaussian-prior
  baselines; UniCardio (diffusion transformer on PPG/ECG/BP) reports strong denoising/imputation/translation. Both
  are author claims, not reproduced here. I found no paper that conditions PPG generation on a requested heart rate
  and validates that the generated rate follows it.
- **Audio GAN components** that fit quasi-periodic signals: HiFi-GAN's multi-period discriminator (sub-critics on
  samples spaced by a prime period) and multi-scale discriminator, and Parallel WaveGAN's multi-resolution STFT
  loss. Not yet applied to PPG in the papers found.

Reading: the literature does **not** give a GAN that is known to beat a likelihood-trained flow/diffusion model on
waveform fidelity; the evidence points the other way (diffusion/flow > GAN on ECG). This project's own record agrees:
both GANs (RSH-GAN, and RSR-FlowGAN on top of RSR-Flow) are below V1 large. Starting a new GAN from scratch is
therefore not recommended. The recommended architecture keeps V1 large as the generator and uses the GAN as a
**fine-tuning stage with a strict-view critic**, fixed as below.

## 3. Why APFT-GAN v1 could not improve (from `evidence/ppg-physigpt-apft-gan-v1/metrics.jsonl`)

1. **The adaptive weight balanced one layer only.** The logged gradient norms at the flow head's output layer were
   ~0.012 (flow anchor) and ~170 (adversarial, median), so `lam` sat at ~1e-4 for the whole run. That makes the two
   terms equal at that layer, but the adversarial gradient also runs through the 16-step ODE and the context state
   into the 85 M backbone: the total generator gradient was 5-7 against a clip of 1.0. After clipping, the update was
   set by the adversarial term and the flow anchor was scaled down ~6x. This is engineering inference from the log:
   v1 did not log per-part norms.
2. **The critic's gradient is truncated across patches.** A generated patch's effect on later contexts is not
   differentiated, so the critic cannot teach beat-to-beat structure, yet in v1 its gradient reached the backbone
   that holds that structure. The held-out beat features dropped (template_corr 0.903 -> 0.851, amp_cv) and the
   selection score collapsed mid-run (0.942 at step 1500, 0.715 at step 3000, 0.827 at the end).
3. **The critic was never the bottleneck.** rt_ema stayed 0.6-0.9 with ADA at its 0.8 cap: the critic separated the
   classes all run. A stronger discriminator (e.g. HiFi-GAN MPD/MSD) would not address 1-2.
4. **The largest gaps are within-patch detail.** power 5-8 Hz (0.885 vs real 0.974), second-difference SD
   (0.905 vs 0.963), centroid. 128 ODE steps made the judge separation worse than 32 (d' 15.1 on one seed vs 12.2), so the
   sampler's step count is not the cause; the learnt velocity field is. A rough check on the only saved windows
   (10 real, 10 V1 large; too few to rely on) has the generated windows slightly *above* real in 3-8 Hz power and
   second-difference SD, i.e. a little rough rather than smooth. v3 logs the median shift per feature on 1024
   windows so the direction is measured, not guessed.

So the limit was mainly in the **training code**, not the generator architecture.

## 4. What v3 changes (`ml/kaggle_physigpt/gan.py`, `model.py`)

| | v1 | v3 (defaults) |
|---|---|---|
| adversarial gradient reaches | flow head + backbone | flow head only (`--adv-scope head`), h detached |
| anchor (flow + logit-Laplace) | all parameters | all parameters (unchanged) |
| adaptive weight | norms at `flow.outp.weight` | norms over every flow-head parameter |
| feature term | none | `--feature-weight 0.5`: 1-D Wasserstein (sorted batch values) per feature, in real-SD units, over a differentiable copy of the feature tier's signal features (5 band powers, centroid, log diff SD, log diff2 SD, skew, kurtosis, diff skew, mean, ACF peak) |
| when G moves | only while the critic separates | anchor + feature from `--critic-warmup`; adversarial only while rt_ema >= gate |
| heart-rate condition | none | `--hr-cond`: Fourier embedding of the window's rate, zero-initialised MLP added to every token; learnt from the anchor's rate labels; V1 loads unchanged |
| logged | lam, norms at one layer | per-term head norms, head vs backbone gradient, median shift per feature, hr_mae |

The differentiable features match `judge_physigpt.signal_features` to 1e-3 on test windows
(`tests/test_apft_gan_v3.py`). The feature term uses training records only; the decision is still made on held-out
people (target report, strict judge, copy check). Training on a copy of the metric risks matching the features while
the waveform stays separable; the strict judge and the beat layer, which the term does not see, are the guard.

The rate label is the feature tier's autocorrelation rate (30-200 bpm, integer lags at 40 Hz, so coarse above
~150 bpm). A conditional checkpoint keeps the selection's real rates (`hr_bank`); the judge samples rates from it,
so the judge compares the same rate distribution as before.

## 5. Next runs: two Kaggle sessions (`scripts/kaggle_two_sessions.sh`)

From the repository root on a `claude/model-benchmark-*` branch (`stage.py` refuses other branches), with the Kaggle
CLI logged in as the account that spends its GPU quota (default `charlesday2612`; the shards and the V1 release of
`halovie2412` must be shared with it):

```
scripts/kaggle_two_sessions.sh push      # stages and pushes both kernels (T4 x2 each)
scripts/kaggle_two_sessions.sh status
scripts/kaggle_two_sessions.sh wait      # every 10 min until both end, then pull + report
scripts/kaggle_two_sessions.sh report    # mean similarity %, every feature %, tree accuracy, strict judge
```

| kernel | what | training | after training |
|---|---|---|---|
| `ppg-physigpt-psf-gan-v1` | PSF-GAN, the pure GAN (section 6), `--hr-cond --batch 256` | ~10.7 h budget, lr decay over the last 20 % of the time, `--patience 10` evaluations of 2000 steps | 9,000 windows of the EMA generator, target report on the 180 held-out people, strict judge seed 0 |
| `ppg-physigpt-apft-gan-v3-hr-v1` | APFT-GAN v3 from V1 large, `--hr-cond` | up to 20,000 steps, `--patience 8` evaluations of 250 steps | the same, sampled at 16 Heun steps |

Each kernel writes `eval/summary.json` (`kernel_eval.py`): the 22-feature mean similarity (1 - KS) in percent next
to real vs real, every feature, tree accuracy, strict-judge AUC and the verdict against the target (mean >= 95 %,
floor 90 %, tree accuracy <= 0.60). The copy check (`copy_check.py`) is still a separate kernel; a model is not
accepted before it passes it. Kaggle's concurrent GPU-session limit and how a T4 x2 session is counted against the
weekly quota are not checked here.

What to read from the first log lines: `grad_backbone` vs `grad_head`, `lam`, `lam_feat`, and whether
`median_shift` of power 5-8 Hz and diff2_std moves toward 0 while template_corr holds. If the selection score does
not rise above step 0 within ~2000 steps, the next lever is a larger `--feature-weight` or a lower `--lr`, not a new
architecture.

Colab: `colab_run.py` is a Drive-resumed supervisor for `train.py` stages, not for `gan.py`; a Colab T4 (16 GB, one
GPU) can run `gan.py` single-process with `--batch 32 --anchor 64` (v1 used 7.9 GB per T4 at 64/128), but that path
has not been run.

## 6. PSF-GAN: the pure GAN (`ml/kaggle_physigpt/pure_gan.py`)

Why the earlier pure GANs failed (from the repository's code and reports; P5/PhysioGAN-R was trained but no result was
ever recorded, so this is engineering reading, not a measured diagnosis):

- **data**: PhysioMix/RSH-GAN, LSM-GAN and P5 trained on the multi-domain packs (thousands of windows, a few hundred
  people). A critic memorises that, so P5 needed ADA and a halved critic rate. PSF-GAN trains on the 2.18 M training
  windows of the physiGPT shards, held on the GPUs, with no augmentation;
- **rhythm**: a convolutional up-sampler has to agree on every beat time over 30 s from a 25-sample seed; RSH-GAN's
  worst features on the benchmark were beat regularity (amp_cv 0.739, 11 features below the floor, tree accuracy
  0.975). PSF-GAN is source-filter: a pulse phase from the mean rate (the heart-rate condition) and a smooth learnt
  rate variability (+-30 %), whose first 4 harmonics drive every fine block; the network shapes the pulse, amplitude
  and baseline around it. With `--hr-cond`, the generated rate follows the asked rate by construction
  (`tests/test_psf_gan.py` checks the excitation's frequency);
- **view**: the generator writes a 40 s record; the v3 band-pass (|H|^2 of the 4th-order Butterworth, in the frequency
  domain) and a centre crop give the 30 s window, then min-max, so no network learns the stop band;
- **critics**: HiFi-GAN multi-period (periods 2, 3, 5, 7, 11) and multi-scale (x1, x2, x4) critics plus a log-STFT
  critic, weight-normalised, each with projection on the heart rate; least-squares loss, feature matching of the
  critics' batch-mean features, and APFT-GAN v3's feature-distribution term;
- **training**: fp16 with one scaler per network, fused AdamW (0.8, 0.99), EMA generator (0.999) for selection and
  release, one process per T4 with one flat all-reduce per network, the data resident on each GPU (half the rows
  per rank, ~2.6 GB), selection every 2000 steps on the 22 features of training records, early stop by patience.

Sizes: generator 7.22 M, critics 4.51 M parameters (base, `--hr-cond`). Speed on a T4 is not measured; the kernel
logs `windows_per_second` and `max_memory_gb`. On the cloud session's CPU, one base step at batch 32 took 2.1 s.

Over- and underfitting: the critics see 2.18 M windows, so memorisation is less likely than on the packs, but it is
checked, not assumed: the copy check against all training windows. Underfitting shows as a selection score that
stops rising while the losses still move; the lr decay over the last 20 % of the time and the EMA are the levers
before a larger model.

### Sampling speed (both models)

`PhysiGPT.sample_patches` keeps a key/value cache, so each of the 30 steps runs the transformer on one new token
instead of the whole prefix (same windows for a seed; `tests/test_psf_gan.py`). On the cloud CPU, 64 large windows
at 16 Heun steps took 7.6 s instead of 17.8 s. APFT-GAN's rollout and the evaluation sampling use it.

## 7. Pi 4 deployment (not measured on the Pi)

Generation is autoregressive: 30 transformer passes and, per patch, 2x16-1 = 31 flow-head calls. For one large
window that is roughly 2 x 85 M x (1+...+30 tokens, ~465) ~ 80 GFLOP for the backbone without a KV cache, plus the
head.

Measured on the cloud session's x86 CPU (4 threads, PyTorch 2.15 fp32, random weights, which cost the same as trained
ones): one 30 s window took 0.9 s (base) and 2.1 s (large) at 16 Heun steps before the key/value cache, 0.6 s and 1.7 s with it. This is not a Pi measurement. A Pi 4
(4x Cortex-A72) is several times slower than that CPU per core; by that ratio, large would take on the order of
10-20 s and base a few seconds per 30 s window. That is an extrapolation and has to be timed on the Pi. Even at that
speed, generation keeps up with 30 s of output if it runs ahead of playback (a buffer of windows produced off the DAC
thread, as `sequence_worker.py` does for LSM-GAN). A KV cache in `generate` would remove most of the backbone cost.

## Sources

- PulseGAN: https://arxiv.org/pdf/2006.02699
- Welch-GAN: https://www.researchgate.net/publication/353838558
- ECG->PPG U-Net GAN: https://pubmed.ncbi.nlm.nih.gov/38273980
- PPG->BP cGAN (UNet3+, PatchGAN): https://doi.org/10.1109/jbhi.2023.3324319
- rPPG from palm video with GANs: https://pmc.ncbi.nlm.nih.gov/articles/PMC12846243
- SSSD-ECG: https://arxiv.org/abs/2301.08227
- FlowECG: https://arxiv.org/pdf/2509.10491
- Wearable generative-AI challenges (TTS-CGAN vs SSSD): https://arxiv.org/pdf/2505.14206
- VAMP-Diff: https://arxiv.org/html/2605.22851
- UniCardio: https://arxiv.org/abs/2505.22306
- HiFi-GAN (MPD/MSD): https://arxiv.org/pdf/2010.05646
- GPT-PPG (the backbone's design): arXiv 2503.08015
