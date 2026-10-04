# Neural PPG assets

The current page 04 keeps the three-Gaussian option and provides the LSM-GAN
v2 generator for experimental 30-second sequence generation. LSM inference
uses `lsm_generator.ts`; its 1,200-sample output is native 40 Hz. The app maps
that normalized shape onto nominal IR/RED levels. It does not learn separate
optical channels or calibrated SpO₂.

The cWGAN-GP and TCN-FiLM artifacts are retained for offline research and
historical comparisons; they are not selectable on the current page. cWGAN
generates one condition-controlled, 256-point phase pulse. Its pilot export
does not contain the trained critic. The original Gaussian engine remains
available without PyTorch.

Install `requirements/neural.txt` only when running neural inference. Do not
copy an x86 virtual environment onto a Raspberry Pi; recreate it for the Pi's
Python and ARM64 platform. `manifest.json` records model hashes and preprocessing
metadata for the packaged LSM asset. Other model files may be ignored by Git;
check the manifest, `.gitignore` and [round 2 report](../../docs/ppg_round2_report_2026-09-28.md)
before expecting research artifacts to be present in a checkout.

Training data is BIDMC 1.0.0, not paired raw IR/RED or a broad healthy cohort.
Validation is exploratory because the test set was previously viewed; cWGAN
single pulses and LSM long sequences are not directly equivalent. The current
page's DAC playback is an explicit user action; opening the page or generating
a preview alone does not emit output. See the [LSM report](../../docs/ppg_lsm_gan_report_2026-09-26.md)
and [sequence and hardware validation](../../docs/ppg_touch_sequence_output_2026-09-30.md).
