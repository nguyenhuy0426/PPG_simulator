# PPG Simulator v5 — continuation and validation report

Date: 2026-09-05

## Result

The Raspberry Pi/Linux application now exposes the full in-scope PPG/SpO2
software control surface through a light clinical-style UI. Navigation is
side-effect free, calibration output is explicit, recording follows model time,
configuration writes are atomic, and the source-controlled 3D web viewer uses
the same principal ranges and waveform choices.

This is a research simulator. It does not claim clinical accuracy, electrical
compliance, or equivalence to a calibrated commercial instrument.

## In-scope commercial-reference coverage

The comparison source is the local AECG100 manual
[`docs/whale_device/user_manual.pdf`](../whale_device/user_manual.pdf),
especially Tables 7, 10, 11 and 13. The score covers PPG and SpO2 software
controls only; ECG, PWTT, licensed SDK functions and enclosure metrology are
outside this project's software scope.

| Area | Weight | Implemented | Score |
|---|---:|---|---:|
| Core ranges and channel controls | 25 | HR 10–300, SpO2 0–100, independent AC/DC, PI convenience range 0.01–30, offset and AC/DC ownership | 24 |
| Waveform and morphology | 20 | PPG/sine/triangle/square, per-channel SP/DN/DP, polarity and gain | 17 |
| Respiration and apnea | 15 | 1–150 brpm, 1:1–1:5, baseline/amplitude/frequency modulation, independent channel depth, duration/cycle | 15 |
| SpO2 model and calibration | 20 | configurable A/B ratio curve, manual RED AC override, unequal DC support and bounded DAC output | 17 |
| Operation, record and playback | 10 | timestamped recording across pages, legacy playback and explicit calibration | 9 |
| UI, persistence and validation | 10 | 1024×600 layout, light/dark clinical hierarchy, transactional validation and atomic save | 9 |
| **Total** | **100** | **PPG/SpO2 software control coverage** | **91** |

The remaining nine points are mainly arbitrary waveform/playlist sequencing,
commercial calibration-table workflow, automatic optical feedback setup, and
high-frequency artefacts above the 100 Hz model Nyquist limit. The 91% score is
a transparent feature checklist, not a measurement-accuracy score. The whole
multi-mode AECG100 product would score much lower because ECG and PWTT are not
implemented.

## Main implementation

- `models/ppg_model.py`, `models/waveform.py`, `models/respiration.py`,
  `models/noise.py` and `models/limits.py`: waveform generation, full ranges,
  respiratory modulation, artefacts, channel ownership and model options.
- `core/signal_engine.py` and `core/rate_scheduler.py`: thread-safe
  transactions, model/DAC scheduling, bounded buffers, calibration and
  recording queues.
- `ui/ctk_app.py`, `ui/theme.py`, `ui/trace_view.py` and `ui/frames/`:
  clinical monitor, setup, calibration and timestamp-aware recordings.
- `config_store.py`: versioned round-trip and atomic replacement of JSON
  configuration.
- `docs/system_3d/viewer_template.html`, `viewer.html`, `build_system.py`
  and `out/`: web viewer, generated model and printable output.

## Verification performed

- Headless software suite: 601 passed, 1 skipped, 233 unittest subtests passed.
- GUI integration under a virtual X display: navigation, valid and invalid
  parameter apply, recording across pages, playback, calibration shutdown,
  1024×600 clipping check and DAC parking all passed.
- Web preview: waveform normalization, independent DC ratio, finite samples and
  bounds passed in Node; the generated viewer was rendered in headless Chrome.
- Mechanical output: all 96 geometry checks passed, including 15 watertight
  STLs, mating features, clearances, zero-volume intersections and Bambu layout.
- Python dependencies: `pip check` reported no broken requirements.
- Setup scripts: shell syntax checks passed; laptop environment verification
  returned PASS=20, FAIL=0, SKIP=2.

The skipped check requires a physical or emulated condition that is not present
in the laptop dry-run environment.

## Physical acceptance still required

Run these on the assembled Raspberry Pi hardware before claiming instrument
performance:

1. Measure actual DAC update cadence and jitter; 1 kHz is a target under
   Linux/I2C scheduling.
2. Measure MCP4725 output, op-amp command voltage and each sense-resistor voltage
   for direct and 10k/10k input options.
3. Confirm LED current, transistor pinout, thermal limits and compliance across
   the full configured range.
4. Measure OPT101 A0/A2 response, dark baseline, saturation, optical isolation
   and distance/aperture effects.
5. Fit SpO2 coefficients or a lookup table against the specific optical assembly
   and reference device.

An I2C acknowledgement, a passing dry-run test, or a realistic-looking plot
does not satisfy these physical checks.
