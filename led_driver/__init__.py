"""
led_driver — pure theoretical calculations for the PPG TX LED driver.

This package contains NO hardware access of any kind. It imports only the
Python standard library: no GPIO, no I2C, no SMBus, no Blinka, no grove.py.
Everything here is arithmetic over a *design hypothesis*, so that the numbers
in docs/superpowers/ppg_design_audit/03_LED_DRIVER_ARCHITECTURE.md are
produced by executable code instead of by hand.

Evidence labels used throughout this package follow the project convention:

    [VERIFIED-USER]        stated by the user as the authoritative configuration
    [VERIFIED-DATASHEET]   read from a datasheet present in this repository
    [ENGINEERING-INFERENCE] derived by calculation from the above
    [MEASUREMENT-REQUIRED] cannot be settled without bench measurement
    [UNKNOWN]              no reliable grounding available

NOTHING in this package is hardware-verified. Running these tests on a laptop
proves the arithmetic, not the circuit.
"""

from led_driver import (  # noqa: F401
    classification,
    compliance,
    dac,
    error_budget,
    faults,
    filters,
    params,
    power,
    startup,
)

__all__ = ["classification", "compliance", "dac", "error_budget", "faults",
           "filters", "params", "power", "startup"]
