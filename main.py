#!/usr/bin/env python3
"""
main.py — PPG Signal Simulator for Raspberry Pi 4

Entry point for the PPG Signal Simulator application.
Manages the main event loop, input handling, display updates, and state transitions.

Usage:
    python main.py                  # Normal mode (requires RPi hardware)
    python main.py --dry-run        # Dry-run mode (no hardware, simulated I/O)
    PPG_DRY_RUN=1 python main.py    # Alternative dry-run via env var

Controls:
    Keyboard:
        SPACE / M      — MODE button (cycle edit mode / start simulation)
        LEFT / RIGHT   — Adjust potentiometer (or use mouse scroll)
        1-6            — Quick-select condition
        C              — Toggle calibration mode (sine wave output)
        Q / ESC        — Quit
    Potentiometer:
        Analog input via Grove Base Hat ADC (A0)
    Push button:
        GPIO17 — MODE button
"""

import sys
import os
import time
import math
import argparse

# Parse --dry-run before importing config
parser = argparse.ArgumentParser(description="PPG Signal Simulator for Raspberry Pi 4")
parser.add_argument("--dry-run", action="store_true", help="Run without hardware (simulated I/O)")
args = parser.parse_args()

if args.dry_run:
    os.environ["PPG_DRY_RUN"] = "1"

# Now import everything (config reads DRY_RUN from env)
from config import (
    DEVICE_NAME, FIRMWARE_VERSION, FIRMWARE_DATE, DRY_RUN,
    METRICS_UPDATE_MS, WAVEFORM_UPDATE_MS, ADC_MAX_VALUE,
)
from comm.logger import log
from config_store import load_config, save_config, config_from_ppg_params, apply_config_to_params
from models.ppg_model import (
    PPGParameters, CONDITION_NAMES, COND_COUNT,
    get_ppg_limits, _clamp,
)
from core.state_machine import (
    StateMachine,
    STATE_INIT, STATE_SELECT_CONDITION, STATE_SIMULATING, STATE_PAUSED,
    EVT_INIT_COMPLETE, EVT_START_SIMULATION, EVT_BTN_MODE_PRESS, EVT_STOP, EVT_RESUME,
    EDIT_CONDITION_SELECT, EDIT_HR, EDIT_PI, EDIT_SPO2, EDIT_RR, EDIT_NOISE,
)
from core.signal_engine import SignalEngine, SIG_RUNNING
# ============================================================
# Physical hardware controls (potentiometer & button) removed
# Date: 2026-05-10
# Reason: Replaced by interactive sliders on the touch screen
# See Section 3.2 of the UI update plan.
# ============================================================
# [REMOVED] Physical potentiometer (GPIO17) and mode button (GPIO27) – replaced by on-screen sliders and BLE commands.
# from hw.adc_reader import ADCReader
# from hw.button_handler import ButtonHandler
from ui.pygame_display import PygameDisplay
from core.csv_logger import CSVLogger
from comm.ble_server import BleServer

import pygame


def mapf(x, in_min, in_max, out_min, out_max):
    """Linear mapping of x from [in_min, in_max] to [out_min, out_max]."""
    if in_max == in_min:
        return out_min
    return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min


def pot_to_condition(pot_raw: int, current_cond: int, adc_max: int, count: int) -> int:
    """Map potentiometer value to condition index with hysteresis.

    Divides the ADC range into `count` equal zones. Uses ±3% hysteresis
    at each boundary so that small ADC fluctuations near a boundary
    don't cause the condition to jump back and forth.

    Args:
        pot_raw:      Raw ADC value (0 .. adc_max)
        current_cond: Currently selected condition index
        adc_max:      Maximum ADC value (e.g. 4095)
        count:        Number of conditions (e.g. 6)

    Returns:
        Stable condition index (0 .. count-1)
    """
    zone_size = (adc_max + 1) / count        # ~683 counts per zone for 6 conditions
    hysteresis = zone_size * 0.06             # ±3% of zone width (~41 counts)

    # Calculate which zone the pot is pointing at
    candidate = int(pot_raw / zone_size)
    candidate = max(0, min(count - 1, candidate))

    if candidate == current_cond:
        return current_cond

    # Only accept a change if the pot has crossed the boundary + hysteresis
    if candidate > current_cond:
        boundary = current_cond * zone_size + zone_size  # upper edge of current zone
        if pot_raw >= boundary + hysteresis:
            return candidate
    else:
        boundary = current_cond * zone_size  # lower edge of current zone
        if pot_raw <= boundary - hysteresis:
            return candidate

    return current_cond


class PPGSimulatorApp:
    """Main application class for the PPG Signal Simulator."""

    def __init__(self):
        self.engine = SignalEngine.get_instance()
        self.state_machine = StateMachine()
        # self.adc = ADCReader()
        # self.buttons = ButtonHandler()
        self.display = PygameDisplay()
        self.csv_logger = CSVLogger()
        self.ble_server = BleServer(self.engine, self.display)

        # Simulated pot value (for keyboard/mouse control)
        self._sim_pot = 2048

        # Track last raw pot reading to detect intentional movement
        self._last_pot_raw = -1

        # Timing
        self._last_metrics = 0
        self._last_waveform = 0

        # Calibration mode
        self._calibration_mode = False
        self._cal_freq_idx = 0  # Index into [1, 2, 5] Hz
        self._cal_freqs = [1.0, 2.0, 5.0]
        self._cal_amplitude = 50.0  # mV
        self._cal_phase = 0.0
        self._cal_last_time = 0.0

    def setup(self):
        """Initialize all subsystems."""
        log.info("=" * 50)
        log.info(f"  {DEVICE_NAME} v{FIRMWARE_VERSION}")
        log.info(f"  {FIRMWARE_DATE}")
        log.info(f"  Mode: {'DRY-RUN' if DRY_RUN else 'HARDWARE'}")
        log.info("=" * 50)

        # Hardware init
        # self.adc.begin()
        # self.buttons.begin()
        self.engine.begin()

        # Display init
        self.display.begin()
        self.display.update_metrics(0, 0, 0, 0, "Initializing...")

        # BLE Init
        self.ble_server.begin()

        # State machine
        self.state_machine.set_state_change_callback(self._on_state_change)

        # Load saved config
        config = load_config()
        initial_condition = config.get("condition", 0)

        # Complete init
        self.state_machine.process_event(EVT_INIT_COMPLETE)

        # Auto-start with saved (or default Normal) condition
        self._start_simulation(initial_condition)

        # Apply saved parameters
        p = self.engine.get_ppg_params()
        apply_config_to_params(config, p)
        self.engine.update_heart_rate(p.heart_rate)
        self.engine.update_perfusion_index(p.perfusion_index)
        self.engine.update_spo2(p.spo2)
        self.engine.update_resp_rate(p.resp_rate)
        self.engine.update_noise_level(p.noise_level)

        log.info("All systems ready!")

    def run(self):
        """Main event loop."""
        self.setup()

        try:
            while self.display.running:
                self._handle_events()
                self._handle_inputs()
                self._update_display()
                self.display.flip()
                self.display.tick()
        except KeyboardInterrupt:
            log.info("Interrupted by user")
        finally:
            self.csv_logger.stop()
            self._shutdown()

    # ─── Event Handling ───
    def _handle_events(self):
        """Handle Pygame events (keyboard, mouse, window)."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.display.running = False

            if self.display.handle_event(event):
                # Slider or button changed! Update parameters
                p = self.engine.get_ppg_params()
                new_hr = self.display.sliders['hr'].get_value()
                if abs(new_hr - p.heart_rate) >= 1.0:
                    self.engine.update_heart_rate(new_hr)
                
                new_pi = self.display.sliders['pi'].get_value()
                if abs(new_pi - p.perfusion_index) >= 0.1:
                    self.engine.update_perfusion_index(new_pi)
                
                new_spo2 = self.display.sliders['spo2'].get_value()
                if abs(new_spo2 - p.spo2) >= 1.0:
                    self.engine.update_spo2(new_spo2)
                
                new_rr = self.display.sliders['rr'].get_value()
                if abs(new_rr - p.resp_rate) >= 1.0:
                    self.engine.update_resp_rate(new_rr)
                
                new_noise = self.display.sliders['noise'].get_value()
                if abs(new_noise - p.noise_level) >= 0.01:
                    self.engine.update_noise_level(new_noise)

                # Sync condition if changed from UI buttons
                if self.display.selected_cond_idx != self.state_machine.selected_condition:
                    if self.state_machine.state == STATE_SIMULATING:
                        self.engine.change_condition(self.display.selected_cond_idx)
                    self.state_machine.selected_condition = self.display.selected_cond_idx

            elif event.type == pygame.KEYDOWN:
                self._handle_keydown(event.key)

            elif event.type == pygame.MOUSEWHEEL:
                # Scroll wheel adjusts simulated pot value
                self._sim_pot = max(0, min(ADC_MAX_VALUE, self._sim_pot + event.y * 100))

    def _handle_keydown(self, key):
        """Handle keyboard input."""
        if key in (pygame.K_q, pygame.K_ESCAPE):
            self.display.running = False

        elif key == pygame.K_c:
            # Toggle calibration mode
            self._calibration_mode = not self._calibration_mode
            if self._calibration_mode:
                self._cal_phase = 0.0
                self._cal_last_time = time.time()
                self.display.clear_waveform()
                log.info(f"[CAL] Calibration ON: {self._cal_freqs[self._cal_freq_idx]} Hz sine")
                self.display.show_status(
                    f"CAL: {self._cal_freqs[self._cal_freq_idx]:.0f} Hz / "
                    f"{self._cal_amplitude:.0f} mV  [LEFT/RIGHT=freq] [C=exit]")
            else:
                log.info("[CAL] Calibration OFF")
                self.display.clear_waveform()

        elif key in (pygame.K_SPACE, pygame.K_m):
            # MODE button — simulate mode press via state machine
            if not self._calibration_mode:
                state = self.state_machine.state
                if state == STATE_SELECT_CONDITION:
                    cond = self.state_machine.selected_condition
                    self._start_simulation(cond)
                    self.state_machine.process_event(EVT_START_SIMULATION)
                elif state == STATE_SIMULATING:
                    self.state_machine.process_event(EVT_BTN_MODE_PRESS)
                    new_mode = self.state_machine.edit_mode
                    log.debug(f"[KEY] Edit mode: {StateMachine.edit_mode_to_string(new_mode)}")
                    if new_mode == EDIT_CONDITION_SELECT:
                        self.state_machine.process_event(EVT_STOP)
                        self.engine.stop_simulation()
                        self.csv_logger.stop()

        elif key == pygame.K_LEFT:
            if self._calibration_mode:
                self._cal_freq_idx = (self._cal_freq_idx - 1) % len(self._cal_freqs)
                self.display.show_status(
                    f"CAL: {self._cal_freqs[self._cal_freq_idx]:.0f} Hz / "
                    f"{self._cal_amplitude:.0f} mV  [LEFT/RIGHT=freq] [C=exit]")
            else:
                self._sim_pot = max(0, self._sim_pot - 200)

        elif key == pygame.K_RIGHT:
            if self._calibration_mode:
                self._cal_freq_idx = (self._cal_freq_idx + 1) % len(self._cal_freqs)
                self.display.show_status(
                    f"CAL: {self._cal_freqs[self._cal_freq_idx]:.0f} Hz / "
                    f"{self._cal_amplitude:.0f} mV  [LEFT/RIGHT=freq] [C=exit]")
            else:
                self._sim_pot = min(ADC_MAX_VALUE, self._sim_pot + 200)

        elif key in (pygame.K_1, pygame.K_2, pygame.K_3,
                     pygame.K_4, pygame.K_5, pygame.K_6):
            # Quick-select condition
            if not self._calibration_mode:
                cond = key - pygame.K_1
                if 0 <= cond < COND_COUNT:
                    self.state_machine.selected_condition = cond
                    self.display.selected_cond_idx = cond
                    if self.state_machine.state == STATE_SIMULATING:
                        self.engine.change_condition(cond)
                        self.display.clear_waveform()
                    elif self.state_machine.state == STATE_SELECT_CONDITION:
                        self._start_simulation(cond)
                        self.state_machine.process_event(EVT_START_SIMULATION)

    # ─── Input Handling ───
    def _handle_inputs(self):
        """Handle button presses and potentiometer input."""
        state = self.state_machine.state
        edit_mode = self.state_machine.edit_mode

        # ============================================================
        # Physical hardware controls (potentiometer & button) removed
        # Date: 2026-05-10
        # Reason: Replaced by interactive sliders on the touch screen
        # See Section 3.2 of the UI update plan.
        # ============================================================

        # MODE button
        # if self.buttons.was_mode_pressed():
        #     log.debug("[BTN] Mode pressed")
        # 
        #     if state == STATE_SELECT_CONDITION:
        #         cond = self.state_machine.selected_condition
        #         self._start_simulation(cond)
        #         self.state_machine.process_event(EVT_START_SIMULATION)
        # 
        #     elif state == STATE_SIMULATING:
        #         self.state_machine.process_event(EVT_BTN_MODE_PRESS)
        #         new_mode = self.state_machine.edit_mode
        #         log.debug(f"[BTN] Edit mode: {StateMachine.edit_mode_to_string(new_mode)}")
        # 
        #         if new_mode == EDIT_CONDITION_SELECT:
        #             self.engine.stop_simulation()
        #             self.csv_logger.stop()
        #             self.state_machine.process_event(EVT_STOP)
        #             self.display.clear_waveform()
        # 
        #     elif state == STATE_PAUSED:
        #         self.engine.resume_simulation()
        #         self.state_machine.process_event(EVT_RESUME)
        # 
        # # Potentiometer — read with heavy smoothing + deadzone from ADCReader
        # pot_raw = self.adc.read_raw()
        # 
        # # Skip processing if pot hasn't changed (deadzone already applied in ADCReader)
        # if pot_raw == self._last_pot_raw:
        #     return
        # self._last_pot_raw = pot_raw
        # 
        # if state == STATE_SELECT_CONDITION:
        #     cond = pot_to_condition(pot_raw, self.state_machine.selected_condition,
        #                            ADC_MAX_VALUE, COND_COUNT)
        #     if cond != self.state_machine.selected_condition:
        #         self.state_machine.selected_condition = cond
        #         self.display.show_condition_select(CONDITION_NAMES[cond], cond)
        # 
        # elif state == STATE_SIMULATING:
        #     p = self.engine.get_ppg_params()
        #     lim = get_ppg_limits(p.condition)
        # 
        #     if edit_mode == EDIT_CONDITION_SELECT:
        #         cond = pot_to_condition(pot_raw, self.state_machine.selected_condition,
        #                                ADC_MAX_VALUE, COND_COUNT)
        #         if cond != self.state_machine.selected_condition:
        #             self.state_machine.selected_condition = cond
        #             self.engine.change_condition(cond)
        #             self.display.clear_waveform()
        # 
        #     elif edit_mode == EDIT_HR:
        #         new_hr = round(mapf(pot_raw, 0, ADC_MAX_VALUE, lim.heart_rate.min, lim.heart_rate.max))
        #         if abs(new_hr - p.heart_rate) >= 1.0:
        #             self.engine.update_heart_rate(new_hr)
        # 
        #     elif edit_mode == EDIT_PI:
        #         new_pi = round(mapf(pot_raw, 0, ADC_MAX_VALUE,
        #                             lim.perfusion_index.min, lim.perfusion_index.max) * 10) / 10
        #         if abs(new_pi - p.perfusion_index) >= 0.1:
        #             self.engine.update_perfusion_index(new_pi)
        # 
        #     elif edit_mode == EDIT_SPO2:
        #         new_spo2 = round(mapf(pot_raw, 0, ADC_MAX_VALUE, lim.spo2.min, lim.spo2.max))
        #         if abs(new_spo2 - p.spo2) >= 1.0:
        #             self.engine.update_spo2(new_spo2)
        # 
        #     elif edit_mode == EDIT_RR:
        #         new_rr = round(mapf(pot_raw, 0, ADC_MAX_VALUE, lim.resp_rate.min, lim.resp_rate.max))
        #         if abs(new_rr - p.resp_rate) >= 1.0:
        #             self.engine.update_resp_rate(new_rr)
        # 
        #     elif edit_mode == EDIT_NOISE:
        #         new_noise = round(mapf(pot_raw, 0, ADC_MAX_VALUE, 0.0, 0.10) * 100) / 100
        #         if abs(new_noise - p.noise_level) >= 0.01:
        #             self.engine.update_noise_level(new_noise)

    # ─── Display Update ───
    def _update_display(self):
        """Update waveform and metrics on the display."""
        now_ms = time.time() * 1000
        state = self.state_machine.state

        # Calibration mode: generate sine wave for oscilloscope verification
        if self._calibration_mode:
            if now_ms - self._last_waveform >= WAVEFORM_UPDATE_MS:
                self._last_waveform = now_ms
                now = time.time()
                dt = now - self._cal_last_time
                self._cal_last_time = now
                freq = self._cal_freqs[self._cal_freq_idx]
                self._cal_phase += dt * 2.0 * math.pi * freq
                self._cal_phase %= (2.0 * math.pi)
                val = self._cal_amplitude * math.sin(self._cal_phase)
                # Both channels show identical sine for calibration
                self.display.draw_waveform_point(val, val)
            return

        # Waveform update (50 Hz)
        if now_ms - self._last_waveform >= WAVEFORM_UPDATE_MS:
            self._last_waveform = now_ms
            if state == STATE_SIMULATING and self.engine.state == SIG_RUNNING:
                ac_ir = self.engine.get_current_display_ir()
                ac_red = self.engine.get_current_display_red()
                self.display.draw_waveform_point(ac_ir, ac_red, self.engine.get_beat_count())
                
                # Log numerical data
                p = self.engine.get_ppg_params()
                cond = self.state_machine.selected_condition
                cond_name = CONDITION_NAMES[cond] if cond < len(CONDITION_NAMES) else "Unknown"
                raw_ir = self.engine.get_current_raw_ir()
                raw_red = self.engine.get_current_raw_red()
                self.csv_logger.log_data(raw_ir, raw_red, p.heart_rate, p.spo2, 
                                         p.resp_rate, p.perfusion_index, cond_name)

        # Metrics update (4 Hz)
        if now_ms - self._last_metrics >= METRICS_UPDATE_MS:
            self._last_metrics = now_ms

            if state in (STATE_SIMULATING, STATE_PAUSED):
                p = self.engine.get_ppg_params()
                cond = self.state_machine.selected_condition
                cond_name = CONDITION_NAMES[cond] if cond < len(CONDITION_NAMES) else "Unknown"
                self.display.update_metrics(p.heart_rate, p.perfusion_index,
                                            p.spo2, p.resp_rate, cond_name)
                
                # Sync UI sliders with current params (in case changed by BLE)
                if not any(s.is_dragging for s in self.display.sliders.values()):
                    self.display.update_sliders(p)

            elif state == STATE_SELECT_CONDITION:
                cond = self.state_machine.selected_condition
                cond_name = CONDITION_NAMES[cond] if cond < len(CONDITION_NAMES) else "Unknown"
                self.display.update_metrics(0, 0, 0, 0, cond_name)

    # ─── Helpers ───
    def _start_simulation(self, condition: int):
        """Start the PPG simulation."""
        log.info(f"[SIM] Starting PPG: {CONDITION_NAMES[condition]}")
        self.engine.start_simulation(condition)
        self.csv_logger.start()
        self.state_machine.selected_condition = condition
        self.state_machine.edit_mode = EDIT_CONDITION_SELECT
        self.display.clear_waveform()

    def _on_state_change(self, old_state, new_state):
        log.info(f"[STATE] {StateMachine.state_to_string(old_state)} → {StateMachine.state_to_string(new_state)}")

    def _shutdown(self):
        """Clean shutdown — save config, stop engine, cleanup GPIO."""
        log.info("Shutting down...")

        # Save current parameters
        try:
            p = self.engine.get_ppg_params()
            config = config_from_ppg_params(p)
            config["condition"] = self.state_machine.selected_condition
            config["edit_mode"] = self.state_machine.edit_mode
            save_config(config)
        except Exception as e:
            log.error(f"Failed to save config on exit: {e}")

        self.ble_server.stop()
        self.engine.stop_simulation()
        # self.buttons.cleanup()
        self.display.quit()
        log.info("Goodbye!")


def main():
    app = PPGSimulatorApp()
    app.run()


if __name__ == "__main__":
    main()
