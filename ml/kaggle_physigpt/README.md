# PPG-physiGPT

A decoder-only patch transformer for normalised 30 s, 40 Hz PPG, designed after GPT-PPG
(Chen et al. 2025, arXiv 2503.08015) and sized for a Kaggle T4 x2 kernel. Engineering model of signal shape;
not clinical.

## Data: what GPT-PPG had and what is used here

GPT-PPG pretrained on more than 200 million 30 s strips (40 Hz, min-max) from UCSF ICU monitoring
(2013-2018, >24,100 patients), held under a UCSF-Emory data use agreement. That data is not public, and no
200-million-strip hospital set is available to this project.

The open substitute is the MIMIC-III Waveform Database v1.0 (PhysioNet, ODbL 1.0, open access, 125 Hz,
6.7 TB, 67,830 record sets of ~30,000 ICU patients, PLETH in many records; `RECORDS-adults` lists 59,344
adult records). `mimic_wdb.py` builds shards from it:

- only the bytes of chosen windows are fetched (HTTP Range on the multiplexed `.dat`, formats 80 and 16);
- per record at most `--cap` windows (default 300), in 5 min blocks chosen from the record name;
- records in a fixed hashed order, a shard = a record range, so shards never share a record;
- 2% of records (name hash) held out for validation;
- the project's v3 view (0.5-8 Hz Butterworth over the block, per-window min-max), stored as uint16;
- the records behind the project's MIMIC PERFORM sets are excluded (the strict judge's people). BIDMC
  (MIMIC-II) cannot be mapped to these records; that overlap risk stays and the judge round's copy gate
  covers it.

Format 80 PLETH rails at byte 0 on troughs, so there only a run of byte 0 of 1 s or more counts as a dropout;
shorter runs fall under the 5% clipping rule of the project's packs.

Checked on real records (from this machine, 2 records, cap 20): 17 and 20 windows extracted; the full shard CLI
(PERFORM exclusions, 715 record names, then 4 records, cap 6) wrote 18 windows. The windows per
hour on Kaggle and the PLETH yield of the whole database are not measured yet; the first shard kernel logs both
(`manifest.json`: `windows_per_hour`, `counts`).

## Model (`model.py`)

| | GPT-PPG | PPG-physiGPT |
|---|---|---|
| tokens | 30 patches x 40 samples, linear embedding | same |
| first input | one learnable start vector | one start vector per domain (MIMIC-III ICU first) |
| block | pre-norm RMSNorm, RoPE, causal attention | same, SwiGLU feed-forward |
| output | logit-Laplace (mu, b per sample) | flow-matching patch head + logit-Laplace as auxiliary |
| sizes | 19M / 85M / 345M / 1B | base 30.7M (backbone 25.3M), large 99.9M (backbone 85.0M) |

The logit-Laplace head samples the 40 samples of a patch independently given the context, which puts white
noise inside every patch; the flow head (an adaptive-LN residual MLP, as the diffusion head of Li et al. 2024)
models the patch jointly and is sampled with a Heun ODE per patch, autoregressively over 30 patches.

## Training (`train.py`) and continual stages

- DDP over both T4s, fp16 autocast with a gradient scaler, AdamW (0.9, 0.95), weight decay 0.1, clip 1.0,
  global batch 1024 windows, peak LR 6e-4.
- Warmup-stable-decay (Hägele et al. 2024): stage 0 warms up; every stage holds the peak and ends with a
  1-sqrt decay over its last 15%. `stable.pt` (before the decay) starts the next stage at the peak with no new
  warmup; `release.pt` is the decayed model for evaluation; `last.pt` resumes a stopped stage exactly.
- A stage covers `--epochs` (default 4) over its new shard plus 25% replay of the earlier shards. Batches and
  flow noise are functions of (seed, step), so a resumed stage continues exactly (tested on CPU).
- The 11 h kernel budget shortens a stage from the measured step time, keeping its decay.

"Học tăng cường liên tục" here means continual pretraining on new shards (with replay), not reinforcement
learning.

## Scale (estimates, not measured)

FLOPs per window ~ 6 x params x 30 tokens. With an assumed ~25 TFLOP/s effective over two T4s: base ~5,000
windows/s, so 5 M windows x 4 epochs ~ 1-2 h and 200 M windows x 1 epoch ~ 11 h. Data, not GPU time, is the
limit: a 5 M-window shard is ~12 GB of uint16 (inside the 20 GB kernel output) and needs roughly 60-120 GB of
Range downloads from PhysioNet. Reaching 200 M windows would need most PLETH hours of the database (records
capped higher) and many shard kernels; whether the database holds that many usable windows is not known yet.

## Kernels (`stage.py`)

```
python3 -m ml.kaggle_physigpt.stage <dir> data --shard 0 --start 0 --target 5000000
python3 -m ml.kaggle_physigpt.stage <dir> train --stage 0 --shards 0
python3 -m ml.kaggle_physigpt.stage <dir> train --stage 1 --shards 0 1      # resumes stage 0's stable.pt
```

The next data shard starts at the previous shard's `next_record`; shards built in parallel take fixed disjoint
`--start`/`--stop` ranges instead (train.py refuses mounted shards whose record ranges overlap). Stage 0 trains on
every mounted shard, and on solo outputs given with `--solos`, as new data:

```
python3 -m ml.kaggle_physigpt.stage <dir> data --owner halovie2412 --shard 1 --start 5000 --stop 10000
python3 -m ml.kaggle_physigpt.stage <dir> train --owner halovie2412 --stage 0 --shards 1 2 3 4 --solos 0 \
    --epochs 300 --plateau 4 --eval-every 500
```

With `--plateau`, a stage whose held-out flow loss has risen above its best (overfitting) ends at `best.pt`
instead of decaying; on solo 0 alone (87 k windows) the held-out loss was lowest at step 2000 and rose after. Realism is not claimed from NLL or flow loss:
a later round fine-tunes on the project's people and goes through the strict judge with its copy gate.

The decay a plateau stop skipped runs as its own kernel from `stable.pt`; a tagged train kernel keeps its own
output, and the large config needs gradient accumulation on a T4:

```
python3 -m ml.kaggle_physigpt.stage <dir> train --owner halovie2412 --stage 0 --shards 1 2 3 4 --solos 0 \
    --datasets ppg-physigpt-shard0-data-v1 --config large --tag large --micro 256 --lr 0.0004 \
    --epochs 300 --plateau 6 --plateau-delta 0.001 --eval-every 500
python3 -m ml.kaggle_physigpt.stage <dir> decay --owner halovie2412 --stage 0 --shards 1 2 3 4 --solos 0 \
    --datasets ppg-physigpt-shard0-data-v1 --config large --epochs 300 --from-slug ppg-physigpt-stage0-large-v1 \
    --tag large --decay-steps 3000 --micro 256 --lr 0.0004
python3 -m ml.kaggle_physigpt.stage <dir> judge --owner halovie2412 --stage 0 --shards 1 2 3 4 --solos 0 \
    --datasets ppg-physigpt-shard0-data-v1 --from-slug ppg-physigpt-decay0-large-v1 --judge-seeds 0   # feature tier only
```

Measured results (strict judge, feature tier, held-out flow loss) are in [docs/physigpt](../../docs/physigpt/README.md).
