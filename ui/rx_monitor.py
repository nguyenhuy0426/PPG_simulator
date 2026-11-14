"""Shared read-only view of the existing receiver; never starts ADC or DAC IO."""
import time

from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED, OPT101_SATURATION_MV
from core.rx_heart_rate import estimate_rx_rate
from core.rx_filter import StreamFilter
from core.rx_resp_rate import WINDOW_S as RR_WINDOW_S, estimate_rx_rr
from core.rx_spo2 import estimate_rx_spo2
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
from ui import theme as T
from ui.trace_view import Lane, LaneView

RX_CHANNELS = ((ADC_CHANNEL_IR, "IR", T.IR), (ADC_CHANNEL_RED, "RED", T.RED))
REFRESH_S = 0.1
MV_PER_CODE = raw_to_millivolts(1)   # the conversion is linear: one multiply per sample instead of a call
DEFAULT_MAX_GAP_S = 0.05
RATE_REFRESH_S = 2.0   # rate and SpO2 recomputed at most every 2 s: ~3 ms per channel on the laptop, far more on the Pi, and the value moves slowly
RR_MAX_GAP_S = 0.25    # Pi RX has 50-110 ms holes under GUI load; harmless for 4-40 breaths/min, fatal for a 30 s gap-free rule at 50 ms
RR_REFRESH_S = 5.0     # RR looks at 30-60 s and costs ~80 ms on the Pi: refresh it less often

# Received pulse rate shown in each live lane header: (label, reasons there is none).
_RATE = {
    "vi": ("Nhịp RX", {"short": "cần ≥ 5 s liên tục", "saturated": "chạm trần ADC", "weak": "tín hiệu yếu",
                       "unclear": "không rõ nhịp đều"}),
    "en": ("RX rate", {"short": "needs ≥ 5 s gap-free", "saturated": "ADC clipping", "weak": "weak signal",
                       "unclear": "no clear regular rhythm"}),
}

# Estimated SpO2 shown under the rate of the RED lane: (label, reasons there is none).
_SPO2_CAL = {   # which A, B read the received R (core.rx_spo2_cal)
    "vi": {"calibrated": " (đã hiệu chuẩn)", "other_dc": " (chưa hiệu chuẩn ở DC này)", "none": " (chưa hiệu chuẩn)"},
    "en": {"calibrated": " (calibrated)", "other_dc": " (not calibrated at this DC)", "none": " (uncalibrated)"},
}
_SPO2 = {
    "vi": ("SpO₂ RX ước tính", {"short": "cần ≥ 5 s cả hai kênh", "saturated": "chạm trần ADC", "weak": "tín hiệu yếu",
                                "mismatch": "IR và RED không cùng nhịp", "no_dc": "không có mức DC",
                                "out_of_range": "ngoài thang"}),
    "en": ("Estimated RX SpO₂", {"short": "needs ≥ 5 s on both", "saturated": "ADC clipping", "weak": "weak signal",
                                 "mismatch": "IR and RED pulses differ", "no_dc": "no DC level",
                                 "out_of_range": "out of scale"}),
}

# Estimated respiratory rate shown under the rate of the IR lane: (label, reasons there is none).
_RR = {
    "vi": ("Nhịp thở RX", {"short": "cần ≥ 30 s liên tục", "saturated": "chạm trần ADC", "weak": "tín hiệu yếu",
                           "dark": "có mẫu 0 mV trong 60 s (LED tắt / rớt tín hiệu)", "unclear": "chưa rõ điều biến thở", "mismatch": "các điều biến không khớp",
                           "stale": "dữ liệu cũ", "invalid": "mẫu lỗi"}),
    "en": ("RX resp", {"short": "needs ≥ 30 s gap-free", "saturated": "ADC clipping", "weak": "weak signal", "dark": "0 mV samples in 60 s (LED off / dropout)",
                       "unclear": "no clear breathing modulation", "mismatch": "modulations disagree",
                       "stale": "stale data", "invalid": "invalid samples"}),
}

# Short lane-header state plus the centred explanation shown in an empty lane.
_PANEL = {
    "vi": {
        "disabled": ("Tắt", "Chưa gắn cảm biến", "Kênh tắt cho tới khi gắn cảm biến {name}"),
        "dry-run": ("Mô phỏng", "Không có dữ liệu ADC thật", "Chế độ dry-run không đọc Grove 0x08"),
        "init": ("Đang chờ", "Đang chờ mẫu ADC đầu tiên", ""),
        "stale": ("Dữ liệu cũ", "Không có mẫu mới", "Mẫu cuối quá 0.5 s"),
        "error": ("Lỗi", "Lỗi đọc ADC", "Kiểm tra Grove Base Hat 0x08 và cáp"),
        "invalid": ("Lỗi", "Mẫu ADC không hợp lệ", ""),
        "disconnected": ("Mất kết nối", "Mất kết nối ADC", "Kiểm tra Grove Base Hat 0x08 và cáp"),
        "opt101_sat": "OPT101 bão hòa (~2.5 V)", "filtered": "đã lọc",
        "ok": ("Trực tiếp", "", ""), "saturated": ("Chạm trần ADC", "", ""),
    },
    "en": {
        "disabled": ("Off", "No sensor installed", "Channel stays off until the {name} sensor is fitted"),
        "dry-run": ("Simulated", "No physical ADC data", "Dry-run mode does not read Grove 0x08"),
        "init": ("Waiting", "Waiting for the first ADC sample", ""),
        "stale": ("Stale", "No fresh samples", "Last sample is older than 0.5 s"),
        "error": ("Error", "ADC read error", "Check the Grove Base Hat 0x08 and cable"),
        "invalid": ("Error", "Invalid ADC sample", ""),
        "disconnected": ("Disconnected", "ADC disconnected", "Check the Grove Base Hat 0x08 and cable"),
        "opt101_sat": "OPT101 saturated (~2.5 V)", "filtered": "filtered",
        "ok": ("Live", "", ""), "saturated": ("ADC full scale", "", ""),
    },
}


def channel_view(receiver, channel, now, window_s):
    """Status and the in-window samples of one channel, as (status, samples).

    Disabled channels and dry-run never return samples: nothing is fabricated.
    """
    status = receiver.channel_status(channel)
    if status == "disabled" or receiver.is_simulated:
        return ("disabled" if status == "disabled" else "dry-run"), ()
    if status in ("ok", "saturated") and receiver.is_stale(channel, now=now):
        status = "stale"
    since = getattr(receiver, "get_samples_since", None)
    samples = since(channel, now - window_s) if since else receiver.get_samples(channel)
    return status, [s for s in samples if now - window_s <= s.timestamp <= now]


def calibration_coefficients():
    """(A, B, state) to read the received R: the receive-path fit from the Calibration page while the sent DC
    levels match it ('calibrated'), else the generator's own SpO2 = A - B*R ('none' / 'other_dc')."""
    from core.rx_spo2_cal import coefficients_for
    from core.signal_engine import SignalEngine
    return coefficients_for(SignalEngine.get_instance().get_ppg_params())


class RXPanel(LaneView):
    """IR/RED lanes shown next to TX on every page; reads, never starts, the receiver."""

    def __init__(self, master, language="en", receiver=None, channels=RX_CHANNELS, vitals=True, **kwargs):
        super().__init__(master, **kwargs)
        self.receiver = receiver or OPT101Receiver.get_instance()
        self.language = language
        self.channels = tuple(channels)
        self.vitals = vitals   # HR / SpO2 / RR badges; off where the output is a test signal (Calibration)
        self.end_s = 0.0
        self._last_update = 0.0
        self._rates = {}       # channel -> (computed_at, RxRate)
        self._spo2 = None      # (computed_at, RxSpo2)
        self._rr = None        # (computed_at, RxRespRate)
        self._filters = {ch: StreamFilter() for ch, _name, _color in self.channels}

    def set_language(self, language):
        self.language = language
        self._last_update = 0.0

    def periodic_update(self):
        now = time.monotonic()
        if not self.winfo_ismapped() or now - self._last_update < REFRESH_S:
            return
        self._last_update = now
        self._heavy = 1        # at most one refresh of the rate/SpO2 estimates per tick (see _may_estimate)
        copy = _PANEL["vi" if self.language == "vi" else "en"]
        period = getattr(self.receiver, "sample_period_s", 0.0)
        max_gap = max(DEFAULT_MAX_GAP_S, 1.5 * period)
        vitals = self.vitals
        lanes = []
        live = {}              # lane name -> samples, only where the channel is really being read
        for channel, name, color in self.channels:
            status, samples = channel_view(self.receiver, channel, now, self.window_s)
            state, message, sub = copy.get(status, (status, status, ""))
            detail = state
            # The plot shows the despiked, lightly smoothed trace; estimates below read the raw samples.
            points = [(t - now, v) for t, v in self._filters[channel].update(
                [(s.timestamp, s.raw * MV_PER_CODE) for s in samples], max_gap)]
            if samples and status in ("ok", "saturated"):
                live[name] = samples
                latest_mv = raw_to_millivolts(samples[-1].raw)
                detail = f"{state}   {points[-1][1]:.0f} mV   {copy['filtered']}"
                if latest_mv >= OPT101_SATURATION_MV:
                    detail += f"   {copy['opt101_sat']}"
            title = f"A{channel}  {name}"
            lanes.append(Lane(title, color, detail, points,
                              message if not samples else "", sub.format(name=name) if not samples else "",
                              max_gap_s=max_gap,
                              badge=self.rate_badge(channel, status, samples, now) if vitals else ""))
        if vitals:
            spo2, rr = self.spo2_badge(live, now), self.rr_badge(live, now)
            for lane, (_channel, name, _color) in zip(lanes, self.channels):
                lane.badge2 = spo2 if name == "RED" else rr if name == "IR" else ""
        self.update_lanes(lanes, end_s=0.0)

    def rr_badge(self, live, now):
        """Respiratory rate from 30-60 s of the IR lane; empty while IR is not being read."""
        if "IR" not in live:
            self._rr = None
            return ""
        computed_at, result = self._rr or (None, None)
        if (computed_at is None or now - computed_at >= RR_REFRESH_S) and self._may_estimate(computed_at):
            channel = next(ch for ch, name, _ in self.channels if name == "IR")
            since = getattr(self.receiver, "get_samples_since", None)
            history = since(channel, now - RR_WINDOW_S) if since else live["IR"]
            result = estimate_rx_rr(history, now=now, max_gap_s=RR_MAX_GAP_S)
            self._rr = (now, result)
        label, reasons = _RR["vi" if self.language == "vi" else "en"]
        if result.brpm is None:
            return f"{label}  — {reasons.get(result.reason, result.reason)}"
        unit = "lần/phút" if self.language == "vi" else "/min"
        return f"{label}  {result.brpm:.0f} {unit}"

    def _may_estimate(self, previous):
        """A due rate/SpO2 estimate costs ~14 ms on the Pi 4 (pure Python). Refreshing the three of them in one
        tick is a 40 ms stall of the Tk thread; this lets one run per tick and the others follow on the next
        ticks, which also keeps them apart afterwards. The first estimate of a value is never deferred."""
        if previous is None:
            return True
        if getattr(self, "_heavy", 1) > 0:
            self._heavy = getattr(self, "_heavy", 1) - 1
            return True
        return False

    def spo2_badge(self, live, now):
        """Estimated SpO2 from both received channels; empty unless both are being read."""
        if "IR" not in live or "RED" not in live:
            self._spo2 = None
            return ""
        computed_at, result = self._spo2 or (None, None)
        if (computed_at is None or now - computed_at >= RATE_REFRESH_S) and self._may_estimate(computed_at):
            a, b, state = calibration_coefficients()
            result = estimate_rx_spo2(live["IR"], live["RED"], a, b)
            self._spo2 = (now, result)
            self._spo2_state = state
        label, reasons = _SPO2["vi" if self.language == "vi" else "en"]
        tag = _SPO2_CAL["vi" if self.language == "vi" else "en"].get(getattr(self, "_spo2_state", "none"), "")
        ratio = "" if result.ratio is None else f"  R {result.ratio:.2f}"
        if result.spo2 is None:
            return f"{label}{tag}  — {reasons.get(result.reason, result.reason)}{ratio}"
        return f"{label}{tag}  {result.spo2:.0f} %{ratio}"

    def rate_badge(self, channel, status, samples, now):
        """Pulse rate of the received samples; empty when there are no real samples (dry-run, off)."""
        if not samples or status not in ("ok", "saturated"):
            self._rates.pop(channel, None)
            return ""
        computed_at, rate = self._rates.get(channel, (None, None))
        if (computed_at is None or now - computed_at >= RATE_REFRESH_S) and self._may_estimate(computed_at):
            rate = estimate_rx_rate(samples)
            self._rates[channel] = (now, rate)
        label, reasons = _RATE["vi" if self.language == "vi" else "en"]
        if rate.bpm is None:
            return f"{label}  — {reasons.get(rate.reason, rate.reason)}"
        return f"{label}  {rate.bpm:.0f} bpm"
