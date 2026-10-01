# A0/A2 monitor

Added a persistent, read-only OPT101 RX dock to Classic, Calibration, Recordings and Neural, plus the Settings window. A0/IR and A2/RED retain independent acquisition timestamps. The last eight seconds are displayed at up to 10 UI refreshes/second, using the existing ADC buffers; mV is derived from the configured ADC reference. No smoothing, zero filling, or interpolation across gaps over 50 ms is applied. Disabled, dry-run, stale, invalid, error and ADC-full-scale states are explicit. A2 acquisition remains disabled until its sensor is installed/configured.

On compact displays the page content scrolls while navigation and RX remain fixed, avoiding squeezed TX plots. The scrollbar is widened for touch. English and Vietnamese monitor labels follow Settings.

Validation: 736 tests passed, 1 skipped, 288 subtests passed. scripts/smoke_rx_monitor.py passed under a 1024x600 Xvfb display with a 958x531 app window: all pages, Settings, language changes, independent channel mapping, missing-data line breaks, stale-data expiry and no output activation. Screenshots in docs/ui/rx-monitor are dry-run UI captures, not hardware measurements.

Deployed the three changed UI files to /home/huy/final_project/PPG_simulator_raspi/ui on Pi via the saved Wi-Fi alias (192.168.16.101). Remote SHA-256 values match local files. Original files backed up under /home/huy/ppg-backups/pre-rx-monitor-20261001. Started the app on Calibration with the transient ppg-simulator user service; service active. Startup confirmed Grove 0x08, enabled channel A0, 100 Hz acquisition and probe raw=320. No sine output was requested by this UI validation.

Runtime limitation: startup logged one Red DAC 0x61 I/O write error. This is a separate hardware-output issue; successful UI deployment does not establish healthy RED output or optical waveform fidelity. Live GUI appearance on the physical display has not been captured in this turn.
