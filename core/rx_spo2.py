"""SpO2 estimate from the received IR and RED waveforms for display (pure Python; the Pi runtime has no numpy).

Both channels are put on one time grid over their common gap-free stretch. AC is the RMS of the band-passed
signal and DC the mean above the dark level, giving R = (AC_red/DC_red)/(AC_ir/DC_ir), which goes through the
same linear calibration SpO2 = A - B*R as the generator. A strip where the two channels do not show the same
pulse gets no value rather than a guess.

This checks the optical loop and is not a clinical SpO2. A and B describe the generator, not this LED/OPT101
path, and neither is calibrated against it: the OPT101 output is not proportional to the LED drive (IR stays
dark below about DAC code 550), so a difference from the TX setpoint can be the path and not an error in R.
Dual mode has no live dark level (0 is used; measured with the LEDs off: A0 16 mV, A4 4 mV).
"""
from dataclasses import dataclass
import math

from core.rx_heart_rate import (DETREND_S, GRID_HZ, MAX_SATURATED, MIN_SECONDS, MIN_SWING_CODES, _percentile,
                                band_pass, latest_stretch)

MIN_CORRELATION = 0.8      # band-passed IR against RED; below this they are not one pulse
MIN_DC_CODES = 12          # about 10 mV above dark; below this the AC/DC ratio has no meaning


@dataclass(frozen=True)
class RxSpo2:
    spo2: float | None
    ratio: float | None     # R; kept when the calibrated value falls outside 0-100 %
    reason: str             # "ok", "short", "saturated", "weak", "mismatch", "no_dc", "out_of_range"
    seconds: float          # length of the common stretch that was analysed


def _on_grid(samples, start, count, hz):
    """Raw codes linearly interpolated at start + i/hz; samples must span that range."""
    out, j = [], 0
    for i in range(count):
        t = start+i/hz
        while samples[j+1].timestamp < t:
            j += 1
        a, b = samples[j], samples[j+1]
        w = 0. if b.timestamp == a.timestamp else (t-a.timestamp)/(b.timestamp-a.timestamp)
        out.append(a.raw+w*(b.raw-a.raw))
    return out


def _correlation(a, b):
    mean_a, mean_b = sum(a)/len(a), sum(b)/len(b)
    aa = sum((v-mean_a)**2 for v in a)
    bb = sum((v-mean_b)**2 for v in b)
    if aa <= 0 or bb <= 0:
        return 0.
    return sum((x-mean_a)*(y-mean_b) for x, y in zip(a, b))/math.sqrt(aa*bb)


def _rms(x):
    mean = sum(x)/len(x)
    return math.sqrt(sum((v-mean)**2 for v in x)/len(x))


def _swing(x):
    ordered = sorted(x)
    return _percentile(ordered, .95)-_percentile(ordered, .05)


def estimate_rx_spo2(ir_samples, red_samples, coeff_a, coeff_b, ir_dark=0., red_dark=0., hz=GRID_HZ):
    """RxSpo2 for two RX sample streams (objects with .timestamp, .raw, .saturated), oldest first.

    ir_dark and red_dark are 12-bit codes subtracted from DC.
    """
    ir, red = latest_stretch(ir_samples), latest_stretch(red_samples)
    if len(ir) < 2 or len(red) < 2:
        return RxSpo2(None, None, "short", 0.)
    start = max(ir[0].timestamp, red[0].timestamp)
    seconds = min(ir[-1].timestamp, red[-1].timestamp)-start
    if seconds < MIN_SECONDS:
        return RxSpo2(None, None, "short", max(0., seconds))
    for stretch in (ir, red):
        inside = [s for s in stretch if start <= s.timestamp <= start+seconds]
        if sum(s.saturated for s in inside) > MAX_SATURATED*len(inside):
            return RxSpo2(None, None, "saturated", seconds)
    count = int(seconds*hz)
    ir_raw, red_raw = _on_grid(ir, start, count, hz), _on_grid(red, start, count, hz)
    dc_ir, dc_red = sum(ir_raw)/count-ir_dark, sum(red_raw)/count-red_dark
    if dc_ir < MIN_DC_CODES or dc_red < MIN_DC_CODES:
        return RxSpo2(None, None, "no_dc", seconds)
    # Edges of a moving-average filter are biased; drop one detrend half-window at each end.
    edge = round(DETREND_S*hz/2)
    ac_ir = band_pass(ir_raw, hz)[edge:count-edge]
    ac_red = band_pass(red_raw, hz)[edge:count-edge]
    if _swing(ac_ir) < MIN_SWING_CODES or _swing(ac_red) < MIN_SWING_CODES:
        return RxSpo2(None, None, "weak", seconds)
    if _correlation(ac_ir, ac_red) < MIN_CORRELATION:
        return RxSpo2(None, None, "mismatch", seconds)
    ratio = (_rms(ac_red)/dc_red)/(_rms(ac_ir)/dc_ir)
    spo2 = coeff_a-coeff_b*ratio
    if not 0. <= spo2 <= 100.:
        return RxSpo2(None, ratio, "out_of_range", seconds)
    return RxSpo2(spo2, ratio, "ok", seconds)
