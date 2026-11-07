# APFT-GAN v3 HR v1 — experimental Pi bundle

Source: the user's Kaggle kernel `charlesday2612/ppg-physigpt-apft-gan-v3-hr-v1`, script365845262, checkpoint1250. The source network matches the kernel's source manifest (SHA256 in manifest.json). The deployment checkpoint contains generator weights and configuration only and loads with `weights_only=True`.

100,520,568 parameters, float32 CPU. Native output: 1,200 normalized samples, 30 seconds at40Hz. Autoregressive30×40-sample patches with16-step Heun flow head. Requested HR40–180bpm is a condition and does not guarantee the measured rate. The discriminator is used during training only.

Held-out feature mean1−KS95.28%, tree real/fake accuracy61.275%, strict judge AUC1.0. Automated verdict remains fail. This is not clinical validation.

Pi4 ARM64,4GB, PyTorch2.5.1: real UI subprocess test generated1,200 samples in about91s including loading in the staged test. Precompute before playback. `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1` bound worker threads; torch uses one intra-op thread. Pi UI permits up to300s for APFT. Installed measurements and backup paths are recorded separately in `pi-deployment.json` / the deployment report.

IR/RED derive from the same normalized waveform and nominal AC/DC. No calibrated optical or SpO₂ model. Real reference is an unpaired MIMIC-III TRAIN segment for visual comparison only. No LED/DAC test has been performed with this bundle.
