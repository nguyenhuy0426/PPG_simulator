"""
Input RC filter option analysis (Stage 1, C1 selection space).

Stdlib only. No hardware access.

C1 sits from the divider midpoint to ground, so the resistance it sees is
the divider Thevenin resistance, 10k || 10k = 5 kohm. Options under
evaluation: DNP (None), 10 nF, 100 nF, 220 nF. Everything here is a
first-order RC calculation of the option space, NOT a selection - per the
task instruction the input filter must not be finalised from theory alone.
"""

import math
from dataclasses import dataclass
from typing import List, Optional

from led_driver.params import DividerSpec

# Source resistance the capacitor sees (divider Thevenin resistance).
R_SOURCE_OHM = DividerSpec().thevenin_ohm

SELECTION_STATUS = (
    "MEASUREMENT-REQUIRED - the C1 choice trades 1 kHz step attenuation "
    "against settling and channel matching. The final value is selected on "
    "the bench with a scope on TP_CMD_IR / TP_CMD_RED, not from this table.")


def cutoff_hz(c_farad: Optional[float]) -> float:
    """-3 dB corner of the RC low-pass. DNP (None) has no corner."""
    if c_farad is None:
        return math.inf
    if c_farad <= 0:
        raise ValueError(f"c_farad must be positive or None (DNP), got {c_farad}")
    return 1.0 / (2.0 * math.pi * R_SOURCE_OHM * c_farad)


def magnitude_at(f_hz: float, c_farad: Optional[float]) -> float:
    """First-order low-pass magnitude response at f_hz."""
    if f_hz < 0:
        raise ValueError(f"f_hz must not be negative, got {f_hz}")
    if c_farad is None:
        return 1.0
    fc = cutoff_hz(c_farad)
    return 1.0 / math.sqrt(1.0 + (f_hz / fc) ** 2)


def settle_5tau_s(c_farad: Optional[float]) -> float:
    """Time to settle within ~0.7 % of a step (5 time constants)."""
    if c_farad is None:
        return 0.0
    if c_farad <= 0:
        raise ValueError(f"c_farad must be positive or None (DNP), got {c_farad}")
    return 5.0 * R_SOURCE_OHM * c_farad


def channel_gain_mismatch(c_farad: Optional[float], tol_frac: float,
                          f_hz: float) -> float:
    """Worst-case magnitude difference between the two channels at f_hz when
    their capacitors sit at opposite ends of the tolerance band. The two
    channels must be fitted with the same option and tolerance grade."""
    if c_farad is None:
        return 0.0
    lo = magnitude_at(f_hz, c_farad * (1.0 + tol_frac))
    hi = magnitude_at(f_hz, c_farad * (1.0 - tol_frac))
    return abs(hi - lo)


@dataclass(frozen=True)
class FilterOption:
    c_farad: Optional[float]
    label: str
    cutoff_hz: float
    magnitude_1khz: float
    magnitude_100hz: float
    magnitude_10hz: float
    settle_5tau_s: float


_OPTION_VALUES = ((None, "DNP"), (10e-9, "10 nF"),
                  (100e-9, "100 nF"), (220e-9, "220 nF"))


def option_table() -> List[FilterOption]:
    """The four permitted C1 options with their first-order figures."""
    return [
        FilterOption(
            c_farad=c,
            label=label,
            cutoff_hz=cutoff_hz(c),
            magnitude_1khz=magnitude_at(1000.0, c),
            magnitude_100hz=magnitude_at(100.0, c),
            magnitude_10hz=magnitude_at(10.0, c),
            settle_5tau_s=settle_5tau_s(c),
        )
        for c, label in _OPTION_VALUES
    ]
