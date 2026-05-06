"""
button_handler.py — GPIO push button handler with debounce.

Port of button_handler.cpp. Uses RPi.GPIO with event detection.
In dry-run mode, button presses are simulated via the UI (keyboard).
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BTN_MODE_PIN, BTN_DEBOUNCE_MS, DRY_RUN
from comm.logger import log


class ButtonHandler:
    """Handles the MODE push button with software debounce."""

    def __init__(self):
        self._mode_pressed = False
        self._last_mode_time = 0.0

    def begin(self) -> bool:
        """Initialize GPIO pin and attach event detection."""
        if DRY_RUN:
            log.info("[ButtonHandler] DRY-RUN mode — keyboard input only")
            return True

        try:
            import RPi.GPIO as GPIO
            self._GPIO = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(BTN_MODE_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(
                BTN_MODE_PIN, GPIO.FALLING,
                callback=self._isr_mode,
                bouncetime=BTN_DEBOUNCE_MS
            )
            log.info(f"[ButtonHandler] Initialized: Mode=GPIO{BTN_MODE_PIN}")
            return True
        except Exception as e:
            log.error(f"[ButtonHandler] Failed to initialize GPIO: {e}")
            return False

    def _isr_mode(self, channel):
        """ISR callback for the MODE button (GPIO falling edge)."""
        now = time.time() * 1000
        if now - self._last_mode_time > BTN_DEBOUNCE_MS:
            self._mode_pressed = True
            self._last_mode_time = now
            log.debug("[ButtonHandler] MODE button pressed (GPIO)")

    def was_mode_pressed(self) -> bool:
        """Check and consume the mode button press event."""
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
        if not DRY_RUN:
            try:
                import RPi.GPIO as GPIO
                GPIO.cleanup(BTN_MODE_PIN)
            except Exception:
                pass
