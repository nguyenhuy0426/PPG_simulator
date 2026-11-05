# PPG-physiGPT results (Kaggle, stage 0)

Results of the unconditional patch transformer in `ml/kaggle_physigpt/` (design and kernels: its README).
`build_results.py` writes `results.json` from the kernel records in `evidence/`; every number below comes from there.
These are engineering evaluations of normalised 30 s, 40 Hz PPG shape (0.5-8 Hz view, min-max), not clinical
validation, and nothing here was measured on the Pi/DAC/OPT101.

Why APFT-GAN v1 did not improve on V1 large, the v3 fixes (not trained yet) and the next runs: [APFT_GAN_V3.md](APFT_GAN_V3.md).

## Setup

- Data: MIMIC-III Waveform Database v1.0, shards 0-4 and solo 0 (stage 0), 2% of records held out for the flow loss.
- base: 30.7M parameters (dim 512, 8 layers); large: 99.9M (dim 768, 12 layers). Both trained on Kaggle 2 x T4,
  DDP fp16, batch 1024, warmup-stable-decay; large used `--micro 256` (gradient accumulation) and peak LR 4e-4.
- A stage with `--plateau` ends at `best.pt` when the held-out flow loss stops improving; the skipped decay then
  runs as its own kernel from `stable.pt` (`--decay-steps 3000`, 1-sqrt to zero).
- Two evaluation tiers, both on people never used for training:
  - **strict judge** (C2ST): a 3.6M three-branch classifier (time, spectrum, autocorrelation) trained per seed
    for 3000 steps on 4,972 people and tested on 180 held-out people, 2,000 windows per side. The AUC is saturated
    at 1.0 for every variant, so the separation d' = (mean fake score - mean real score) / pooled SD of the raw
    judge scores is reported as the progress measure (real vs other real people: d' 0.14).
  - **feature tier**: per-feature similarity 1 - KS between generated windows and the held-out people, plus a
    feature-only classifier. The 14-feature tier below (older variants) and the 22-feature tier of the benchmark
    (14 plus 8 beat-shape features) use the same scorer.
- **Pass criterion (current, absolute)**: mean 1 - KS over the 22 features >= 0.95, every feature >= 0.90 (or its
  real-vs-real value if that is lower), and tree-classifier accuracy <= 0.60. The strict judge is **not** a pass
  criterion any more; it stays as a known limit (real vs other real people: AUC about 0.5, d' 0.14).
- The earlier **V1 relative criterion** (mean similarity >= 95% of the real-vs-real value, 14 features) is kept only for
  the older variants in the table below. It is easy to misread as "reached 95%": 98.1% of 0.960 is 0.941, below 0.95.

## Results

| Variant | Steps | Held-out flow | Strict AUC | d' (per seed) | Feature 1-KS (of real) | Tree acc. |
|---|---|---|---|---|---|---|
| base, plateau stop (no decay) | 14,500 | 0.0645 | 1.00 | 17.9 (20.8, 20.1, 12.8) | | |
| base, decay 3k | 17,500 | 0.0591 | 1.00 | 12.2 (10.8, 12.1, 13.7) | | |
| base, decay 3k, unclamped sampling | 17,500 | 0.0591 | 1.00 | 11.2 (12.0, 10.4) | | |
| base, decay 3k, 128 ODE steps | 17,500 | 0.0591 | 1.00 | 15.1 (one seed) | | |
| base, hold 7k + decay 3k (longer) | 24,500 | 0.0581 | 1.00 | 9.0 (10.4, 7.7) | | |
| base, longer + sharpness loss 0.25 | 27,500 | 0.0578 | 1.00 | **7.5** (8.0, 7.0) | | |
| base, longer + sharpness loss 8 | 27,500 | 0.0578 | | | 0.933 (97.3%) | 0.639 |
| **large, plateau stop + decay 3k (V1)** | 25,000 | **0.0575** | 1.00 | 8.6 (8.0, 9.3) | **0.941 (98.1%)** | **0.618** |
| real vs other real people | | | 0.54 (one seed) | 0.14 | 0.960 | 0.50 |

The `Feature 1-KS (of real)` column of this table is the 14-feature value and the old relative score.

Judge controls on real windows (seed 0): phase-randomised AUC 1.0, d' 7.7; 1% noise AUC 1.0, d' 16.5; circular
filter AUC 1.0, d' 15.0. The best variants sit at the separation of a phase-randomised copy of real PPG.

The large run trained 22,000 steps in 7.7 h (938 windows/s, 6.9 GB per T4), stopped at its best checkpoint when
the held-out loss rose, and decayed for 3,000 steps in 0.85 h.

Feature tier, large vs base (1 - KS; real-vs-real reference in brackets): beat regularity `acf_peak` 0.918 vs 0.881
[0.947], rate 0.950 vs 0.931 [0.967], kurtosis 0.950 vs 0.920 [0.940], spectral centroid 0.916 vs 0.897 [0.952];
band power 5-8 Hz 0.885 vs 0.895 [0.974] and second-difference SD 0.905 vs 0.895 [0.963] stay the largest gaps.

## Four models on the same people (current criterion)

`results.json` -> `benchmark`, from `evidence/ppg-physigpt-judge-benchmark-generated-v1-fid/`. Same 180 held-out
MIMIC people (2,000 windows), 22 features, same scorer for all. Intervals: 2,000 bootstrap rounds over people,
bias-corrected. RSH-GAN (earlier name PhysioMix) and RSR-Flow (earlier name PhysioFlow) are the app models and were
given the `perform_large` condition for the prompts, so this set is unfavourable to them; it does not show they are
worse on their own data.

| Model | Mean 1-KS, 22 features (95% CI) | Tree acc. | Features below floor | Lowest feature | Verdict |
|---|---|---|---|---|---|
| V1 large | 0.9379 (0.9122-0.9574) | 0.638 | 2 | power 5-8 Hz 0.885 | fail |
| APFT-GAN | 0.9363 (0.9112-0.9549) | 0.658 | 3 | template_corr 0.851 | fail |
| RSR-Flow | 0.9040 (0.8828-0.9236) | 0.780 | 8 | power 8-20 Hz 0.805 | fail |
| RSH-GAN | 0.8882 (0.8640-0.9087) | 0.975 | 11 | amp_cv 0.739 | fail |
| real vs other real people | 0.9583 (0.9403-0.9728) | 0.50 | | | |

Paired differences of the 22-feature mean (95% CI): V1 large - APFT-GAN +0.0016 (-0.0112 to +0.0146), not separable;
V1 large - RSR-Flow +0.0339 (+0.0081 to +0.0596); V1 large - RSH-GAN +0.0497 (+0.0141 to +0.0860);
APFT-GAN - RSR-Flow +0.0322 (+0.0067 to +0.0583); APFT-GAN - RSH-GAN +0.0480 (+0.0141 to +0.0821);
RSH-GAN - RSR-Flow -0.0158 (-0.0430 to +0.0073), not separable. All four models fail. V1 large and APFT-GAN cannot be
told apart and both beat the two app models on this set.

## RSR-FlowGAN (`evidence/ppg-rsr-flowgan-v1/`)

Adversarial fine-tuning of RSR-Flow, two seeds, about 6.7 h each (5,490 and 5,575 of 6,000 steps; best at 5,000 and
5,575). Evaluated on the multi-domain held-out people (6 domains, 14 features, small samples), **not** on the 180 MIMIC
people, so these numbers are not comparable with the table above (real vs real is only 0.855 there):

| Model | Mean 1-KS, 14 features | Tree acc. | Strict judge AUC |
|---|---|---|---|
| RSR-Flow (app) | 0.8285 | 0.626 | 1.000 |
| RSR-FlowGAN seed 42 | 0.8252 | 0.625 | 0.99999 |
| RSR-FlowGAN seed 123 | 0.8273 | 0.613 | 0.99995 |
| real vs other real people | 0.8549 | | 0.459 |

The GAN stage did not improve on RSR-Flow: the means are within 0.004 of it, the strict judge still separates it
(AUC about 1.0), and it fails the absolute criterion. Its record still shows "passes relative" (about 0.97 of the
real-vs-real value) because that test is the old criterion.

## Reading

- The larger model lowered the held-out flow loss only slightly (0.0575 vs 0.0578) and did not separate from the
  best base variant on the strict judge (d' 8.6 vs 7.5; the seed spread is about 1-3). Every variant stays at AUC 1.0.
- **The current absolute criterion is not met by any of the four models** (table above). Under the old relative
  criterion the large model scored 98.1% of the real-vs-real similarity (14 features; the best base variant 97.3%), which
  is 0.941 in absolute terms, not 0.95. Large improves beat regularity, rate and pulse shape.
- On 22 features V1 large is 0.9379 and tree accuracy 0.638; the strict judge still separates every variant (AUC 1.0).
  The remaining gap is high-frequency detail (5-8 Hz power, second differences), which neither the larger model nor
  the sharpness loss closed.
- The decay step, not the stable phase, gave most of each gain; in the large stable phase the held-out loss fell
  by about 2% per 6,500 steps before the plateau stop.
- The held-out flow loss is computed on records that also chose `best.pt`, so it is a fit measure; realism claims
  rest on the two tiers above, which use separate people.
