"""
DEPRECATED: Mode button removed. Switching parameter control is now via UI or BLE.

button_handler.py — GPIO push button handler with software debounce.

Uses polling instead of edge detection to avoid the
"Failed to add edge detection" error on recent RPi kernels/Ubuntu.
The main loop calls was_mode_pressed() every frame (~60 Hz), which is
more than sufficient for responsive button input.

Falls back through: RPi.GPIO → lgpio → keyboard-only.
In dry-run mode, button presses are simulated via the UI (keyboard).
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BTN_MODE_PIN, BTN_DEBOUNCE_MS, DRY_RUN
from comm.logger import log


class ButtonHandler:
    """Handles the MODE push button with polling-based software debounce."""

    def __init__(self):
        self._mode_pressed = False
        self._last_mode_time = 0.0
        self._prev_pin_state = 1     # Active LOW: 1 = released, 0 = pressed
        self._gpio_backend = None    # 'rpigpio', 'lgpio', or None
        self._GPIO = None
        self._lgpio_handle = None

    def begin(self) -> bool:
        """Initialize GPIO pin for polling (no edge detection)."""
        if DRY_RUN:
            log.info("[ButtonHandler] DRY-RUN mode — keyboard input only")
            return True

        # Try RPi.GPIO first (polling mode only — no add_event_detect)
        try:
            import RPi.GPIO as GPIO
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(BTN_MODE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self._GPIO = GPIO
            self._gpio_backend = 'rpigpio'
            self._prev_pin_state = GPIO.input(BTN_MODE_PIN)
            log.info(f"[ButtonHandler] Initialized (RPi.GPIO polling): Mode=GPIO{BTN_MODE_PIN}")
            return True
        except Exception as e:
            log.warning(f"[ButtonHandler] RPi.GPIO failed: {e}, trying lgpio...")

        # Fallback: lgpio (modern GPIO library for RPi)
        try:
            import lgpio
            h = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_input(h, BTN_MODE_PIN, lgpio.SET_PULL_UP)
            self._lgpio_handle = h
            self._gpio_backend = 'lgpio'
            self._prev_pin_state = lgpio.gpio_read(h, BTN_MODE_PIN)
            log.info(f"[ButtonHandler] Initialized (lgpio polling): Mode=GPIO{BTN_MODE_PIN}")
            return True
        except Exception as e:
            log.warning(f"[ButtonHandler] lgpio failed: {e}")

        log.error("[ButtonHandler] No GPIO backend available — keyboard only")
        return False

    def _read_pin(self) -> int:
        """Read the current pin state (1 = released, 0 = pressed)."""
        try:
            if self._gpio_backend == 'rpigpio':
                return self._GPIO.input(BTN_MODE_PIN)
            elif self._gpio_backend == 'lgpio':
                import lgpio
                return lgpio.gpio_read(self._lgpio_handle, BTN_MODE_PIN)
        except Exception:
            pass
        return 1  # Default to "not pressed" on error

    def was_mode_pressed(self) -> bool:
        """Check and consume the mode button press event.

        Also polls the GPIO pin for a falling edge (1→0 transition)
        with debounce protection.
        """
        # Poll hardware GPIO if available
        if self._gpio_backend is not None:
            pin = self._read_pin()
            now = time.time() * 1000
            # Detect falling edge (released → pressed)
            if self._prev_pin_state == 1 and pin == 0:
                if now - self._last_mode_time > BTN_DEBOUNCE_MS:
                    self._mode_pressed = True
                    self._last_mode_time = now
                    log.debug("[ButtonHandler] MODE button pressed (GPIO poll)")
            self._prev_pin_state = pin

        # Check and consume
        if self._mode_pressed:
            self._mode_pressed = False
            return True
        return False

    def simulate_mode_press(self):
        """Simulate a mode button press (from keyboard/UI)."""
        self._mode_pressed = True
        log.debug("[ButtonHandler] MODE button simulated")

    def cleanup(self):
        """Clean up GPIO resources."""
        if DRY_RUN:
            return
        try:
            if self._gpio_backend == 'rpigpio' and self._GPIO:
                self._GPIO.cleanup(BTN_MODE_PIN)
            elif self._gpio_backend == 'lgpio' and self._lgpio_handle is not None:
                import lgpio
                lgpio.gpiochip_close(self._lgpio_handle)
        except Exception:
            pass
