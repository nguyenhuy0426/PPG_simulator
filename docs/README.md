# Documentation index

What is in `docs/`, grouped by purpose. Dated reports are kept as written at the
time; the newest result in each group is listed first.

## Set up and run

| Document | Contents |
|---|---|
| [setup/RASPBERRY_PI_4_UBUNTU_24_04.md](setup/RASPBERRY_PI_4_UBUNTU_24_04.md) | Raspberry Pi 4 installation on Ubuntu 24.04 |
| [setup/RASPBERRY_PI_4_UBUNTU_26_04_SSH.md](setup/RASPBERRY_PI_4_UBUNTU_26_04_SSH.md) | Laptop-to-Pi Ethernet/SSH, deployment and remote debugging |
| [ble_protocol.md](ble_protocol.md) | BLE GATT contract with the Android app |
| [logging/PPG_TX_RX_LOG_SCHEMA.md](logging/PPG_TX_RX_LOG_SCHEMA.md) | Paired TX/RX session log format |

## Hardware

| Document | Contents |
|---|---|
| [hardware/](hardware/) | Prototype BOM, schematic, wiring/test points, transistor identification |
| [hardware/design-audit/](hardware/design-audit/) | LED-driver design audit: base context, system audit, datasheet evidence, driver architecture, stage-1 recalculation |
| [architecture/](architecture/) | Phase 1 reference audit and master design; Phase 4 dual-DAC TX and LED driver |
| [system_3d/](system_3d/README.md) | Printable optical enclosure: generator scripts, STL files, viewer |
| [opt101-a0-diagnostic-2026-10-01.md](opt101-a0-diagnostic-2026-10-01.md) | OPT101/A0 bench diagnostic protocol |
| [hardware-validation/2026-09-30/](hardware-validation/2026-09-30/) | Raspberry Pi timing, ARM inference and TX/RX capture evidence |
| [ds_linhkien/](ds_linhkien/), [whale_device/](whale_device/) | Component datasheets and the WhaleTeq AECG100 reference manual (see [REFERENCES.md](REFERENCES.md)) |

## Waveform models

| Document | Contents |
|---|---|
| [model-report/](model-report/README.md) | Static web report on all generators (open `index.html`) |
| [physioflow/REPORT_VI.md](physioflow/REPORT_VI.md) | PhysioFlow (rectified flow), round 10; rules in `physioflow/rules/` |
| [physiomix-v3/REPORT_VI.md](physiomix-v3/REPORT_VI.md) | PhysioMix rounds 4–9 (app model: round 9) and per-dataset realism |
| [physiomix-v2/REPORT_VI.md](physiomix-v2/REPORT_VI.md) | PhysioMix v2 benchmark, data and frozen protocol |
| [ppg_touch_sequence_output_2026-09-30.md](ppg_touch_sequence_output_2026-09-30.md) | LSM-GAN sequence output, touch controls, sequence audit |
| [ppg_neural_preview_report_2026-09-28.md](ppg_neural_preview_report_2026-09-28.md), [ppg_round2_report_2026-09-28.md](ppg_round2_report_2026-09-28.md), [ppg_gaussian_fit_2026-09-28.md](ppg_gaussian_fit_2026-09-28.md), [ppg_morphology_selection_2026-09-28.md](ppg_morphology_selection_2026-09-28.md) | Earlier neural preview, round 2, Gaussian fit and morphology selection |
| [ppg_lsm_gan_report_2026-09-26.md](ppg_lsm_gan_report_2026-09-26.md), [ppg_gan_report_2026-09-26.md](ppg_gan_report_2026-09-26.md), [ppg_architecture_sweep_report_2026-09-26.md](ppg_architecture_sweep_report_2026-09-26.md) | First LSM-GAN, cWGAN-GP and architecture sweep |
| [ppg_morphology.md](ppg_morphology.md) | Dicrotic-notch model definition and limits |

Figures and metrics for these reports sit in `gaussian-fit/`, `morphology-audit/`,
`neural-comparison/`, `round2/` and `sequence-audit/`. Older UI code is kept in
`archive/`.

## Application

| Document | Contents |
|---|---|
| [phase_reports/V5_CONTINUATION_REPORT.md](phase_reports/V5_CONTINUATION_REPORT.md) | v5 scope, evidence and remaining physical validation |
| [rx-monitor-2026-10-01.md](rx-monitor-2026-10-01.md) | Live A0/A2 RX card design notes |
| [ui/](ui/) | Screenshots referenced by the README and reports |

## Third-party material

[REFERENCES.md](REFERENCES.md) lists the datasheets and manuals kept in the
repository and the literature that was removed from it.
