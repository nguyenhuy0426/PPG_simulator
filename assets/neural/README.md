# Optional research preview bundle

Four UI modes: original Gaussian (stdlib, no checkpoint), cWGAN pilot,
LSM corrected v2, TCN-FiLM/projection critic (seed 42, step 2800).
The five TorchScript files are ignored by Git. `manifest.json` verifies their
SHA-256 hashes at load time. Install `requirements/neural.txt` only for neural
inference, then copy/extract the round2 model bundle at the repository root.
Do not copy an x86 virtual environment onto a Raspberry Pi.

The Classic three-Gaussian engine is retained. Neural generation and export
never drive DAC/LED. IR and RED share a shape with nominal AC/DC conversion;
they are not independently learned optical channels.

See [the round 2 report](../../docs/ppg_round2_report_2026-09-28.md) for results,
instructions and the outstanding human review / external validation.


30 September 2026: page 4 uses only `lsm_generator.ts` for sequence inference.
This 511 kB frozen v2 artifact is tracked for reproducible Pi deployment; other
large research exports can be prepared with the existing script. Its checksum
is in manifest.json. Hardware output is now explicitly user-authorized, while
model quality remains exploratory. `real_train_strip.json` is one preprocessed
BIDMC training window at 40 Hz with provenance, not paired raw IR/RED data.
BIDMC 1.0.0: https://physionet.org/content/bidmc/1.0.0/ (Pimentel et al., ODC-By 1.0).
