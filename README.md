# 🫀 PPG Signal Simulator — Raspberry Pi 4

**Dual-channel PPG research simulator with Raspberry Pi software, three KiCad 10 boards and a printable optical enclosure.**

![Version](https://img.shields.io/badge/version-5.0.0-blue)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%204-green)
![Language](https://img.shields.io/badge/language-Python%203.10+-orange)
![License](https://img.shields.io/badge/license-MIT-yellow)

**Group #2:** HuyNN, VyPT
**Institution:** Industrial University of Ho Chi Minh City (IUH) — Faculty of Electronic Technology
**Version:** 5.0.0 — waveform controls and timestamped recording

---

## 📋 Overview

The Raspberry Pi runtime synthesizes IR/RED signals at 100 Hz, interpolates them
for a nominal 500 Hz dual-MCP4725 output on ARM64, and acquires OPT101 signals separately.
`PPG_DAC_RATE_HZ` supports 100/200/500/1000 Hz; desktop default is 1000 Hz.
Pi GUI + BLE + A0 verification at 500 Hz completed 30 seconds without buffer
overruns or dropped samples. Optical waveform fidelity is still unverified.
The empirical SpO₂ mapping is configurable; a realistic plot does not establish
optical accuracy or compatibility with a particular pulse oximeter.

**Touch and sequence update (30 September 2026):** Numeric controls use sliders;
Settings and calibration include −/+ fine steps. **04 PPG morphology** offers
fitted Gaussian and an exploratory **LSM-GAN 30-second sequence**, a real training
reference, and a live **OPT101 RX** card (A0/A2). **A2 is disabled until its sensor is installed.**
Play/Stop uses the shared MCP4725 writer; clips stop at 30 seconds or when leaving
the page. Opening the page does not emit output. Classic Gaussian is preserved.

LSM keeps native 40 Hz timing and has no HR/notch conditioning. The existing v2
checkpoint has excessive beat variability relative to median validation data;
it is a development baseline, not a validated human-PPG replacement. IR/RED share
one shape with nominal scaling. See [architecture choice, measured sequence audit
and touch/output details](docs/ppg_touch_sequence_output_2026-09-30.md).
The [earlier morphology comparison](docs/ppg_morphology_selection_2026-09-28.md)
remains a historical exploratory result; test has already been viewed.

**RX beside TX & Bench Diagnostics (October 2026):**
- **Live A0/A2 RX card on every page:** Classic, Calibration, Recordings and PPG morphology each show a read-only RX card next to the TX plot (the earlier bottom dock, and the RX strip inside the Signal setup window, are removed). It displays the rolling 8-second window of raw ADC mV at up to 10 Hz refresh, with explicit status states (disabled, dry-run, stale, error, full-scale) and touch-optimized scrolling on 1024×600 screens ([docs/rx-monitor-2026-10-01.md](docs/rx-monitor-2026-10-01.md)).
- **Physical Sensor Diagnostic Protocol:** A bench test and signal conditioning plan is established for OPT101 / CJMCU-101 modules, covering internal 1 MΩ feedback verification, 3.3 V Grove Hat input limits, dark readings, stepped sine wave tests (1–10 Hz), and RC low-pass filtering at $f_c \approx 33.9\text{ Hz}$ ([docs/opt101-a0-diagnostic-2026-10-01.md](docs/opt101-a0-diagnostic-2026-10-01.md)).

| Live monitor | Waveform setup | 30-second sequence |
|---|---|---|
| ![PPG monitor in dry-run mode](docs/ui/monitor-1280.png) | ![Signal setup controls](docs/ui/setup-1280.png) | ![LSM-GAN sequence screen](docs/ui/touch-output/lsm-vi-1280.png) |

### What's complete in v5

- Light controls, charcoal IR/RED plots, large setpoints and timestamp axes. The UI scales automatically from compact 7-inch 1024×600 panels through Full-HD/QHD desktop displays.
- HR 10–300 bpm; respiration 1–150 brpm; SpO₂ target 0–100%; PI convenience input 0.01–30%.
- Independent IR/RED AC and DC, AC/DC ownership, output offset, gain and polarity.
- PPG, sine, triangle and square waveforms; independent SP/DN/DP timing for each channel.
- Baseline, amplitude and frequency respiratory modulation, inhale/exhale ratio, per-channel variation and periodic apnea.
- Absolute-mV artefacts with optional seeds; configurable HR/amplitude, SpO₂/notch and beat-variability effects.
- Timestamped 100 Hz model-command CSV recording continues across pages; playback follows the recorded timestamps.
- Explicit Start/Stop for calibration; only the engine's DAC thread produces its sine output.
- Configuration round-trip, validation and atomic JSON save. Opening a page does not change signal parameters.
- English/Vietnamese UI; touch-sized controls; TX on the left and live OPT101 A0/A2 RX on the right of every page. A2 acquisition awaits an installed sensor.
- Collapsible left navigation rail (icons collapsed, labels overlay when expanded), light/dark theme saved in `config.json`, and a Classic page with TX and RX side by side. The status line reports *no MCP4725 at 0x60/0x61* instead of claiming LED output when the DACs do not answer.
- `scripts/deploy_and_run.sh` (run on the laptop): SSH check, `i2cdetect -y 1` report for 0x08/0x60/0x61, rsync to the Pi, restart the app on the Pi display, and a dry-run copy on the laptop. When the Ethernet link reports `NO-CARRIER`, use the Wi‑Fi address: `PI_HOST=user@<pi-wifi-ip> scripts/deploy_and_run.sh`, and stop any other running instance first so two apps do not share I2C/BLE.

See [the continuation and validation report](docs/phase_reports/V5_CONTINUATION_REPORT.md)
for scope, evidence, commercial-reference comparison and physical validation still needed.

### Neural waveform models

The current **04 PPG morphology** page keeps the original three-Gaussian
generator and offers the LSM-GAN sequence as an experimental model. The
cWGAN-GP checkpoint below is retained for research comparison; it is not the
current sequence source. Both neural models were trained from BIDMC 1.0.0 PPG
records using subject-separated train/validation/test groups. They do not learn
separate IR and RED optical channels.

| Model | What goes in → what comes out | Network idea | Current role |
|---|---|---|---|
| cWGAN-GP pilot | 32-value random latent vector + 7 measured morphology conditions → one 256-point, phase-normalized pulse | Dense layers followed by three linear-upsample/Conv1D stages; strided-convolution critic; Wasserstein loss with gradient penalty | Research artifact only; the pilot export contains G but not its trained critic. The app's older preview repeated this one pulse to form a longer trace. |
| LSM-GAN v2 | A random 1,200-point noise strip → 1,200 PPG samples, 30 s at 40 Hz | Generator has parallel Conv1D branches (kernels 5/21/61) and a spectral-matching objective; its discriminator is a CNN with two real/fake scores | Experimental long-sequence option in page 04; no HR/notch control. |

For LSM-GAN, training used 624 non-overlapping 30-second windows from 32
patients; validation and test each used 112 windows from 7 separate patients.
BIDMC's 125 Hz signals were resampled to 40 Hz, filtered at 0.9–5 Hz and
normalized per window. This is not raw, full-band PPG or a healthy-population
dataset. The model produces a normalized shape; the app maps that shape to
nominal IR/RED voltage levels, so it does not predict two independently learned
optical signals or calibrated SpO₂.

These experiments are **exploratory** because the test set had already been
viewed. cWGAN makes a single pulse while LSM-GAN makes a long sequence, so
their scores are not a fully like-for-like ranking. Selection considers the
pre-agreed spectrum similarity, autocorrelation and high-frequency energy;
loss and discriminator scores alone are not evidence of realistic PPG.
See the [detailed LSM/GAN report](docs/ppg_lsm_gan_report_2026-09-26.md),
[cWGAN and LSM integration audit](docs/ppg_neural_preview_report_2026-09-28.md)
and [current sequence and hardware validation](docs/ppg_touch_sequence_output_2026-09-30.md).

### Key Specifications

| Parameter               | Value                                           |
|------------------------|-------------------------------------------------|
| Platform               | Raspberry Pi 4 (Ubuntu 24.04/26.04 LTS, arm64)  |
| UI Library             | CustomTkinter                                   |
| DAC                    | MCP4725 (12-bit, I2C) × 2 — IR & Red channels   |
| Model Rate             | 100 Hz                                          |
| DAC Rate               | Pi: 500 Hz target; configurable; Linux/I²C timing requires measurement |
| Data Recording         | 100 Hz model commands, timestamped CSV in `dataset/` |
| DAC Voltage Range      | Configured 0–3.28 V (0 → 0, 3.28 V → 4095) |
| Live RX ADC Channels   | A0 (IR) & A2 (Red) on Grove Base Hat (I2C 0x08) |

---

## 🛠️ Hardware Architecture

### Pin Mapping (Raspberry Pi 4, BCM numbering)

```
MCP4725 DACs (I2C Bus 1):
  GPIO2 (pin 3)   → I2C1_SDA
  GPIO3 (pin 5)   → I2C1_SCL
  Addresses: 0x60 (IR channel), 0x61 (Red channel)

Display:
  HDMI → Any screen (auto-detect resolution)
```

### Three KiCad 10 boards

The current CAD release has two alternative receiver boards and one LED
driver. Assemble **either** receiver for the optical channel pair; the V-cut
panel contains all three designs for fabrication, then separates into three
electrically independent boards.

| Board | Size | Main parts | Project |
|---|---:|---|---|
| OPT101 receiver | 70 × 20 mm | Two OPT101P in DIP-8 sockets; 2 mm Grove A2/RED and A0/IR headers; ADS1115 signal header; supply bypass and output RC | [Schematic, PCB and assembly notes](hardware/opt101_receiver_kicad/opt101_receiver/README.md) |
| BPW34 receiver | 70 × 20 mm | Two BPW34, two OPA333 TIAs, 1 MΩ/22 pF feedback, 2 mm Grove headers, ADS1115 signal/GND header | [Schematic, PCB and assembly notes](hardware/bpw34_receiver/README.md) |
| LED/IR driver | 70 × 40 mm | Two plug-in MCP4725 modules, socketed LM358, two 2N4401 current sinks, LED and 5 V headers | [Schematic, PCB and assembly notes](hardware/led_ir_driver/README.md) |

| OPT101 receiver | BPW34 receiver | LED/IR driver |
|---|---|---|
| ![OPT101 receiver PCB](hardware/opt101_receiver_kicad/opt101_receiver/reports/pcb_top.png) | ![BPW34 receiver PCB](hardware/bpw34_receiver/reports/pcb_top.png) | ![LED and IR driver PCB](hardware/led_ir_driver/reports/pcb_top.png) |

The [70 × 80 mm V-cut panel](hardware/ppg_panel/README.md) marks two score lines
at 20 and 40 mm. Copper stays at least 1.5 mm from each line. Send the
[panel fabrication ZIP](hardware/PPG_3boards_VCUT_panel.zip) to a board house
that accepts three designs on one panel. Standalone packages are available for
[OPT101](hardware/PPG_OPT101_receiver.zip), [BPW34](hardware/PPG_BPW34_receiver.zip)
and the [driver](hardware/PPG_LED_IR_driver.zip). Confirm V-score capability and pricing with the board house;
separate the bare boards before soldering.

![Three-board V-cut fabrication panel](hardware/ppg_panel/reports/pcb_top.png)
![V-cut positions and dimensions](hardware/ppg_panel/reports/vcut_drawing.png)

#### PCB Routing Quality & Chamfering

All three PCB layouts and the fabrication panel have undergone automated geometric auditing and cleanup:
- **100% 45° Chamfered Corners:** Automated chamfering (`hardware/routing_45.py`) converts all right-angle bends into smooth $1.2\text{ mm}$ 45° diagonal transitions, preventing acid traps and impedance discontinuities while preserving clearance.
- **Copper Segment Cleanup:** `clean_segments()` resolves multi-node track junctions, deduplicates coincident traces, merges collinear segments, and eliminates non-functional copper stubs.
- **Detailed Wiring Guides:** Enhanced wiring guides ([BPW34 guide](hardware/bpw34_receiver/reports/wiring_guide.png), [Driver guide](hardware/led_ir_driver/reports/wiring_guide.png)) render net-colored tracks and explicitly mark interlayer vias with white circular glyphs to assist manual assembly, testing, and probe placement.
- **DRC Verification:** KiCad design rule checks confirm 0 DRC violations, 0 unrouted nets, and full compliance with 2-layer FR-4 $1.6\text{ mm}$ manufacturing constraints.

### Printable optical enclosure

The dark chamber has separate RED/IR lanes, a sliding LED carrier, replaceable
apertures, a labyrinth lid and cable passages. The parametric model and assembly
instructions are in [docs/system_3d](docs/system_3d/README.md). For a 180 mm
Bambu bed, use the [three-plate print package](docs/system_3d/out/print_bambu_180.zip)
for the original enclosure parts. The compact receiver PCBs use **separate H-shaped
supports**, with open space under the PCB for header cables: [OPT101 STL](docs/system_3d/out/print_bambu_180/14_ga_chu_U_OPT101_70x20.stl)
and [BPW34 STL](docs/system_3d/out/print_bambu_180/15_ga_chu_U_BPW34_70x20.stl).
The driver has its [70 × 40 mm adapter STL](docs/system_3d/out/print_bambu_180/16_ga_driver_70x40.stl).
Read the [mounting notes](docs/system_3d/out/print_bambu_180/README_PCB_MOUNTS.md)
before printing: the receiver support is 3.8 mm thick in a 4.3 mm nominal slot;
test-print one support and check fit in the actual enclosure.

![Assembled optical enclosure](docs/system_3d/out/preview_assembled.png)
![Electronics inside the model](docs/system_3d/out/preview_electronics.png)

KiCad ERC/DRC, schematic-to-PCB checks and nominal mechanical collision checks
are recorded in each hardware project's `reports/` and `mechanical/` folders.
They do not establish physical fit, analog noise, optical isolation or LED current.
Check module pin order, MCP4725 I²C addresses, supply voltage and fit on the
actual parts before powering the assembly.

> **The IR lane has no STLs of its own — this is deliberate, not a missing
> export.** The two optical lanes are mirror-symmetric about z = 0, so the
> `slide_shaft`, `led_carrier`, `push_rod`, `rod_knob`, `aperture_*` and `hood_*` parts are
> exported once under the `_red` name and printed twice (the `*_ir` copies exist
> in `model.json` for the viewer only). Print counts are in the STL table of the
> `docs/system_3d/` README.

---

## 💻 Software Architecture

### Folder Structure

```
PPG_simulator_raspi/
├── main.py                      # Application entry point
├── config.py                    # Constants, theme & styles (single source of truth for version)
├── config_store.py              # JSON configuration persistence & validation
├── core/
│   ├── signal_engine.py         # Signal generation thread & DAC output
│   ├── csv_logger.py            # Dataset recording logic
│   ├── tx_rx_logger.py          # Paired TX command & RX acquisition logger
│   ├── rate_scheduler.py        # Drift-free fixed-rate execution ticker
│   └── state_machine.py         # System operational state machine
├── hw/
│   ├── opt101_rx.py             # Grove Base Hat ADC reader (A0/A2 channels)
│   ├── dac_manager.py           # Dual MCP4725 I2C DAC controllers
│   ├── adc_reader.py            # Low-level ADC reading interface
│   └── button_handler.py        # Physical push-button interrupt handler
├── models/
│   ├── ppg_model.py             # PPG physiological synthesis model
│   ├── noise.py                 # Artefact generators (absolute-mV, band-limited)
│   ├── respiration.py           # Respiratory baseline/amplitude/RSA modulation
│   ├── waveform.py              # Pulse morphology (Gaussian, sine, square, triangle)
│   └── limits.py                # Parameter limits and boundary validation
├── led_driver/                  # Op-amp + BJT current-sink calculations & error budget
├── ui/
│   ├── ctk_app.py               # Main CustomTkinter UI shell & window manager
│   ├── rx_monitor.py            # Read-only A0/A2 RX lanes shown beside TX on every page
│   ├── trace_view.py            # High-performance trace plot widget
│   ├── touch_slider.py          # Touch-optimized slider with +/- step buttons
│   ├── advanced_controls.py     # Parameter validation & event dispatcher
│   ├── i18n.py                  # English and Vietnamese UI translations
│   ├── responsive.py            # Multi-resolution UI scaling (1024x600 to 4K)
│   └── frames/
│       ├── pathology_frame.py   # Classic PPG simulator & pathology controls
│       ├── calibration_frame.py # Sine wave DAC test & calibration
│       ├── advanced_frame.py    # Signal setup (AC/DC ownership, SpO2, artefacts)
│       ├── neural_frame.py      # LSM-GAN 30s sequence & morphology evaluation
│       └── playback_frame.py    # CSV recording browser & playback viewer
├── hardware/                    # KiCad 10 projects, V-cut panel & release ZIPs
├── docs/                        # Design documents, reports, and 3D STL models
│   ├── opt101-a0-diagnostic-2026-10-01.md # Bench test plan for physical sensor
│   ├── rx-monitor-2026-10-01.md           # Live RX view design notes & validation (dock era)
│   ├── ppg_touch_sequence_output_2026-09-30.md # Touch controls & GAN details
│   └── system_3d/               # 3D printable dark enclosure STLs & guide
└── dataset/                     # Recorded CSV dataset files
```

---

## 🔧 Installation & Setup

### 1. Prerequisites
- Raspberry Pi 4 with Ubuntu 24.04 or 26.04 LTS (aarch64)
- I2C enabled (`dtparam=i2c_arm=on` in `/boot/firmware/config.txt`; the setup
  script can add it after confirmation)
- Python 3.10+ and OS package `python3-tk`; install dependencies inside a venv.

For Ubuntu, use the repository setup script instead of installing into the
system Python:

```bash
./scripts/setup_rpi_ubuntu.sh --enable-i2c
```

For a laptop-to-Pi Ethernet cable, source transfer, repeatable `ping`/`ssh`
commands, and remote debugging, follow
[docs/setup/RASPBERRY_PI_4_UBUNTU_26_04_SSH.md](docs/setup/RASPBERRY_PI_4_UBUNTU_26_04_SSH.md).

### 2. Laptop setup, run and tests

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade -r requirements/test.txt
.venv/bin/python main.py --dry-run
PPG_DRY_RUN=1 .venv/bin/python -m pytest -q
```

On the configured Raspberry Pi, use `.venv/bin/python main.py` for hardware mode.
Virtual environments are deliberately excluded from Git; recreate one on each
machine because wheels and interpreter paths are architecture-specific.

GUI interaction and screenshot check (requires a real display or Xvfb):

```bash
.venv/bin/python scripts/smoke_ui.py --output docs/ui
```

Install the PPG Simulator icon in the Raspberry Pi application dashboard and
place a trusted shortcut on the desktop:

```bash
./scripts/install_desktop_launcher.sh
```

The launcher uses this checkout's `.venv`, starts the normal GUI with BLE,
prevents duplicate instances and writes startup logs to
`~/.local/state/ppg-simulator/launcher.log`.

The laptop environment verifier also audits Git hygiene and rejects committed
virtual environments, bytecode and generated package caches.

### 3. BLE remote control (Android app)

The simulator can be driven from the Android app (`com.medical.simulator`)
over BLE GATT: `pip install -r requirements/ble.txt`, then run with `--ble`
(GUI) or `--ble-only` (headless). The phone advertises-pairs as central, sends
JSON setpoint commands (HR/SpO₂/RR/PI/noise/condition plus AC/DC amplitude
0–1500 mV per channel) and receives the 50 Hz waveform plus a 5 Hz status
snapshot with bidirectional sync. Full contract: `docs/ble_protocol.md`.

```bash
PPG_DRY_RUN=1 .venv/bin/python main.py --dry-run --ble        # GUI + BLE
PPG_DRY_RUN=1 .venv/bin/python main.py --dry-run --ble-only   # headless
```

---

## Operation

**Monitor:** adjust HR, SpO₂ target, respiration and PI with sliders, or type a
value and press Enter. Run starts TX; Stop parks both DAC command values at zero.
Record CSV starts capture; Save recording closes the file into `dataset/data_N.csv`.
Closing the app saves an active recording. The plotted signal is generated TX,
not an optical measurement. The right-hand numbers are setpoints.

**Signal setup:** each tab applies only when its Apply button is pressed.
Blank RED AC derives it from SpO₂. Explicit RED AC disconnects that amplitude
from the SpO₂ target and the monitor reports this. Lock AC holds AC while a PI
change moves IR DC; Lock DC lets PI move AC; both locks make PI read-only.
Feature times are quoted at 60 bpm and scale with cycle duration.

For a repeatable nominal waveform, disable respiratory modulation and all three
physiological dynamics switches on the Respiration tab. Otherwise modulation,
HR coupling and beat variability deliberately change the instantaneous AC/HR.

**Calibration & Sine Generator:** enter sine frequency (1–10 Hz) and peak output (100–3280 mV),
then Start calibration. Opening the page alone does not start output. Leaving the
page stops an active calibration. Sine calibration drives both MCP4725 DAC channels simultaneously.

**Live RX card:** every page shows an RX card to the right of its TX plot
(the Signal setup window has none). The receiver samples the Grove Base Hat ADC at 100 Hz and refreshes the UI at up to 10 Hz,
plotting an 8-second rolling window for A0 (IR) and A2 (Red). Sensor readings display raw
millivolts alongside real-time connection status (`LIVE`, `STALE`, `DRY RUN`, `DISABLED`, or `FULL SCALE`).
Dry-run mode and unplugged sensors explicitly show disconnected states without fabricating data.

**Neural Sequence & Morphology Evaluation:** the **04 PPG morphology** page allows selecting
between the standard three-Gaussian pulse synthesis and an experimental 30-second LSM-GAN
continuous pulse sequence. Clips automatically stop at 30 seconds or upon navigating away.
Opening the screen does not activate DAC output without an explicit Play action.
The TX card stacks the generated lane over the real reference lane; the RX card
on the right shows A0/A2 from the receiver.

**Recordings:** review saved TX command CSVs without driving hardware. The session
list is a drawer that folds to one icon and closes after a recording is picked.
Recorded TX sits on the left and the live RX card on the right; that RX is the ADC
reading at viewing time, not data stored in the recording. New files
contain `Time_s` and `Source`; the first seven columns retain the legacy schema.
Legacy files without timestamps explicitly assume 50 Hz for screen playback.
CSV output is a model command record, not proof that a DAC wrote every sample.

**Bench Diagnostics & Optical Validation:** for physical sensor testing with the OPT101 / CJMCU-101 module,
follow the testing protocol in [docs/opt101-a0-diagnostic-2026-10-01.md](docs/opt101-a0-diagnostic-2026-10-01.md):
1. Verify module pinout (ensure 1 MΩ internal feedback loop between pins 4 & 5; do not leave floating).
2. Measure baseline dark voltage under complete optical enclosure sealing.
3. Perform stepped sine excitation (1, 2, 5, 10 Hz) via DAC to measure sensor linearity, phase shift, and harmonic distortion.
4. If high-frequency ripple or ADC noise is present, insert an anti-aliasing RC filter ($R = 4.7\text{ k}\Omega$, $C = 1\ \mu\text{F}$, $f_c \approx 33.9\text{ Hz}$) between the OPT101 OUT pin and Grove A0 input. Keep Grove signals strictly $\le 3.3\text{ V}$.

| Calibration and RX status | Recording review |
|---|---|
| ![Calibration screen](docs/ui/calibration-1280.png) | ![Saved waveform playback screen](docs/ui/recordings-1280.png) |

## Signal relationships and limits

`PI = AC_IR / DC_IR × 100`; at DC=1500 mV, PI=3% gives nominal AC=45 mV.
RED is derived with the full ratio-of-ratios:

`R = max(0, (A − SpO₂_target) / B)`

`AC_RED = R × AC_IR × DC_RED / DC_IR`

The defaults A=110 and B=25 are an empirical example, not universal optical
calibration. The former R clamp of 0.4–1.6 has been removed so low SpO₂ targets
change the generated ratio. A negative requested R cannot be synthesized; the
monitor reports it. Unequal respiration depth and manually pinned RED AC can
change the instantaneous ratio from the nominal target.

PPG uses a normalized three-Gaussian shape. Respiratory depth defaults to 4% of
AC per channel, with baseline/amplitude/RSA modulation individually selectable.
Apnea suppresses respiratory modulation while cardiac pulses continue.

Direct AC entry spans 0–1500 mV and DC entry 0–1500 mV, matching the Android
app. PI-driven AC stays inside the direct AC range at these limits; output
offset spans 0–2000 mV with DC+offset≤3000 mV. Gain,
noise and modulation can still exceed DAC headroom: the output clamps to the
configured rails and the clipping counter reports it. A clipped waveform does
not meet the requested amplitude or ratio.

50/60 Hz mains noise is rejected by the 100 Hz synthesis model; 10× interpolation
does not create additional bandwidth. Likewise, the MCP4725 code step is about
0.80 mV at 3.28 V: software entry resolution is finer than physical DAC resolution.

The LED-driver topology in the supplied drawing is DAC → op-amp → NPN current
sink with emitter feedback through R_sense. The 3D preview defaults to this direct
command path, and offers the older 10k/10k divider hypothesis separately. Its
`I ≈ Vcmd/R` readout is an ideal estimate; current, compliance and optical response
must be measured on the actual assembly. No wiring, transistor or resistor is
changed by this software update.

## 👨‍💻 Authors

**HuyNN** — Hardware design, embedded firmware  
**VyPT** — Software design, UI/UX

**Institution:** Industrial University of Ho Chi Minh City (IUH)
