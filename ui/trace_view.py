"""Bounded, timestamp-based dual-channel monitor; no generated placeholder traces."""
import math
import tkinter as tk
from ui import theme as T
from ui.theme import AXIS, DARK, GRID, IR, PLOT_TEXT, RED


class TraceView(tk.Canvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=T.resolve(DARK), highlightthickness=0, **kwargs)
        T.track_canvas(self)
        self.samples = []
        self.channels = ((1, "IR", IR), (2, "RED", RED))
        self.window_s = 8.0
        self.tick_offset_s = 0.0
        self.max_gap_s = None
        self.empty_text = "Ready to generate  /  Press Run"
        self.bind("<Configure>", lambda event: self.render())

    def update_samples(self, samples, empty_text=None):
        self.samples = samples
        if empty_text is not None:
            self.empty_text = empty_text
        self.render()

    def render(self):
        self.delete("all")
        self.configure(bg=T.resolve(DARK))
        w, h = self.winfo_width(), self.winfo_height()
        if w < 100 or h < 80:
            return
        scale = max(0.75, min(1.5, min(w / 1000, h / 300)))
        left, right = round(72 * scale), w - round(18 * scale)
        top, bottom = round(22 * scale), h - round(28 * scale)
        axis_font = max(7, round(9 * scale))
        lane_font = max(8, round(10 * scale))
        end = max(self.window_s, self.samples[-1][0]) if self.samples else self.window_s
        start = end - self.window_s
        points = [p for p in self.samples if p[0] >= start]
        for i in range(9):
            x = left + (right - left) * i / 8
            self.create_line(x, top, x, bottom, fill=GRID, dash=(2, 5))
            tick = start + i * self.window_s / 8 + self.tick_offset_s
            self.create_text(x, h - 12, text=f"{tick:.2f}" if self.window_s < 2 else f"{tick:.0f}",
                             fill="#A5B3BC", font=("DejaVu Sans", axis_font))
        self.create_text(20, h - 12, text="s", fill="#A5B3BC")
        lane = (bottom - top) / len(self.channels)
        for lane_index, (ch, title, color) in enumerate(self.channels):
            y0 = top + lane_index * lane
            self.create_text(left, y0 - 4, text=title + " / mV", fill=color, anchor="sw",
                             font=("DejaVu Sans", lane_font, "bold"))
            values = [p[ch] * 1000 for p in points]
            lo = min(values) if values else 0
            hi = max(values) if values else 50
            span = max(hi - lo, 0.1)
            lo -= span * 0.12
            hi += span * 0.12
            for fraction in (0, 0.5, 1):
                y = y0 + 12 + (lane - 30) * fraction
                self.create_line(left, y, right, y, fill=GRID)
                self.create_text(left - 8, y, text=f"{hi - fraction * (hi-lo):.1f}",
                                 fill="#A5B3BC", anchor="e", font=("DejaVu Sans", max(7, axis_font - 1)))
            coords = []
            previous_time = None
            # Min/max values remain visible: <=800 real samples in an 8 s model window.
            for p in points:
                if self.max_gap_s is not None and previous_time is not None and p[0] - previous_time > self.max_gap_s:
                    if len(coords) >= 4:
                        self.create_line(*coords, fill=color, width=max(1, round(2 * scale)))
                    coords = []
                coords.extend((left + (p[0] - start) / self.window_s * (right-left),
                               y0 + 12 + (hi - p[ch]*1000) / (hi-lo) * (lane-30)))
                previous_time = p[0]
            if len(coords) >= 4:
                self.create_line(*coords, fill=color, width=max(1, round(2 * scale)))
        if not points:
            self.create_text((left + right)/2, h/2, text=self.empty_text,
                             fill="#D6E0E6", font=("DejaVu Sans", max(9, round(12 * scale))))


class Lane:
    """One horizontal strip of a LaneView: its own samples, scale and status."""
    __slots__ = ("title", "color", "detail", "points", "message", "submessage", "max_gap_s")

    def __init__(self, title, color, detail="", points=(), message="", submessage="", max_gap_s=None):
        self.title, self.color, self.detail = title, color, detail
        self.points = points          # [(time_s, value_mV), ...] in time order
        self.message, self.submessage = message, submessage
        self.max_gap_s = max_gap_s    # break the line across gaps longer than this


class LaneView(tk.Canvas):
    """Stacked, independently auto-scaled lanes sharing one time axis.

    Lanes never borrow samples from each other, so A0 and A2 keep their own
    timestamps and a lane without data shows its status text instead of a
    flat line. Values are drawn as received: no smoothing or gap filling.
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=T.resolve(DARK), highlightthickness=0, **kwargs)
        T.track_canvas(self)
        self.lanes = []
        self.window_s = 8.0
        self.end_s = None            # None: follow the newest sample; 0 with relative times
        self.placeholder = ("", "")  # shown once, centred, when no lane has samples
        self.bind("<Configure>", lambda event: self.render())

    def update_lanes(self, lanes, end_s=None):
        self.lanes, self.end_s = list(lanes), end_s
        self.render()

    @staticmethod
    def _format(value, lo, hi):
        # Whole mV once the axis reaches four digits (RX ~1240 mV); one
        # decimal for the small TX AC lanes, where it carries information.
        return f"{value:.0f}" if max(abs(lo), abs(hi)) >= 1000 or hi - lo >= 200 else f"{value:.1f}"

    def render(self):
        self.delete("all")
        self.configure(bg=T.resolve(DARK))
        w, h = self.winfo_width(), self.winfo_height()
        if w < 120 or h < 80 or not self.lanes:
            return
        scale = max(0.9, min(1.5, min(w / 480, h / 240)))
        family = T.font_family()
        small = (family, -round(11 * scale))          # negative: pixels, not points
        bold = (family, -round(12 * scale), "bold")
        message = (family, -round(14 * scale))
        left, right = round(44 * scale), w - round(12 * scale)
        top, bottom = round(6 * scale), h - round(22 * scale)
        end = self.end_s
        if end is None:
            last = [lane.points[-1][0] for lane in self.lanes if lane.points]
            end = max([self.window_s] + last)
        start = end - self.window_s

        def x_of(t):
            return left + (t - start) / self.window_s * (right - left)

        # Time grid at whole seconds, so it scrolls with the trace like a monitor.
        for second in range(math.ceil(start), math.floor(end) + 1):
            x = x_of(second)
            self.create_line(x, top, x, bottom, fill=GRID, dash=(1, 4))
            self.create_text(x, h - round(11 * scale), text=f"{second:d}", fill=AXIS, font=small)
        self.create_text(round(14 * scale), h - round(11 * scale), text="s", fill=AXIS, font=small)

        lane_h = (bottom - top) / len(self.lanes)
        all_empty = not any(p for lane in self.lanes for p in lane.points if start <= p[0] <= end)
        if all_empty and self.placeholder[0]:
            # Centred in the first lane so it never collides with a lane header.
            cy = top + lane_h / 2 + 8 * scale
            self.create_text((left + right) / 2, cy - 8 * scale, text=self.placeholder[0], fill=PLOT_TEXT,
                             font=message)
            self.create_text((left + right) / 2, cy + 10 * scale, text=self.placeholder[1], fill=AXIS, font=small)
        for index, lane in enumerate(self.lanes):
            y0 = top + index * lane_h
            header_y = y0 + round(11 * scale)
            title_id = self.create_text(left + 4, header_y, text=lane.title, fill=lane.color,
                                        font=bold, anchor="w")
            if lane.detail:
                x1 = self.bbox(title_id)[2] + round(8 * scale)
                self.create_text(x1, header_y, text=lane.detail, fill=AXIS, font=small, anchor="w")
            plot_top, plot_bottom = y0 + round(26 * scale), y0 + lane_h - round(8 * scale)
            points = [p for p in lane.points if start <= p[0] <= end]
            if not points:
                if index:
                    self.create_line(left, y0, right, y0, fill=GRID)
                if all_empty and self.placeholder[0]:
                    continue
                cy = (plot_top + plot_bottom) / 2
                if lane.message:
                    self.create_text((left + right) / 2, cy - (8 * scale if lane.submessage else 0),
                                     text=lane.message, fill=PLOT_TEXT, font=message)
                if lane.submessage:
                    self.create_text((left + right) / 2, cy + 10 * scale, text=lane.submessage,
                                     fill=AXIS, font=small)
                continue
            values = [p[1] for p in points]
            lo, hi = min(values), max(values)
            span = max(hi - lo, 0.1)
            lo, hi = lo - span * 0.1, hi + span * 0.1
            for fraction in (0.0, 0.5, 1.0):
                y = plot_top + (plot_bottom - plot_top) * fraction
                self.create_line(left, y, right, y, fill=GRID)
                self.create_text(left - 6, y, text=self._format(hi - fraction * (hi - lo), lo, hi),
                                 fill=AXIS, font=small, anchor="e")
            coords, previous = [], None
            width = max(1, round(1.6 * scale))
            for t, v in points:
                if lane.max_gap_s is not None and previous is not None and t - previous > lane.max_gap_s:
                    if len(coords) >= 4:
                        self.create_line(*coords, fill=lane.color, width=width)
                    coords = []
                coords.extend((x_of(t), plot_top + (hi - v) / (hi - lo) * (plot_bottom - plot_top)))
                previous = t
            if len(coords) >= 4:
                self.create_line(*coords, fill=lane.color, width=width)
