"""Shared read-only view of the existing receiver; never starts ADC or DAC IO."""
import time

from core.rx_heart_rate import estimate_rx_rate
from core.rx_spo2 import estimate_rx_spo2
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
from ui import theme as T
from ui.trace_view import Lane, LaneView

RX_CHANNELS = ((0, "IR", T.IR), (4, "RED", T.RED))
REFRESH_S = 0.1
MV_PER_CODE = raw_to_millivolts(1)   # the conversion is linear: one multiply per sample instead of a call
DEFAULT_MAX_GAP_S = 0.05
RATE_REFRESH_S = 2.0   # rate and SpO2 recomputed at most every 2 s: ~3 ms per channel on the laptop, far more on the Pi, and the value moves slowly

# Received pulse rate shown in each live lane header: (label, reasons there is none).
_RATE = {
    "vi": ("Nhịp RX", {"short": "cần ≥ 5 s liên tục", "saturated": "chạm trần ADC", "weak": "tín hiệu yếu",
                       "unclear": "không rõ nhịp đều"}),
    "en": ("RX rate", {"short": "needs ≥ 5 s gap-free", "saturated": "ADC clipping", "weak": "weak signal",
                       "unclear": "no clear regular rhythm"}),
}

# Estimated SpO2 shown under the rate of the RED lane: (label, reasons there is none).
_SPO2 = {
    "vi": ("SpO₂ RX ước tính", {"short": "cần ≥ 5 s cả hai kênh", "saturated": "chạm trần ADC", "weak": "tín hiệu yếu",
                                "mismatch": "IR và RED không cùng nhịp", "no_dc": "không có mức DC",
                                "out_of_range": "ngoài thang"}),
    "en": ("Estimated RX SpO₂", {"short": "needs ≥ 5 s on both", "saturated": "ADC clipping", "weak": "weak signal",
                                 "mismatch": "IR and RED pulses differ", "no_dc": "no DC level",
                                 "out_of_range": "out of scale"}),
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
        "ok": ("Trực tiếp", "", ""), "saturated": ("Chạm trần ADC", "", ""),
        "tdm_idle": "TDM chỉ đọc cảm biến khi đang phát TX",
    },
    "en": {
        "disabled": ("Off", "No sensor installed", "Channel stays off until the {name} sensor is fitted"),
        "dry-run": ("Simulated", "No physical ADC data", "Dry-run mode does not read Grove 0x08"),
        "init": ("Waiting", "Waiting for the first ADC sample", ""),
        "stale": ("Stale", "No fresh samples", "Last sample is older than 0.5 s"),
        "error": ("Error", "ADC read error", "Check the Grove Base Hat 0x08 and cable"),
        "invalid": ("Error", "Invalid ADC sample", ""),
        "disconnected": ("Disconnected", "ADC disconnected", "Check the Grove Base Hat 0x08 and cable"),
        "ok": ("Live", "", ""), "saturated": ("ADC full scale", "", ""),
        "tdm_idle": "TDM reads the sensor only while output runs",
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
    """The generator's SpO2 = A - B*R coefficients, also used to read the received R."""
    from core.signal_engine import SignalEngine
    params = SignalEngine.get_instance().get_ppg_params()
    return params.spo2_coeff_a, params.spo2_coeff_b


class RXPanel(LaneView):
    """A0/A4 lanes shown next to TX on every page; reads, never starts, the receiver."""

    def __init__(self, master, language="en", receiver=None, channels=RX_CHANNELS, **kwargs):
        super().__init__(master, **kwargs)
        self.receiver = receiver or OPT101Receiver.get_instance()
        self.language = language
        self.channels = tuple(channels)
        self.end_s = 0.0
        self._last_update = 0.0
        self._rates = {}       # channel -> (computed_at, RxRate)
        self._spo2 = None      # (computed_at, RxSpo2)

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
        # TDM: both lanes come from one sensor, one sample per slot frame.
        tdm = getattr(self.receiver, "mode", "dual") == "tdm"
        period = getattr(self.receiver, "sample_period_s", 0.0)
        max_gap = max(DEFAULT_MAX_GAP_S, 1.5 * period)
        dark = self.receiver.get_dark_samples(1) if tdm else ()
        lanes = []
        live = {}              # lane name -> samples, only where the channel is really being read
        for channel, name, color in self.channels:
            status, samples = channel_view(self.receiver, channel, now, self.window_s)
            state, message, sub = copy.get(status, (status, status, ""))
            if tdm and status in ("init", "stale"):
                sub = copy["tdm_idle"]
            detail = state
            if samples and status in ("ok", "saturated"):
                live[name] = samples
                detail = f"{state}   {raw_to_millivolts(samples[-1].raw):.0f} mV"
                if dark:
                    detail += f"   dark {raw_to_millivolts(dark[-1].raw):.0f} mV"
            title = (f"A{self.receiver.physical_channel(channel)} TDM  {name}" if tdm
                     else f"A{channel}  {name}")
            lanes.append(Lane(title, color, detail,
                              [(s.timestamp - now, s.raw * MV_PER_CODE) for s in samples],
                              message if not samples else "", sub.format(name=name) if not samples else "",
                              max_gap_s=max_gap, badge=self.rate_badge(channel, status, samples, now)))
        spo2 = self.spo2_badge(live, tdm, now)
        for lane, (_channel, name, _color) in zip(lanes, self.channels):
            if name == "RED":
                lane.badge2 = spo2
        self.update_lanes(lanes, end_s=0.0)

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

    def spo2_badge(self, live, tdm, now):
        """Estimated SpO2 from both received channels; empty unless both are being read."""
        if "IR" not in live or "RED" not in live:
            self._spo2 = None
            return ""
        computed_at, result = self._spo2 or (None, None)
        if (computed_at is None or now - computed_at >= RATE_REFRESH_S) and self._may_estimate(computed_at):
            dark = [s.raw for s in self.receiver.get_dark_samples() if now - self.window_s <= s.timestamp] if tdm else []
            level = sum(dark) / len(dark) if dark else 0.0
            result = estimate_rx_spo2(live["IR"], live["RED"], *calibration_coefficients(),
                                      ir_dark=level, red_dark=level)
            self._spo2 = (now, result)
        label, reasons = _SPO2["vi" if self.language == "vi" else "en"]
        ratio = "" if result.ratio is None else f"  R {result.ratio:.2f}"
        if result.spo2 is None:
            return f"{label}  — {reasons.get(result.reason, result.reason)}{ratio}"
        return f"{label}  {result.spo2:.0f} %{ratio}"

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
