# PPG-physiGPT results (Kaggle, stage 0)

Results of the unconditional patch transformer in `ml/kaggle_physigpt/` (design and kernels: its README).
`build_results.py` writes `results.json` from the kernel records in `evidence/`; every number below comes from there.
These are engineering evaluations of normalised 30 s, 40 Hz PPG shape (0.5-8 Hz view, min-max), not clinical
validation, and nothing here was measured on the Pi/DAC/OPT101.

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
  - **feature tier**: per-feature similarity 1 - KS between 2,000 generated windows and the held-out people for
    14 waveform features, plus a feature-only classifier. Pass: mean similarity >= 0.95 and tree-classifier
    accuracy <= 0.60. Real windows of other people score 0.960 and 0.50 on the same test.

## Results

| Variant | Steps | Held-out flow | Strict AUC | d' (per seed) | Feature 1-KS | Tree acc. |
|---|---|---|---|---|---|---|
| base, plateau stop (no decay) | 14,500 | 0.0645 | 1.00 | 17.9 (20.8, 20.1, 12.8) | | |
| base, decay 3k | 17,500 | 0.0591 | 1.00 | 12.2 (10.8, 12.1, 13.7) | | |
| base, decay 3k, unclamped sampling | 17,500 | 0.0591 | 1.00 | 11.2 (12.0, 10.4) | | |
| base, decay 3k, 128 ODE steps | 17,500 | 0.0591 | 1.00 | 15.1 (one seed) | | |
| base, hold 7k + decay 3k (longer) | 24,500 | 0.0581 | 1.00 | 9.0 (10.4, 7.7) | | |
| base, longer + sharpness loss 0.25 | 27,500 | 0.0578 | 1.00 | **7.5** (8.0, 7.0) | | |
| base, longer + sharpness loss 8 | 27,500 | 0.0578 | | | 0.933 | 0.639 |
| **large, plateau stop + decay 3k** | 25,000 | **0.0575** | 1.00 | 8.6 (8.0, 9.3) | **0.941** | **0.618** |
| real vs other real people | | | 0.54 (one seed) | 0.14 | 0.960 | 0.50 |

Judge controls on real windows (seed 0): phase-randomised AUC 1.0, d' 7.7; 1% noise AUC 1.0, d' 16.5; circular
filter AUC 1.0, d' 15.0. The best variants sit at the separation of a phase-randomised copy of real PPG.

The large run trained 22,000 steps in 7.7 h (938 windows/s, 6.9 GB per T4), stopped at its best checkpoint when
the held-out loss rose, and decayed for 3,000 steps in 0.85 h.

Feature tier, large vs base (1 - KS; real-vs-real reference in brackets): beat regularity `acf_peak` 0.918 vs 0.881
[0.947], rate 0.950 vs 0.931 [0.967], kurtosis 0.950 vs 0.920 [0.940], spectral centroid 0.916 vs 0.897 [0.952];
band power 5-8 Hz 0.885 vs 0.895 [0.974] and second-difference SD 0.905 vs 0.895 [0.963] stay the largest gaps.

## Reading

- The larger model lowered the held-out flow loss only slightly (0.0575 vs 0.0578) and did not separate from the
  best base variant on the strict judge (d' 8.6 vs 7.5; the seed spread is about 1-3). Every variant stays at AUC 1.0.
- On the feature tier, large is the closest so far (0.941, 98% of the real-vs-real 0.960) and improves beat
  regularity, rate and pulse shape, but it fails both criteria. The remaining gap is high-frequency detail
  (5-8 Hz power, second differences), which neither the larger model nor the sharpness loss closed.
- The decay step, not the stable phase, gave most of each gain; in the large stable phase the held-out loss fell
  by about 2% per 6,500 steps before the plateau stop.
- The held-out flow loss is computed on records that also chose `best.pt`, so it is a fit measure; realism claims
  rest on the two tiers above, which use separate people.
