# PPG Simulator → WhaleTeq AECG100 Reference: Claude Code Phase Plan

Project root:
`/home/huynn/final_project/PPG_simulator_raspi/`

Reference PDFs:
- `/home/huynn/final_project/PPG_simulator_raspi/docs/user_manual.pdf`
- `/home/huynn/final_project/PPG_simulator_raspi/docs/version_sdk_app_whale.pdf`
- `/home/huynn/final_project/PPG_simulator_raspi/docs/whale_device.pdf`

Goal: redesign and refine the existing PPG simulator so that the relevant PPG/SpO2 functionality is functionally similar to the WhaleTeq AECG100 reference device at an engineering target of approximately 80–90%, without claiming verified equivalence unless demonstrated by real measurements.

## Current known hardware

- Raspberry Pi 4 running Ubuntu Linux 24.04 LTS.
- Seeed Grove Base Hat for Raspberry Pi 4.
- Two MCP4725 12-bit DAC modules over I2C, confirmed at addresses `0x60` and `0x61`.
- LM358 dual op-amp.
- 3 mm red LED.
- 3 mm IR LED.
- Two OPT101 photodetector modules are available, but no OPT101 acquisition code currently exists.
- Seeed Grove Base Hat ADC is available; current confirmed analog input in use is `A0`. The second OPT101 ADC channel assignment is not yet confirmed and must not be invented.
- Resistors and basic passive components.

Do not assume unverified part numbers, LED wavelengths, supply rails, I2C addresses, ADC limits, DAC count, or transistor/MOSFET availability.

## Phase order

1. `01_PHASE_REFERENCE_AUDIT_AND_MASTER_DESIGN.md`
2. `02_PHASE_CONFIG_AND_SPO2_CALIBRATION.md`
3. `03_PHASE_AC_DC_PI_AND_RED_IR_MODEL.md`
4. `04_PHASE_DUAL_DAC_AND_LED_DRIVER_INTEGRATION.md`
5. `05_PHASE_OPT101_AND_GROVE_ADC_ACQUISITION.md`
6. `06_PHASE_SIGNAL_PROCESSING_AND_MEASURED_SPO2.md`
7. `07_PHASE_LINUX_UI_TX_RX_VISUALIZATION.md`
8. `08_PHASE_HARDWARE_DIAGNOSTICS_AND_RUNTIME_SAFETY.md`
9. `09_PHASE_TESTS_AND_VALIDATION.md`
10. `10_PHASE_CALIBRATION_DOCUMENTATION_AND_FINAL_ACCEPTANCE.md`

## Global execution rule

Every phase must begin by reading:
- the phase file,
- all prior phase reports/plans generated in the repository,
- the current codebase state,
- relevant PDFs and hardware evidence.

Do not redo completed work. Do not rewrite unrelated code. Make the smallest technically correct change. Preserve working architecture. Never fabricate measurements, successful builds, hardware behavior, calibration accuracy, timing, or validation results.

When evidence is insufficient, write exactly:
`I am not sure based on the currently available evidence.`


## Verified hardware baseline for all phases

Treat the following as user-confirmed hardware facts unless later evidence supersedes them:

- 2 x MCP4725 exist physically.
- Confirmed I2C addresses: `0x60` and `0x61`.
- Measured DAC full-scale voltage: `3.2 V`.
- Grove Base Hat ADC currently uses analog input `A0`.
- 2 x OPT101 modules are available.
- There is currently no OPT101 reader/acquisition code in the project.
- Do not assume which MCP4725 address is physically wired to Red or IR unless wiring/code evidence confirms it.
- Do not assume the second OPT101 ADC channel (for example `A1`) until it is explicitly confirmed by wiring, code, or user evidence.
