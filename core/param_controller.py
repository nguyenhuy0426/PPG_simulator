"""
param_controller.py — PPG parameter controller with validation and clamping.

Port of param_controller.cpp.
"""

from models.ppg_model import PPGParameters, get_ppg_limits, _clamp


class ParamController:
    """Manages PPG parameter updates with condition-specific limits."""

    def __init__(self):
        self.current = PPGParameters()
        self._pending = None
        self._has_pending = False

    def set_condition(self, condition: int):
        pending = self.current.copy()
        pending.condition = condition
        lim = get_ppg_limits(condition)
        pending.heart_rate = _clamp(pending.heart_rate, lim.heart_rate.min, lim.heart_rate.max)
        pending.perfusion_index = _clamp(pending.perfusion_index, lim.perfusion_index.min, lim.perfusion_index.max)
        pending.dicrotic_notch = _clamp(pending.dicrotic_notch, lim.dicrotic_notch.min, lim.dicrotic_notch.max)
        self._pending = pending
        self._has_pending = True

    def set_noise_level(self, noise: float):
        self.current.noise_level = _clamp(noise, 0.0, 0.10)

    def set_heart_rate(self, hr: float):
        lim = get_ppg_limits(self.current.condition)
        p = self.current.copy()
        p.heart_rate = _clamp(hr, lim.heart_rate.min, lim.heart_rate.max)
        self._pending = p; self._has_pending = True

    def set_perfusion_index(self, pi: float):
        lim = get_ppg_limits(self.current.condition)
        p = self.current.copy()
        p.perfusion_index = _clamp(pi, lim.perfusion_index.min, lim.perfusion_index.max)
        self._pending = p; self._has_pending = True

    def set_spo2(self, spo2: float):
        lim = get_ppg_limits(self.current.condition)
        p = self.current.copy()
        p.spo2 = _clamp(spo2, lim.spo2.min, lim.spo2.max)
        self._pending = p; self._has_pending = True

    def set_resp_rate(self, rr: float):
        lim = get_ppg_limits(self.current.condition)
        p = self.current.copy()
        p.resp_rate = _clamp(rr, lim.resp_rate.min, lim.resp_rate.max)
        self._pending = p; self._has_pending = True

    def apply_pending(self) -> bool:
        if self._has_pending and self._pending:
            self.current = self._pending
            self._has_pending = False
            return True
        return False

    def has_pending(self) -> bool:
        return self._has_pending

    def get_limits(self):
        return get_ppg_limits(self.current.condition)

    def validate(self, params: PPGParameters) -> bool:
        lim = get_ppg_limits(params.condition)
        if not (lim.heart_rate.min <= params.heart_rate <= lim.heart_rate.max): return False
        if not (0 <= params.noise_level <= 0.10): return False
        if not (lim.perfusion_index.min <= params.perfusion_index <= lim.perfusion_index.max): return False
        if not (lim.spo2.min <= params.spo2 <= lim.spo2.max): return False
        if not (lim.resp_rate.min <= params.resp_rate <= lim.resp_rate.max): return False
        return True

    def reset_to_defaults(self):
        self.current = PPGParameters()
        self._has_pending = False
