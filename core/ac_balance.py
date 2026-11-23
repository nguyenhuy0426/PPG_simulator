"""AC balance: drive the DACs so the AC the OPT101 receives equals the AC set on the Classic page.

Each LED -> OPT101 path has its own small-signal gain, and on this rig the IR one grows with the DC level: the
DC sweep of 2026-11-21 (45 mV AC set, DC 300-1500 mV, docs/hardware-validation/2026-11-21-dc-sweep-ac) read
RX/TX AC 1.28-2.08 on IR and 1.12-1.25 on RED. Two stages bring the received AC back to the set AC:

1. Feedforward. AC written to the DAC = set AC / g(DC), g the measured gain at the sent DC (table below,
   3-point smoothed, linear between points, held flat past the ends). Instant, but only as good as the table.
2. Closed-loop trim. Every UPDATE_S the per-beat AC of TX (the set waveform) and RX are measured the same way
   as core/rx_spo2 (median peak-to-trough per beat, straight line through each beat's ends removed), and a
   per-channel trim moves the DAC AC by ratio**-ALPHA, at most MAX_STEP per update, within TRIM_RANGE. It
   corrects what the table misses (temperature, LED ageing, a moved carrier) and is skipped whenever the
   window is not trustworthy: output not running Classic, a change less than SETTLE_S ago, RX gaps, OPT101
   saturation, too few beats, or beat-to-beat spread too large.

Only the AC part of the Classic generator is scaled (core/signal_engine applies it); the DC, the TX plot (the
set waveform), Calibration-page test signals and played clips are untouched. This equalises the AC at this
simulator's own receiver. It is not a calibration of any other receiver or a clinical measurement.
"""
from dataclasses import dataclass
import math
import threading
import time

from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED, MODEL_SAMPLE_RATE_PPG, OPT101_SATURATION_MV
from core.rx_heart_rate import DETREND_S, _moving_average, _percentile, band_pass, latest_stretch, pulse_peaks
from core.rx_spo2 import SWING_SMOOTH, _beat_swing, _swing
from hw.opt101_rx import raw_to_millivolts

CONFIG_ENABLED = "ac_balance_enabled"
CONFIG_TABLE = "ac_gain_table"
CHANNELS = ("IR", "RED")

# RX AC / TX AC per sent DC (mV), measured on the Pi 4 rig 2026-11-21 (12 beats per step, HR 75, AC 45 mV set).
MEASURED_GAIN = {
    "IR": ((300, 1.28), (350, 1.48), (400, 1.47), (450, 1.53), (500, 1.57), (550, 1.63), (600, 1.66),
           (650, 1.73), (700, 1.72), (750, 1.80), (800, 1.81), (850, 1.82), (900, 1.86), (950, 1.87),
           (1000, 1.94), (1050, 1.89), (1100, 1.90), (1150, 1.89), (1200, 1.99), (1250, 1.95), (1300, 2.05),
           (1350, 1.98), (1400, 2.05), (1450, 2.02), (1500, 2.08)),
    "RED": ((300, 1.12), (350, 1.19), (400, 1.16), (450, 1.18), (500, 1.18), (550, 1.19), (600, 1.20),
            (650, 1.20), (700, 1.21), (750, 1.23), (800, 1.20), (850, 1.22), (900, 1.22), (950, 1.24),
            (1000, 1.24), (1050, 1.23), (1100, 1.22), (1150, 1.20), (1200, 1.25), (1250, 1.22), (1300, 1.23),
            (1350, 1.23), (1400, 1.22), (1450, 1.21), (1500, 1.23)),
}
GAIN_RANGE = (0.2, 5.0)        # a table value outside this is a broken table, not a gain of this rig

UPDATE_S = 10.0                # one trim update per 10 s (~12 beats at 75 bpm in the window)
WINDOW_S = 8.0                 # >= 6 beats at 45 bpm
SETTLE_S = 2.0                 # after a change: OPT101/ADC response and the DAC buffer (~0.1 s) with margin
ALPHA = 0.5                    # half the log error per update: converges in ~4 updates, does not chase noise
MAX_STEP = 1.15                # trim factor change per update, either way
TRIM_RANGE = (0.6, 1.6)        # beyond this the table is wrong for the rig: remeasure rather than trim
DEADBAND = 0.02                # |RX/TX - 1| below this is left alone (per-beat noise is ~2-5 %)
MIN_BEATS = 5
MIN_TX_AC_MV = 5.0
MAX_SPREAD = 0.25              # RX per-beat IQR / median above this: not a steady pulse
RX_MAX_GAP_S = 0.15            # the Pi RX has 50-110 ms holes under GUI load; a longer one breaks the window


def smoothed(points):
    """3-point moving average of (dc, gain) points sorted by dc (the measured gains scatter by 2-5 %)."""
    points = sorted(points)
    out = []
    for i, (dc, _g) in enumerate(points):
        near = points[max(0, i - 1):i + 2]
        out.append((dc, sum(g for _d, g in near) / len(near)))
    return tuple(out)


def parse_table(raw):
    """{'IR': [[dc, gain], ...], 'RED': [...]} from config.json, or None when anything is missing or invalid."""
    if not isinstance(raw, dict):
        return None
    table = {}
    for name in CHANNELS:
        try:
            points = tuple((float(dc), float(g)) for dc, g in raw[name])
        except (KeyError, TypeError, ValueError):
            return None
        if len(points) < 2 or not all(math.isfinite(dc) and math.isfinite(g) and GAIN_RANGE[0] <= g <= GAIN_RANGE[1]
                                      for dc, g in points):
            return None
        table[name] = points
    return table


def gain_at(points, dc_mv):
    """Linear interpolation of the (dc, gain) points, flat past either end."""
    if dc_mv <= points[0][0]:
        return points[0][1]
    for (d0, g0), (d1, g1) in zip(points, points[1:]):
        if dc_mv <= d1:
            return g0 + (g1 - g0) * (dc_mv - d0) / (d1 - d0)
    return points[-1][1]


def beat_ac(values, hz=MODEL_SAMPLE_RATE_PPG):
    """(median AC, IQR, beats) of a uniformly sampled pulse in mV: per beat peak-to-trough, each beat from one
    pulse peak to the next with the straight line through its ends removed (core/rx_spo2's AC definition)."""
    edge = round(DETREND_S * hz / 2)
    if len(values) < 2 * edge + 3 * hz:
        return None, None, 0
    bp = band_pass(values, hz)
    core = bp[edge:len(bp) - edge]
    peaks = [p + edge for p in pulse_peaks(core, hz, _swing(core))]
    smooth = _moving_average(values, SWING_SMOOTH)
    swings = sorted(_beat_swing(smooth[a:b + 1]) for a, b in zip(peaks, peaks[1:]) if b - a >= 2)
    if not swings:
        return None, None, 0
    return _percentile(swings, .5), _percentile(swings, .75) - _percentile(swings, .25), len(swings)


def received_mv(samples, start, end, hz=MODEL_SAMPLE_RATE_PPG):
    """RX samples in [start, end] on a uniform grid (mV), or (None, reason)."""
    stretch = latest_stretch([s for s in samples if start <= s.timestamp <= end], RX_MAX_GAP_S)
    if len(stretch) < 2 or stretch[-1].timestamp - stretch[0].timestamp < (end - start) * 0.9:
        return None, "gaps"
    if any(s.saturated or raw_to_millivolts(s.raw) >= OPT101_SATURATION_MV for s in stretch):
        return None, "saturated"
    t0, n = stretch[0].timestamp, int((stretch[-1].timestamp - stretch[0].timestamp) * hz)
    out, j = [], 0
    for i in range(n):
        t = t0 + i / hz
        while stretch[j + 1].timestamp < t:
            j += 1
        a, b = stretch[j], stretch[j + 1]
        w = 0.0 if b.timestamp == a.timestamp else (t - a.timestamp) / (b.timestamp - a.timestamp)
        out.append(raw_to_millivolts(a.raw) + w * (raw_to_millivolts(b.raw) - raw_to_millivolts(a.raw)))
    return out, "ok"


@dataclass(frozen=True)
class ChannelState:
    feedforward: float = 1.0   # 1 / g(DC)
    trim: float = 1.0
    ratio: float = None        # last measured RX AC / TX AC
    tx_ac: float = None
    rx_ac: float = None
    reason: str = "waiting"    # last loop outcome: ok, held, waiting, gaps, saturated, weak, spread, ...

    @property
    def factor(self):
        return self.feedforward * self.trim


def measure(tx_rows, rx_samples, start, end):
    """{channel: (tx_ac, rx_ac, reason)} for one window; tx_rows (t, ir_mV, red_mV) at the model rate."""
    out = {}
    for k, name in ((1, "IR"), (2, "RED")):
        tx_ac, _iqr, tx_beats = beat_ac([row[k] for row in tx_rows])
        values, reason = received_mv(rx_samples[name], start, end)
        if values is None:
            out[name] = (tx_ac, None, reason)
            continue
        rx_ac, iqr, beats = beat_ac(values)
        if tx_ac is None or rx_ac is None or min(tx_beats, beats) < MIN_BEATS or tx_ac < MIN_TX_AC_MV:
            out[name] = (tx_ac, rx_ac, "weak")
        elif iqr > MAX_SPREAD * rx_ac:
            out[name] = (tx_ac, rx_ac, "spread")
        else:
            out[name] = (tx_ac, rx_ac, "ok")
    return out


def next_trim(trim, ratio):
    """The trim after one update for a measured RX/TX ratio (1 = balanced)."""
    if abs(ratio - 1.0) < DEADBAND:
        return trim
    step = min(MAX_STEP, max(1.0 / MAX_STEP, ratio ** -ALPHA))
    return min(TRIM_RANGE[1], max(TRIM_RANGE[0], trim * step))


class AcBalance:
    """Owned by the app and ticked from the Tk loop; the measurement runs on a worker thread."""

    def __init__(self, engine, receiver, enabled=True, table=None, hold=lambda: False, loop=True):
        self.engine, self.receiver, self.hold, self.loop = engine, receiver, hold, loop
        self.enabled = bool(enabled)
        self.table = {name: smoothed(points) for name, points in (table or MEASURED_GAIN).items()}
        self.state = {name: ChannelState() for name in CHANNELS}
        self._key = None
        self._changed_at = 0.0
        self._next_at = 0.0
        self._job = None
        self._result = None

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.state = {name: ChannelState() for name in CHANNELS}
        self._key = None
        self._apply()

    def feedforward(self, params):
        offset = getattr(params, "output_dc_offset_mv", 0.0) or 0.0
        return {"IR": 1.0 / gain_at(self.table["IR"], params.dc_ir_mv + offset),
                "RED": 1.0 / gain_at(self.table["RED"], params.dc_red_mv + offset)}

    def _apply(self):
        if self.enabled:
            self.engine.set_ac_compensation(self.state["IR"].factor, self.state["RED"].factor)
        else:
            self.engine.set_ac_compensation(1.0, 1.0)

    def classic_running(self):
        e = self.engine
        return e.is_running and not e.is_calibrating and not e.is_waveform_playing

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.enabled:
            return
        p = self.engine.get_ppg_params()
        ff = self.feedforward(p)
        for name in CHANNELS:
            if abs(self.state[name].feedforward - ff[name]) > 1e-9:
                self.state[name] = ChannelState(ff[name], self.state[name].trim, reason="waiting")
        key = (self.classic_running(), round(ff["IR"], 4), round(ff["RED"], 4), p.dc_ir_mv, p.dc_red_mv,
               p.ac_ir_mv, p.ac_red_mv, p.heart_rate, p.spo2, p.condition, p.perfusion_index,
               round(self.state["IR"].trim, 4), round(self.state["RED"].trim, 4))
        if key != self._key:
            self._key, self._changed_at = key, now
            self._next_at = max(self._next_at, now + SETTLE_S + WINDOW_S)
            self._result = None          # a window that straddles the change is dropped
        self._apply()
        if self._result is not None:
            result, self._result = self._result, None
            self._take(result)
        job = self._job
        if not self.loop or now < self._next_at or (job and job.is_alive()):
            return
        self._next_at = now + UPDATE_S
        if not self.classic_running() or self.hold():
            for name in CHANNELS:
                self.state[name] = _with(self.state[name], reason="held")
            return
        start, end = max(self._changed_at + SETTLE_S, now - WINDOW_S), now
        tx_rows = self.engine.get_display_history()[-int(WINDOW_S * MODEL_SAMPLE_RATE_PPG):]
        tx_rows = [(t, ir * 1000.0, red * 1000.0) for t, ir, red in tx_rows]
        rx = {"IR": self.receiver.get_samples_since(ADC_CHANNEL_IR, start),
              "RED": self.receiver.get_samples_since(ADC_CHANNEL_RED, start)}
        key_at_start = self._key

        def work():
            self._result = (key_at_start, measure(tx_rows, rx, start, end))
        self._job = threading.Thread(target=work, daemon=True, name="AcBalance")
        self._job.start()

    def _take(self, result):
        key, measured = result
        if key != self._key:
            return
        for name, (tx_ac, rx_ac, reason) in measured.items():
            s = self.state[name]
            if reason != "ok":
                self.state[name] = _with(s, tx_ac=tx_ac, rx_ac=rx_ac, reason=reason)
                continue
            ratio = rx_ac / tx_ac
            self.state[name] = ChannelState(s.feedforward, next_trim(s.trim, ratio), ratio, tx_ac, rx_ac, "ok")
        self._apply()


def _with(state, **changes):
    values = {k: getattr(state, k) for k in ("feedforward", "trim", "ratio", "tx_ac", "rx_ac", "reason")}
    values.update(changes)
    return ChannelState(**values)


def from_config(engine, receiver, hold=lambda: False):
    """An AcBalance with the saved on/off choice (default on) and the saved gain table, if a valid one exists."""
    try:
        from config_store import load_config
        config = load_config()
    except Exception:
        config = {}
    return AcBalance(engine, receiver, enabled=config.get(CONFIG_ENABLED, True),
                     table=parse_table(config.get(CONFIG_TABLE)), hold=hold)
