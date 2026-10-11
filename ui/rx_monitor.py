"""Shared read-only view of the existing receiver; never starts ADC or DAC IO."""
import time

from core.rx_heart_rate import estimate_rx_rate
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
from ui import theme as T
from ui.trace_view import Lane, LaneView

RX_CHANNELS = ((0, "IR", T.IR), (2, "RED", T.RED))
REFRESH_S = 0.1
RATE_REFRESH_S = 1.0   # rate recomputed at most once a second per channel (~3 ms each on the x86 laptop; Pi unmeasured)

# Received pulse rate shown in each live lane header: (label, reasons there is none).
_RATE = {
    "vi": ("Nhịp RX", {"short": "cần ≥ 5 s liên tục", "saturated": "chạm trần ADC", "weak": "tín hiệu yếu",
                       "unclear": "không rõ nhịp đều"}),
    "en": ("RX rate", {"short": "needs ≥ 5 s gap-free", "saturated": "ADC clipping", "weak": "weak signal",
                       "unclear": "no clear regular rhythm"}),
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
    },
}


def channel_view(receiver, channel, now, window_s):
    """Status and the in-window samples of one channel, as (status, samples).

    Disabled channels and dry-run never return samples: nothing is fabricated.
    """
    status = receiver.channel_status(channel)
    samples = receiver.get_samples(channel)
    if status == "disabled" or receiver.is_simulated:
        return ("disabled" if status == "disabled" else "dry-run"), ()
    if status in ("ok", "saturated") and receiver.is_stale(channel, now=now):
        status = "stale"
    return status, [s for s in samples if now - window_s <= s.timestamp <= now]


class RXPanel(LaneView):
    """A0/A2 lanes shown next to TX on every page; reads, never starts, the receiver."""

    def __init__(self, master, language="en", receiver=None, channels=RX_CHANNELS, **kwargs):
        super().__init__(master, **kwargs)
        self.receiver = receiver or OPT101Receiver.get_instance()
        self.language = language
        self.channels = tuple(channels)
        self.end_s = 0.0
        self._last_update = 0.0
        self._rates = {}       # channel -> (computed_at, RxRate)

    def set_language(self, language):
        self.language = language
        self._last_update = 0.0

    def periodic_update(self):
        now = time.monotonic()
        if not self.winfo_ismapped() or now - self._last_update < REFRESH_S:
            return
        self._last_update = now
        copy = _PANEL["vi" if self.language == "vi" else "en"]
        lanes = []
        for channel, name, color in self.channels:
            status, samples = channel_view(self.receiver, channel, now, self.window_s)
            state, message, sub = copy.get(status, (status, status, ""))
            detail = state
            if samples and status in ("ok", "saturated"):
                detail = f"{state}   {raw_to_millivolts(samples[-1].raw):.0f} mV"
            lanes.append(Lane(f"A{channel}  {name}", color, detail,
                              [(s.timestamp - now, raw_to_millivolts(s.raw)) for s in samples],
                              message if not samples else "", sub.format(name=name) if not samples else "",
                              max_gap_s=0.05, badge=self.rate_badge(channel, status, samples, now)))
        self.update_lanes(lanes, end_s=0.0)

    def rate_badge(self, channel, status, samples, now):
        """Pulse rate of the received samples; empty when there are no real samples (dry-run, off)."""
        if not samples or status not in ("ok", "saturated"):
            self._rates.pop(channel, None)
            return ""
        computed_at, rate = self._rates.get(channel, (None, None))
        if computed_at is None or now - computed_at >= RATE_REFRESH_S:
            rate = estimate_rx_rate(samples)
            self._rates[channel] = (now, rate)
        label, reasons = _RATE["vi" if self.language == "vi" else "en"]
        if rate.bpm is None:
            return f"{label}  — {reasons.get(rate.reason, rate.reason)}"
        return f"{label}  {rate.bpm:.0f} bpm"
