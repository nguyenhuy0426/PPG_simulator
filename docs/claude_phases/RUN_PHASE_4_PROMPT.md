Before changing anything, read these first and treat the current architecture truth as authoritative:
- docs/claude_phases/00_CURRENT_PROJECT_ARCHITECTURE_SOURCE_OF_TRUTH.md
- docs/claude_phases/00_README_FROM_PHASE_4.md

Read and execute ONLY Phase 4 from:

/home/huynn/final_project/PPG_simulator_raspi/docs/claude_phases/04_PHASE_DUAL_DAC_AND_LED_DRIVER_INTEGRATION.md

Project root:
/home/huynn/final_project/PPG_simulator_raspi/

Before changing anything, read the Phase 1 architecture report, Phase 1–3 completion reports, current source code, and current git diff. Do not redo completed work.

Verified hardware architecture:
- exactly 1 Raspberry Pi 4 and 1 Seeed Grove Base HAT are used for TX, RX, processing, and UI;
- Raspberry Pi I2C is exposed/routed through the Grove Base HAT path to the DAC modules;
- MCP4725 0x60 = IR TX;
- MCP4725 0x61 = Red TX;
- DAC full-scale = 3.2 V;
- OPT101 IR -> A0;
- OPT101 Red -> A1;
- the previous A2 mapping is obsolete.

Execute only Phase 4. Preserve all Phase 2–3 math and existing passing tests. Do not implement OPT101 acquisition or measured SpO2 yet. Do not invent circuit values, LED ratings, timing, measurements, or hardware validation.

At the end create docs/phase_reports/PHASE_04_COMPLETION_REPORT.md with exact files changed, commands actually run, real PASS/FAIL/NOT RUN/BLOCKED results, shared one-Pi/one-HAT bus implications, LED-driver findings, hardware-validation status, git diff summary, acceptance checklist, and do-not-redo handoff for Phase 5.

Then STOP. Do not start Phase 5.
