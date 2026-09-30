# Conditional PPG architecture sweep

This experiment compares generator/critic **architectures**, not clinical
validity. It reuses the frozen BIDMC patient split and 256-point pulse data from
the cWGAN pilot. The application, DAC clock and Gaussian fallback are untouched.

Kaggle version 1 completed 15/15 runs. `tcn_film_projection` won by median
validation selection score (0.08771); its three-seed mean test selection score
was 0.09563, SP phase MAE 0.02521, notch sensitivity 99.80%, specificity 100%,
and log-spectrum RMSE 0.36792. See the
[full Vietnamese report](../../docs/ppg_architecture_sweep_report_2026-09-26.md).
This is the promoted **research candidate**, not a production/DAC deployment.

## Candidate set

| Arm | Generator | Conditional critic |
|---|---|---|
| `upsample_projection` | Original dense + interpolating Conv1D topology | Projection + auxiliary condition head |
| `resnet_film_projection` | Three residual upsampling blocks; FiLM at each block | Projection + auxiliary condition head |
| `tcn_film_projection` | Six full-resolution dilated residual blocks | Projection + auxiliary condition head |
| `multiscale_film_projection` | Four residual blocks with kernels 3/9/21/41 | Projection + auxiliary condition head |
| `resnet_film_concat` | Same ResNet-FiLM generator | Concatenated feature/condition score + same auxiliary head |

The projection/concatenation pair isolates the discriminator conditioning method.
The other four arms use the same critic and isolate generator topology. FiLM is
an affine conditioning mechanism, not a claim that the visual-reasoning result
from [Perez et al.](https://arxiv.org/abs/1709.07871) transfers automatically to
PPG. Residual/dilated TCNs are included as a convolutional sequence baseline
motivated by [Bai et al.](https://arxiv.org/abs/1803.01271). A time/frequency loss
is included because PPG/rPPG work such as
[PulseGAN](https://arxiv.org/abs/2006.02699) treats both domains, but PulseGAN is
a paired denoising model and is not the same task as unconditional noise-to-pulse
generation. The projection critic follows the conditioning principle from
[Miyato and Koyama](https://openreview.net/forum?id=ByS1VpgRZ); continuous
morphology conditions are a project adaptation.

## Fair comparison contract

- Frozen source hash: `25c830dc1613a0dbf9c3775fc87b95b966492fc0962a828c84543422fa278dcf`.
- Same 32/7/7 patient groups and no subject overlap.
- Balanced real batches: half resolvable-notch, half no-resolvable-notch.
- Same WGAN-GP loss, optimizers, update budget and explicit morphology,
  spectrum, derivative, boundary and auxiliary-condition losses.
- Real waveform paired with an opposite-class condition is an additional critic
  negative, so the critic cannot succeed solely by detecting realistic shape.
- Seeds 41/42/43; 3,000 generator steps and three critic steps per generator step.
- Each run selects its own checkpoint by a stratified validation score. The
  architecture winner is the smallest median validation score across seeds.
  Test is excluded from checkpoint and architecture selection.

The primary morphology score combines SP error, balanced notch error, and
penalized DN/DP phase/level errors. A missing requested notch receives a penalty
instead of silently disappearing from the DN/DP denominator. Log-spectrum RMSE
is reported separately and contributes only 10% to checkpoint selection.

## Run

```bash
.venv-ml/bin/python -m pytest tests/test_ppg_architecture_sweep.py -q
.venv-ml/bin/python ml/kaggle_arch/train_architectures.py \
  --output ml/runs/architecture-smoke-new --steps 2 --batch 4 \
  --ncritic 1 --evaluate-every 1 --seeds 41

uv tool run --from kaggle kaggle kernels push -p ml/kaggle_arch \
  --timeout 7200 --accelerator NvidiaTeslaT4
uv tool run --from kaggle kaggle kernels status \
  charlesday2612/ppg-conditional-architecture-sweep
uv tool run --from kaggle kaggle kernels output \
  charlesday2612/ppg-conditional-architecture-sweep \
  -p ml/runs/architecture-kaggle-v1
```

Each seed saves G and critic checkpoints, TorchScript exports, fixed test
samples, validation history, and metrics. `summary.json` identifies the winner
using validation only. “Winner” always means best among these five configurations
under this bounded protocol; it does not establish a universally optimal PPG
architecture. No export is installed into the Raspberry Pi automatically.
