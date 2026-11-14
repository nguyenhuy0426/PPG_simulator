"""Timestamp-based signal lanes; no generated placeholder traces."""
import math
from operator import sub
import time
import tkinter as tk
from ui import theme as T
from ui.theme import AXIS, DARK, GRID, IR, PLOT_TEXT, RED  # noqa: F401  (re-exported)


# A Pi 4 pays ~0.3 ms per canvas item (Tk + Xwayland), so a lane is drawn with at
# most one vertex per pixel column; the y-scale still uses every sample.
MAX_VERTICES_PER_PIXEL = 1.0
# A render slower than this marks a slow host: the next one then waits twice
# as long as the last took, so the Tk thread (which also owns the GIL the
# DAC and RX threads need) never spends its whole time redrawing.
SLOW_RENDER_S = 0.015
RENDER_BACKOFF = 2.0


class Lane:
    """One horizontal strip of a LaneView: its own samples, scale and status."""
    __slots__ = ("title", "color", "detail", "points", "message", "submessage", "max_gap_s", "badge", "badge2")

    def __init__(self, title, color, detail="", points=(), message="", submessage="", max_gap_s=None, badge="",
                 badge2=""):
        self.title, self.color, self.detail = title, color, detail
        self.badge = badge            # right-aligned header reading, e.g. the received pulse rate
        self.badge2 = badge2          # second reading under it, e.g. the received SpO2
        self.points = points          # [(time_s, value_mV), ...] in time order
        self.message, self.submessage = message, submessage
        self.max_gap_s = max_gap_s    # break the line across gaps longer than this


class LaneView(tk.Canvas):
    """Stacked, independently auto-scaled lanes sharing one time axis.

    Lanes never borrow samples from each other, so A0 and A4 keep their own
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
        self._drawn = None           # what the canvas shows; an identical update is not redrawn
        self._items = None           # canvas item ids of the last full draw, for in-place updates
        self._not_before = 0.0
        self.bind("<Configure>", lambda event: self.render())

    def update_lanes(self, lanes, end_s=None):
        """Redraw only when something visible changed and, on a slow host,
        not before the backoff from the previous render has passed."""
        now = time.perf_counter()
        if now < self._not_before:
            return
        self.lanes, self.end_s = list(lanes), end_s
        # Stopped output, an idle receiver or a dry-run status repeat the same picture every tick;
        # redrawing it costs a full canvas rebuild. Size and theme changes call render() directly.
        content = (end_s, self.placeholder, [(lane.title, lane.color, lane.detail, lane.badge, lane.badge2, lane.message,
                                              lane.submessage, lane.max_gap_s, list(lane.points))
                                             for lane in self.lanes])
        if content == self._drawn:
            return
        self._drawn = content
        self.render()
        cost = time.perf_counter() - now
        if cost > SLOW_RENDER_S:
            self._not_before = now + RENDER_BACKOFF * cost

    @staticmethod
    def _format(value, lo, hi):
        # Whole mV once the axis reaches four digits (RX ~1240 mV); one
        # decimal for the small TX AC lanes, where it carries information.
        return f"{value:.0f}" if max(abs(lo), abs(hi)) >= 1000 or hi - lo >= 200 else f"{value:.1f}"

    def render(self):
        """Draw the lanes. Between two frames that differ only in samples (the live case), the canvas items are
        kept: the polylines get new coordinates, the scrolling time grid is moved, and a text is touched only when
        it changed. A layout, size, theme or header change rebuilds everything (the full path below), and the
        result of both paths is the same set of items (tests/test_ui_performance.py checks that)."""
        frame = self._frame()
        if frame is None:
            self.delete("all")
            self.configure(bg=T.resolve(DARK))
            self._items = None
            return
        items = self._items
        if items is not None and items["signature"] == frame["signature"]:
            self._patch(frame, items)
        else:
            self._rebuild(frame)

    # ---- geometry shared by both paths ----
    def _frame(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 120 or h < 80 or not self.lanes:
            return None
        scale = max(0.9, min(1.5, min(w / 480, h / 240)))
        left, right = round(44 * scale), w - round(12 * scale)
        top, bottom = round(6 * scale), h - round(22 * scale)
        end = self.end_s
        if end is None:
            last = [lane.points[-1][0] for lane in self.lanes if lane.points]
            end = max([self.window_s] + last)
        start = end - self.window_s

        def x_of(t):
            return left + (t - start) / self.window_s * (right - left)

        lane_h = (bottom - top) / len(self.lanes)
        all_empty = not any(p for lane in self.lanes for p in lane.points if start <= p[0] <= end)
        lanes = []
        for index, lane in enumerate(self.lanes):
            y0 = top + index * lane_h
            header_y = y0 + round(11 * scale)
            plot_top, plot_bottom = y0 + round(26 * scale), y0 + lane_h - round(8 * scale)
            if lane.badge2 and plot_bottom - plot_top > round(40 * scale):
                plot_top_line = plot_top + round(12 * scale)    # the trace starts below the second header row
            else:
                plot_top_line = plot_top
            points = lane.points            # in time order, so a trace already inside the window needs no filtering
            if points and not (start <= points[0][0] and points[-1][0] <= end):
                points = [p for p in points if start <= p[0] <= end]
            info = dict(lane=lane, y0=y0, header_y=header_y, plot_top=plot_top_line, plot_bottom=plot_bottom,
                        empty=not points, labels=(), segments=())
            if points:
                times, values = zip(*points)                       # C-speed unzip
                lo, hi = min(values), max(values)
                span = max(hi - lo, 0.1)
                lo, hi = lo - span * 0.1, hi + span * 0.1
                info["lo"], info["hi"] = lo, hi
                info["labels"] = tuple(self._format(hi - f * (hi - lo), lo, hi) for f in (0.0, 0.5, 1.0))
                cap = max(2, int((right - left) * MAX_VERTICES_PER_PIXEL))
                if len(points) > cap:
                    stride = -(-len(points) // cap)
                    times_d, values_d = times[::stride], values[::stride]
                    if times_d[-1] is not times[-1]:
                        times_d, values_d = times_d + (times[-1],), values_d + (values[-1],)
                    times, values = times_d, values_d
                kx = (right - left) / self.window_s
                ky = (plot_bottom - plot_top_line) / (hi - lo)
                gap = lane.max_gap_s
                segments = []
                # Piece boundaries: a hole longer than max_gap_s starts a new line. One C-speed pass answers "no
                # holes" (the usual case) so the Python loop only runs when there is something to split.
                cuts = [0]
                if gap is not None and len(times) > 1 and max(map(sub, times[1:], times[:-1])) > gap:
                    cuts += [i for i in range(1, len(times)) if times[i] - times[i - 1] > gap]
                cuts.append(len(times))
                for lo_i, hi_i in zip(cuts, cuts[1:]):
                    if hi_i - lo_i < 2:
                        continue                                    # a piece of one vertex is not a line
                    coords = [0.0] * (2 * (hi_i - lo_i))
                    coords[0::2] = [left + (t - start) * kx for t in times[lo_i:hi_i]]
                    coords[1::2] = [plot_top_line + (hi - v) * ky for v in values[lo_i:hi_i]]
                    segments.append(coords)
                info["segments"] = segments
            lanes.append(info)
        # Everything that forces a rebuild: size, theme, titles, colours, which header texts and traces exist. The text of detail/badge/badge2 (a live mV reading, a rate), the
        # time grid and the polylines are patched in place.
        signature = (w, h, T.resolve(DARK), scale, self.placeholder, all_empty,
                     tuple((i["lane"].title, i["lane"].color, bool(i["lane"].detail), bool(i["lane"].badge),
                            bool(i["lane"].badge2), i["lane"].message, i["lane"].submessage, i["empty"], i["plot_top"], i["plot_bottom"])
                           for i in lanes))
        return dict(signature=signature, w=w, h=h, scale=scale, left=left, right=right, top=top, bottom=bottom,
                    start=start, end=end, x_of=x_of, lane_h=lane_h, all_empty=all_empty, lanes=lanes,
                    seconds=tuple(range(math.ceil(start), math.floor(end) + 1)))

    # ---- full path ----
    def _grid(self, f):
        """Time grid at whole seconds, so it scrolls with the trace like a monitor. Tagged to be moved as one."""
        scale, h, family = f["scale"], f["h"], T.font_family()
        small = (family, -round(11 * scale))
        for second in f["seconds"]:
            x = f["x_of"](second)
            self.create_line(x, f["top"], x, f["bottom"], fill=GRID, dash=(1, 4), tags="tgrid")
            self.create_text(x, h - round(11 * scale), text=f"{second:d}", fill=AXIS, font=small, tags="tgrid")

    def _rebuild(self, f):
        self.delete("all")
        self.configure(bg=T.resolve(DARK))
        scale, w, h = f["scale"], f["w"], f["h"]
        family = T.font_family()
        small = (family, -round(11 * scale))          # negative: pixels, not points
        bold = (family, -round(12 * scale), "bold")
        message = (family, -round(14 * scale))
        left, right, top = f["left"], f["right"], f["top"]
        self._grid(f)
        self.create_text(round(14 * scale), h - round(11 * scale), text="s", fill=AXIS, font=small)

        lane_h, all_empty = f["lane_h"], f["all_empty"]
        if all_empty and self.placeholder[0]:
            # Centred in the first lane so it never collides with a lane header.
            cy = top + lane_h / 2 + 8 * scale
            self.create_text((left + right) / 2, cy - 8 * scale, text=self.placeholder[0], fill=PLOT_TEXT,
                             font=message)
            self.create_text((left + right) / 2, cy + 10 * scale, text=self.placeholder[1], fill=AXIS, font=small)
        width = max(1, round(1.6 * scale))
        labels, lines, headers = [], [], []
        for index, info in enumerate(f["lanes"]):
            lane, y0, header_y = info["lane"], info["y0"], info["header_y"]
            title_id = self.create_text(left + 4, header_y, text=lane.title, fill=lane.color, font=bold, anchor="w")
            header = {}
            if lane.detail:
                x1 = self.bbox(title_id)[2] + round(8 * scale)
                header["detail"] = self.create_text(x1, header_y, text=lane.detail, fill=AXIS, font=small, anchor="w")
            if lane.badge:
                header["badge"] = self.create_text(right - 4, header_y, text=lane.badge, fill=lane.color, font=bold,
                                                   anchor="e")
            if lane.badge2:
                header["badge2"] = self.create_text(right - 4, header_y + round(14 * scale), text=lane.badge2,
                                                    fill=lane.color, font=bold, anchor="e")
            headers.append(header)
            lane_labels, lane_lines = [], []
            if info["empty"]:
                if index:
                    self.create_line(left, y0, right, y0, fill=GRID)
                if not (all_empty and self.placeholder[0]):
                    cy = (info["plot_top"] + info["plot_bottom"]) / 2
                    if lane.message:
                        self.create_text((left + right) / 2, cy - (8 * scale if lane.submessage else 0),
                                         text=lane.message, fill=PLOT_TEXT, font=message)
                    if lane.submessage:
                        self.create_text((left + right) / 2, cy + 10 * scale, text=lane.submessage,
                                         fill=AXIS, font=small)
            else:
                plot_top, plot_bottom = info["plot_top"], info["plot_bottom"]
                for fraction, label in zip((0.0, 0.5, 1.0), info["labels"]):
                    y = plot_top + (plot_bottom - plot_top) * fraction
                    self.create_line(left, y, right, y, fill=GRID)
                    lane_labels.append(self.create_text(left - 6, y, text=label, fill=AXIS, font=small, anchor="e"))
                for coords in info["segments"]:
                    lane_lines.append(self.create_line(*coords, fill=lane.color, width=width))
            labels.append(lane_labels)
            lines.append(lane_lines)
        self._items = dict(signature=f["signature"], labels=labels, lines=lines, headers=headers,
                           seconds=f["seconds"], grid_x0=f["x_of"](f["seconds"][0]) if f["seconds"] else None)

    # ---- incremental path ----
    def _patch(self, f, items):
        if f["seconds"] != items["seconds"]:
            self.delete("tgrid")
            self._grid(f)
            self.tag_lower("tgrid")
            items["seconds"] = f["seconds"]
        elif f["seconds"]:
            x0 = f["x_of"](f["seconds"][0])
            if x0 != items["grid_x0"]:
                self.move("tgrid", x0 - items["grid_x0"], 0)
        items["grid_x0"] = f["x_of"](f["seconds"][0]) if f["seconds"] else None
        for info, label_ids, line_ids, header in zip(f["lanes"], items["labels"], items["lines"], items["headers"]):
            for key, item in header.items():
                text = getattr(info["lane"], key)
                if self.itemcget(item, "text") != text:
                    self.itemconfigure(item, text=text)
            for item, text in zip(label_ids, info["labels"]):
                if self.itemcget(item, "text") != text:
                    self.itemconfigure(item, text=text)
            segments = info["segments"]
            for item, coords in zip(line_ids, segments):
                self.coords(item, *coords)
            if len(segments) > len(line_ids):        # a gap in the samples split the trace into more pieces
                width = max(1, round(1.6 * f["scale"]))
                for coords in segments[len(line_ids):]:
                    line_ids.append(self.create_line(*coords, fill=info["lane"].color, width=width))
            elif len(segments) < len(line_ids):
                for item in line_ids[len(segments):]:
                    self.delete(item)
                del line_ids[len(segments):]


class TraceView(LaneView):
    """Fixed-channel monitor on the shared lane renderer.

    Callers pass rows of (time_s, ch1_V, ch2_V, ...); `channels` picks the
    columns as (index, title, colour). All lanes share the row timestamps.
    """

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.samples = []
        self.channels = ((1, "IR", IR), (2, "RED", RED))
        self.tick_offset_s = 0.0     # e.g. -window_s to label the axis -8 … 0
        self.max_gap_s = None
        self.empty_text = "Ready to generate  /  Press Run"

    def update_samples(self, samples, empty_text=None):
        self.samples = samples
        if empty_text is not None:
            self.empty_text = empty_text
        offset = self.tick_offset_s
        lanes = [Lane(title, color, "mV", [(row[0] + offset, row[ch] * 1000) for row in samples],
                      max_gap_s=self.max_gap_s)
                 for ch, title, color in self.channels]
        self.placeholder = (self.empty_text, "")
        end = None
        if samples:
            end = max(self.window_s, samples[-1][0]) + offset
        elif offset:
            end = self.window_s + offset
        self.update_lanes(lanes, end_s=end)


