"""Bounded, timestamp-based dual-channel monitor; no generated placeholder traces."""
import tkinter as tk
from ui.theme import DARK, GRID, IR, RED


class TraceView(tk.Canvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg=DARK, highlightthickness=0, **kwargs)
        self.samples = []
        self.window_s = 8.0
        self.empty_text = "Ready to generate  /  Press Run"
        self.bind("<Configure>", lambda event: self.render())

    def update_samples(self, samples, empty_text=None):
        self.samples = samples
        if empty_text is not None:
            self.empty_text = empty_text
        self.render()

    def render(self):
        self.delete("all")
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
            self.create_text(x, h - 12, text=f"{start + i * self.window_s / 8:.0f}",
                             fill="#A5B3BC", font=("DejaVu Sans", axis_font))
        self.create_text(20, h - 12, text="s", fill="#A5B3BC")
        lane = (bottom - top) / 2
        for ch, title, color in ((1, "IR", IR), (2, "RED", RED)):
            y0 = top + (ch - 1) * lane
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
            # Min/max values remain visible: <=800 real samples in an 8 s model window.
            for p in points:
                coords.extend((left + (p[0] - start) / self.window_s * (right-left),
                               y0 + 12 + (hi - p[ch]*1000) / (hi-lo) * (lane-30)))
            if len(coords) >= 4:
                self.create_line(*coords, fill=color, width=max(1, round(2 * scale)))
        if not points:
            self.create_text((left + right)/2, h/2, text=self.empty_text,
                             fill="#D6E0E6", font=("DejaVu Sans", max(9, round(12 * scale))))
