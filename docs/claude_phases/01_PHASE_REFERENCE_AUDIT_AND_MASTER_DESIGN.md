# Phase 1 — Reference Audit and Master System Design

## Project

Project root:
`/home/huynn/final_project/PPG_simulator_raspi/`

Reference PDFs:
- `docs/user_manual.pdf`
- `docs/version_sdk_app_whale.pdf`
- `docs/whale_device.pdf`

## Objective

Read all three PDFs and audit the complete existing PPG simulator codebase before modifying any code. Use WhaleTeq AECG100 only as the reference for relevant PPG/SpO2 behavior. The target is approximately 80–90% functional similarity for the relevant PPG/SpO2 subsystem, not the full ECG/PWTT product.

Do not claim 80–90% similarity as achieved unless it is defined feature-by-feature and supported by real validation evidence.

## Mandatory scope

Focus on:
- PPG waveform generation.
- Heart rate.
- Respiratory rate.
- Red/IR optical channels.
- SpO2 target simulation.
- Adjustable SpO2 equation `SpO2 = A - B * R`.
- Adjustable A and B.
- Adjustable AC and DC in mV.
- PI derived from AC/DC.
- Noise level.
- BM/AM/FM respiration modulation where relevant.
- AC above DC / AC below DC.
- Generated waveform display.
- Received waveform display.
- Two OPT101 receivers.
- Grove Base Hat ADC acquisition.
- DAC output to Red/IR optical transmitter path.
- Calibration and validation workflow.

Exclude unrelated ECG/PWTT implementation unless a shared architecture detail is necessary.

## Current known hardware

- Raspberry Pi 4.
- Ubuntu 24.04 LTS.
- Seeed Grove Base Hat.
- Two MCP4725 12-bit DAC modules over I2C, physically present and confirmed at addresses `0x60` and `0x61`.
- LM358.
- Red 3 mm LED.
- IR 3 mm LED.
- Two OPT101 modules.
- Grove Base Hat ADC; current confirmed analog input in use is `A0`.
- Resistors and basic passives.

Treat the existence of two MCP4725 modules and addresses `0x60` and `0x61` as user-confirmed hardware facts. Still verify the current code mapping, runtime bus detection, and physical Red/IR wiring before assigning a specific optical channel to a specific address.

Do not assume the red LED is exactly 660 nm or the IR LED is exactly 940 nm unless verified by part number or datasheet.


## User-confirmed hardware facts that override prior uncertainty

The following are confirmed by the user and must be treated as known facts in this phase:
- Two MCP4725 modules are physically present.
- Their I2C addresses are `0x60` and `0x61`.
- The measured DAC full-scale output is `3.2 V`.
- The Grove Base Hat ADC currently uses analog input `A0`.
- Two OPT101 modules are physically available.
- No OPT101 acquisition code currently exists.

Important remaining unknowns:
- Do not assume which MCP4725 address drives Red and which drives IR unless verified from source code and wiring evidence.
- Only ADC input `A0` is currently confirmed. The second OPT101 ADC channel is not yet confirmed; do not invent `A1` or any other mapping.

## Mandatory audit

Inspect the entire active codebase before proposing edits. At minimum inspect:
- `main.py`
- `config.py`
- `config_store.py`
- `models/`
- `core/`
- `hw/`
- `ui/`
- `comm/`
- tests
- docs
- DAC code
- ADC code
- signal generation
- signal engine
- UI thread/update path
- I2C usage
- GPIO usage
- hardware dry-run/simulation mode

Identify actual:
- thread/task ownership,
- buffers,
- sample rates,
- DAC update rate,
- interpolation,
- I2C addresses,
- hardware abstraction,
- current parameter limits,
- current AC/DC/PI relationship,
- current SpO2 formula,
- current Red/IR architecture,
- current UI architecture.

## Required reference extraction from PDFs

Build an evidence table for all relevant PPG/SpO2 features and ranges, including where applicable:
- HR range and default.
- RR range and default.
- PPG AC/DC/PI ranges and defaults.
- Red/IR channel behavior.
- SpO2 mode behavior.
- R curve / calibration equation behavior.
- Noise frequencies and amplitude.
- BM/AM/FM respiration modulation.
- AC above/below DC.
- Sampling PD.
- LED switch sampling.
- waveform display.
- save/recall/player features.
- optical alignment.
- calibration workflow.

For each fact, record:
- source PDF,
- page/section,
- exact verified value,
- relevance to this project.

## Required mathematical architecture

The design must distinguish target generation from measurement.

### Target generation

`R_target = (A - SpO2_target) / B`

Full ratio-of-ratios:

`R = (AC_red / DC_red) / (AC_ir / DC_ir)`

Therefore:

`AC_red = R_target * AC_ir * (DC_red / DC_ir)`

Only simplify to `AC_red = R_target * AC_ir` when `DC_red == DC_ir`.

### Measured SpO2

From OPT101 acquisition:

`R_measured = (AC_red_measured / DC_red_measured) / (AC_ir_measured / DC_ir_measured)`

`SpO2_measured = A - B * R_measured`

Changing A or B only changes the numerical mapping unless the simulator uses the new A/B values to recalculate `R_target` and therefore changes generated Red/IR amplitudes.

## Required diagrams and design deliverables

Before any code modification, produce:

1. Executive summary.
2. AECG100 relevant PPG/SpO2 feature summary.
3. Current codebase architecture.
4. Current hardware architecture.
5. Reference-vs-current gap matrix.
6. Target system architecture.
7. System block diagram.
8. Software architecture diagram.
9. Hardware architecture diagram.
10. Complete end-to-end data pipeline.
11. Red transmitter block/circuit concept.
12. IR transmitter block/circuit concept.
13. Red OPT101 receiver path.
14. IR OPT101 receiver path.
15. I2C topology.
16. ADC topology.
17. Power/ground plan.
18. Timing/thread architecture.
19. UI architecture.
20. SpO2 mathematical model.
21. AC/DC/PI model.
22. Configurable A/B calibration design.
23. Noise model.
24. Respiration model.
25. Calibration workflow.
26. Oscilloscope validation plan.
27. Logic analyzer validation plan.
28. Risk register.
29. Unknowns requiring physical measurement.
30. BOM split into owned / required / optional / replacement recommended.
31. Exact phased implementation plan.
32. Exact files to modify.
33. Files that should not be modified.
34. Tests to add.
35. Acceptance criteria.

Use Mermaid diagrams where useful, but every arrow must have a defined meaning.

## Hardware analysis requirements

Analyze whether the current hardware is sufficient and explicitly identify gaps.

### MCP4725
Verify:
- confirm code support for the two known DAC modules/channels,
- I2C addresses,
- DAC voltage source of truth,
- verify and remove any mismatch between the measured `3.2 V` DAC full-scale and any hardcoded `3.3 V` assumptions,
- 12-bit resolution,
- voltage-per-LSB,
- update rate,
- Linux jitter,
- ability to represent small AC values.

### LM358
Analyze:
- actual supply rail if known,
- common-mode range,
- output swing,
- bandwidth,
- saturation,
- suitability as prototype LED driver,
- whether transistor/MOSFET is required.

Do not invent component values or transistor parts.

### LEDs
Verify actual wavelength, polarity, forward voltage, current rating, optical geometry and temperature effects only when supported by evidence.

### OPT101
Treat the absence of existing OPT101 reader code as confirmed current state. Design the receiver path without pretending acquisition already works.

Analyze:
- supply,
- output range,
- responsivity vs wavelength,
- saturation,
- bandwidth,
- ambient light,
- crosstalk between Red and IR,
- need for shielding, optical filters or time-division multiplexing.

### Grove Base Hat ADC
Verify actual API, resolution, input range, channels, sampling behavior and suitability from source code and documentation present in the project. Do not fabricate an API.

## Strict rules

- Do not change code in Phase 1.
- Do not redo already completed work.
- Do not remove working code.
- Do not invent measurements or validation results.
- Do not claim clinical-grade performance.
- Separate verified evidence from inference and unknowns.

## Output

Write the Phase 1 report into a new documentation file inside the project, preferably under:

`docs/architecture/`

Use a clear filename such as:

`docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md`

At the end, stop and wait for review. Do not begin Phase 2 automatically.
