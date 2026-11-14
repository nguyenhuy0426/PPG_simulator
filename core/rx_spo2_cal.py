"""SpO2 calibration of the receive path: SpO2 = A' - B' * R_received, fitted on this rig.

Why (docs/hardware-validation/2026-11-14-ir-overload §13): each LED -> OPT101 lane is linear with its own zero,
rx = g * (tx - x0), x0 ~ 256 mV IR and ~ 87 mV RED. AC/DC received is then AC / (DC - x0), so the received
ratio-of-ratios is a fixed fraction of the sent one (0.82 at DC 1000/1000 mV) and the generator's A, B read
SpO2 70 % as ~78 %. A pulse oximeter is calibrated the same way: its own R against reference SpO2 values.

The run plays the Classic waveform at POINTS SpO2 targets, reads R from the received IR/RED after SETTLE_S at
each, and fits A', B' by least squares. The fit holds for the DC levels it was made at (x0 / DC changes with
DC) and for the optics as they were; it is only applied while the DC levels match, and moving a carrier needs
a new run. This calibrates a loop-back check of this simulator, not a clinical SpO2 measurement.
"""
from dataclasses import asdict, dataclass
import math
import time

from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED
from core.rx_spo2 import estimate_rx_spo2

POINTS = (98.0, 90.0, 80.0, 70.0)   # SpO2 targets, R 0.48-1.6 with the default A 110 / B 25
SETTLE_S = 4.0                       # RED AC steps at once; leave the old R out of the window
MEASURE_S = 12.0                     # >= MIN_SECONDS and >= 8 beats at 40 bpm
MAX_RESIDUAL = 2.0                   # % SpO2; a worse straight line means the lanes are not stable/linear
DC_MATCH_MV = 20.0                   # the fit is applied only while each sent DC is this close to the fit's
CONFIG_KEY = "rx_spo2_calibration"


@dataclass(frozen=True)
class RxSpo2Calibration:
    a: float
    b: float
    dc_ir_mv: float            # sent DC (level + output offset) the fit was made at
    dc_red_mv: float
    max_residual: float        # % SpO2
    points: tuple              # ((target SpO2, received R), ...)
    created: float             # unix time

    def applies_to(self, dc_ir_mv, dc_red_mv):
        return abs(dc_ir_mv - self.dc_ir_mv) <= DC_MATCH_MV and abs(dc_red_mv - self.dc_red_mv) <= DC_MATCH_MV

    def to_dict(self):
        out = asdict(self)
        out["points"] = [list(p) for p in self.points]
        return out

    @classmethod
    def from_dict(cls, data):
        """None for anything that is not a complete, finite, B > 0 calibration."""
        try:
            values = {k: float(data[k]) for k in ("a", "b", "dc_ir_mv", "dc_red_mv", "max_residual", "created")}
            points = tuple((float(s), float(r)) for s, r in data["points"])
        except (KeyError, TypeError, ValueError):
            return None
        if not all(math.isfinite(v) for v in values.values()) or values["b"] <= 0 or len(points) < 2:
            return None
        return cls(points=points, **values)


def sent_dc(params):
    """DC each DAC really outputs: the channel level plus the common output offset."""
    offset = getattr(params, "output_dc_offset_mv", 0.0) or 0.0
    return params.dc_ir_mv + offset, params.dc_red_mv + offset


def fit(points):
    """Least squares SpO2 = a - b * R over ((spo2, R), ...); returns (a, b, max |residual|)."""
    n = len(points)
    if n < 2:
        raise ValueError("need at least two points")
    mean_r = sum(r for _, r in points) / n
    mean_s = sum(s for s, _ in points) / n
    sxx = sum((r - mean_r) ** 2 for _, r in points)
    if sxx <= 0:
        raise ValueError("received R did not change between the SpO2 points")
    slope = sum((r - mean_r) * (s - mean_s) for s, r in points) / sxx
    a, b = mean_s - slope * mean_r, -slope
    return a, b, max(abs(s - (a - b * r)) for s, r in points)


_cache = {"loaded": False, "value": None}


def current():
    """The saved calibration (read from config.json once)."""
    if not _cache["loaded"]:
        _cache["loaded"] = True
        try:
            from config_store import load_config
            raw = load_config().get(CONFIG_KEY)
        except Exception:
            raw = None
        _cache["value"] = RxSpo2Calibration.from_dict(raw) if isinstance(raw, dict) else None
    return _cache["value"]


def save(calibration):
    """Store in config.json; returns False when the file could not be written (the fit is still used)."""
    from config_store import load_config, save_config
    _cache.update(loaded=True, value=calibration)
    config = load_config()
    config[CONFIG_KEY] = calibration.to_dict()
    return save_config(config)


def coefficients_for(params):
    """(a, b, state) for reading the received R: state 'calibrated', 'other_dc' or 'none'."""
    cal = current()
    if cal is None:
        return params.spo2_coeff_a, params.spo2_coeff_b, "none"
    if not cal.applies_to(*sent_dc(params)):
        return params.spo2_coeff_a, params.spo2_coeff_b, "other_dc"
    return cal.a, cal.b, "calibrated"


class CalibrationRun:
    """Drives the engine through POINTS; call tick(now) from the UI loop until done is True.

    The Classic parameters are snapshotted at start and restored at the end (RED AC follows SpO2 during the run,
    a manual RED AC would hold R fixed)."""

    def __init__(self, engine, receiver, points=POINTS, settle_s=SETTLE_S, measure_s=MEASURE_S):
        self.engine, self.receiver = engine, receiver
        self.points, self.settle_s, self.measure_s = tuple(points), settle_s, measure_s
        self.index, self.results = 0, []
        self.done, self.error, self.calibration = False, None, None
        self._snapshot = self._step_at = None

    @property
    def step_s(self):
        return self.settle_s + self.measure_s

    def remaining_s(self, now):
        if self.done or self._step_at is None:
            return 0.0
        return max(0.0, (len(self.points) - self.index) * self.step_s - (now - self._step_at))

    def start(self, now):
        self._snapshot = self.engine.get_ppg_params().copy()
        self.engine.update_spo2_target(self.points[0])
        self.engine.start_simulation(self._snapshot.condition)
        self._step_at = now

    def tick(self, now):
        if self.done or now - self._step_at < self.step_s:
            return
        since = self._step_at + self.settle_s
        ir = self.receiver.get_samples_since(ADC_CHANNEL_IR, since)
        red = self.receiver.get_samples_since(ADC_CHANNEL_RED, since)
        result = estimate_rx_spo2(ir, red, self._snapshot.spo2_coeff_a, self._snapshot.spo2_coeff_b)
        if result.ratio is None:
            self._finish(f"reason:{result.reason}")
            return
        self.results.append((self.points[self.index], result.ratio))
        self.index += 1
        if self.index < len(self.points):
            self.engine.update_spo2_target(self.points[self.index])
            self._step_at = now
            return
        try:
            a, b, residual = fit(self.results)
        except ValueError as exc:
            self._finish(str(exc))
            return
        if b <= 0:
            self._finish("received R does not fall as SpO2 rises")
            return
        if residual > MAX_RESIDUAL:
            self._finish(f"residual:{residual:.1f}")
            return
        self.calibration = RxSpo2Calibration(a, b, *sent_dc(self._snapshot), residual, tuple(self.results),
                                             time.time())
        self._finish(None)

    def abort(self):
        if not self.done:
            self._finish("aborted")

    def _finish(self, error):
        self.done, self.error = True, error
        self.engine.stop_simulation()
        if self._snapshot is not None:
            self.engine.load_parameters(self._snapshot)
