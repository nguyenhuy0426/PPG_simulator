"""Shared read-only view of the existing receiver; never starts ADC or DAC IO."""
import time
import customtkinter as ctk

from hw.opt101_rx import OPT101Receiver, raw_to_millivolts
from ui import theme as T
from ui.trace_view import TraceView


class RXMonitor(ctk.CTkFrame):
    def __init__(self, master, language="en", receiver=None, **kwargs):
        super().__init__(master, fg_color=T.DARK, **kwargs)
        self.receiver = receiver or OPT101Receiver.get_instance()
        self.language = language
        self._last_update = 0.0
        self.grid_columnconfigure((0, 1), weight=1, uniform="rx")
        self.labels, self.traces = {}, {}
        for column, (channel, name, color) in enumerate(((0, "A0 · IR", T.IR), (2, "A2 · RED", T.RED))):
            label = T.label(self, name, 11, True, text_color=color, anchor="w")
            label.grid(row=0, column=column, sticky="ew", padx=8, pady=(3, 0))
            trace = TraceView(self, width=1, height=100)
            trace.channels = ((1, name, color),)
            trace.empty_text = "Đang chờ ADC" if language == "vi" else "Waiting for ADC"
            trace.max_gap_s = 0.05
            trace.grid(row=1, column=column, sticky="ew", padx=4, pady=(0, 3))
            self.labels[channel], self.traces[channel] = label, trace

    def set_language(self, language):
        self.language = language
        self._last_update = 0.0

    def periodic_update(self):
        now = time.monotonic()
        if not self.winfo_ismapped() or now - self._last_update < 0.1:
            return
        self._last_update = now
        vi = self.language == "vi"
        messages = {
            "disabled": "Chưa bật / chưa gắn cảm biến" if vi else "Disabled / sensor not installed",
            "dry-run": "Mô phỏng: không có dữ liệu ADC thật" if vi else "Dry run: no physical ADC data",
            "init": "Đang chờ ADC" if vi else "Waiting for ADC",
            "stale": "Dữ liệu cũ / ngừng cập nhật" if vi else "Stale / no fresh samples",
            "ok": "Trực tiếp" if vi else "Live",
            "saturated": "Chạm trần ADC" if vi else "ADC full scale",
            "error": "Lỗi đọc ADC" if vi else "ADC read error",
            "invalid": "Mẫu ADC không hợp lệ" if vi else "Invalid ADC sample",
            "disconnected": "Mất kết nối ADC" if vi else "ADC disconnected",
        }
        for channel, trace in self.traces.items():
            status = self.receiver.channel_status(channel)
            samples = self.receiver.get_samples(channel)
            if status == "disabled" or self.receiver.is_simulated:
                samples = ()
                if status != "disabled":
                    status = "dry-run"
            elif status in ("ok", "saturated") and self.receiver.is_stale(channel, now=now):
                status = "stale"
            message = messages.get(status, status)
            title = "THU OPT101" if vi else "OPT101 RX"
            self.labels[channel].configure(text=f"{title} · A{channel} · {message}")
            # Each channel retains its own real timestamps. Never zero-fill A2
            # or interpolate missing reads. The axis is seconds relative to now.
            points = [(s.timestamp - now + trace.window_s, raw_to_millivolts(s.raw) / 1000)
                      for s in samples if now - trace.window_s <= s.timestamp <= now]
            trace.tick_offset_s = -trace.window_s
            trace.update_samples(points, empty_text=message if not points else "")
