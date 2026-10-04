"""Shared read-only view of the existing receiver; never starts ADC or DAC IO."""
import time
import customtkinter as ctk

from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
from ui import theme as T
from ui.trace_view import Lane, LaneView

RX_CHANNELS = ((0, "IR", T.IR), (2, "RED", T.RED))
REFRESH_S = 0.1

# Short lane-header state plus the centred explanation for the Classic RX panel.
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


class RXMonitor(ctk.CTkFrame):
    """Persistent RX card for pages without their own RX view: A0 and A2 side by side."""

    TITLE = {"vi": "Tín hiệu thu RX · OPT101", "en": "RX received signal · OPT101"}

    def __init__(self, master, language="en", receiver=None, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        from ui import page_kit as K
        self.receiver = receiver or OPT101Receiver.get_instance()
        card, self.title, _ = K.section(self)
        card.pack(fill="both", expand=True, pady=(T.ui(4), T.ui(6)))
        holder = K.plot_holder(card)
        holder.grid_columnconfigure((0, 1), weight=1, uniform="rx")
        holder.grid_rowconfigure(0, weight=1)
        self.panels = {}
        for column, channel in enumerate(RX_CHANNELS):
            panel = RXPanel(holder, language=language, receiver=self.receiver, channels=(channel,), height=88)
            panel.grid(row=0, column=column, sticky="nsew", padx=T.ui(3), pady=T.ui(3))
            self.panels[channel[0]] = panel
        self.set_language(language)

    @property
    def receiver(self):
        return self._receiver

    @receiver.setter
    def receiver(self, receiver):
        # Tests and smoke scripts swap in a fixture receiver after construction.
        self._receiver = receiver
        for panel in getattr(self, "panels", {}).values():
            panel.receiver = receiver
            panel._last_update = 0.0

    def set_language(self, language):
        self.language = language
        self.title.configure(text=self.TITLE["vi" if language == "vi" else "en"])
        for panel in self.panels.values():
            panel.set_language(language)

    def periodic_update(self):
        if not self.winfo_ismapped():
            return
        for panel in self.panels.values():
            panel.periodic_update()


class RXPanel(LaneView):
    """A0/A2 lanes for the Classic page; same data and rules as RXMonitor."""

    def __init__(self, master, language="en", receiver=None, channels=RX_CHANNELS, **kwargs):
        super().__init__(master, **kwargs)
        self.receiver = receiver or OPT101Receiver.get_instance()
        self.language = language
        self.channels = tuple(channels)
        self.end_s = 0.0
        self._last_update = 0.0

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
                              max_gap_s=0.05))
        self.update_lanes(lanes, end_s=0.0)
