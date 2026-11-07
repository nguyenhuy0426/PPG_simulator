#!/usr/bin/env python3
"""Measure what the Tk UI costs while output is running, per page: CPU by thread, canvas renders per second,
render time, canvas items drawn, update_gui time. Dry-run, with a synthetic 100 Hz RX stream fed to the receiver
so the RX card draws what it draws with a live sensor (this is NOT a physical measurement).

Usage (needs a display; on the Pi use DISPLAY=:0):  python3 scripts/measure_ui_load.py [--seconds 10] [--out file.json]
"""
import argparse
import cProfile
import io
import pstats
import json
import math
import os
import statistics
import sys
import threading
import time
from pathlib import Path

os.environ["PPG_DRY_RUN"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.signal_engine import SignalEngine
from hw.opt101_rx import OPT101Receiver, RXSample
from ui import trace_view
from ui.ctk_app import CTkApp
from ui.rx_monitor import RX_CHANNELS

CLK = os.sysconf("SC_CLK_TCK")


def thread_cpu():
    out = {}
    for tid in os.listdir("/proc/self/task"):
        try:
            fields = open(f"/proc/self/task/{tid}/stat").read().rsplit(")", 1)[1].split()
            out[tid] = ((int(fields[11]) + int(fields[12])) / CLK, open(f"/proc/self/task/{tid}/comm").read().strip())
        except OSError:
            pass
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--out", default=None)
    parser.add_argument("--geometry", default="1024x600+0+0")
    parser.add_argument("--profile", action="store_true", help="print the UI thread's top functions per page")
    parser.add_argument("--pages", default="Pathology,Calibration,Playback,Neural")
    args = parser.parse_args()

    CTkApp._maximize_to_work_area = lambda self: None
    app = CTkApp(language="en")
    app._save_language = lambda: None
    app.geometry(args.geometry)

    # RX fixture: both channels fed at 100 Hz, like the Grove ADC loop would.
    rx = OPT101Receiver(dry_run=False, enabled_channels=tuple(c for c, *_ in RX_CHANNELS))
    stop = threading.Event()

    def feed():
        i, nxt = 0, time.monotonic()
        while not stop.is_set():
            now = time.monotonic()
            for ch, dc, ac in ((RX_CHANNELS[0][0], 900, 60), (RX_CHANNELS[1][0], 1300, 25)):
                st = rx._channels[ch]
                st.status = "ok"
                with rx._lock:       # the acquisition loop appends under this lock too
                    st.buffer.append(RXSample(now, int(dc + ac * math.sin(2 * math.pi * 1.25 * now)), False))
            nxt += 0.01
            time.sleep(max(0.0, nxt - time.monotonic()))

    threading.Thread(target=feed, daemon=True).start()
    for frame in app.frames.values():
        panel = getattr(frame, "rx_panel", None)
        if panel is not None:
            panel.receiver = rx

    renders, gui = [], []
    items = []
    original_render = trace_view.LaneView.render

    def timed_render(self):
        t = time.perf_counter()
        original_render(self)
        renders.append(time.perf_counter() - t)
        items.append(len(self.find_all()))

    trace_view.LaneView.render = timed_render
    original_gui = CTkApp.update_gui

    def timed_gui(self):
        t = time.perf_counter()
        original_gui(self)
        gui.append(time.perf_counter() - t)

    CTkApp.update_gui = timed_gui

    engine = SignalEngine.get_instance()
    results = {"host": os.uname().machine, "geometry": args.geometry, "seconds": args.seconds, "pages": {}}
    pages = args.pages.split(",")
    state = {}

    def finish_page(page):
        wall = time.monotonic() - state["wall0"]
        cpu1 = thread_cpu()
        busy = {tid: cpu1[tid][0] - state["cpu0"].get(tid, (0, ""))[0] for tid in cpu1}
        results["pages"][page] = {
            "process_cpu_pct_of_one_core": round(100 * sum(busy.values()) / wall, 1),
            "ui_thread_cpu_pct": round(100 * busy.get(str(os.getpid()), 0) / wall, 1),
            "renders_per_s": round(len(renders) / wall, 1),
            "render_ms_mean": round(1000 * statistics.fmean(renders), 2) if renders else 0,
            "render_ms_p95": round(1000 * sorted(renders)[int(.95 * (len(renders) - 1))], 2) if renders else 0,
            "canvas_items_per_render": round(statistics.fmean(items)) if items else 0,
            "update_gui_ms_mean": round(1000 * statistics.fmean(gui), 2) if gui else 0,
            "update_gui_ms_p95": round(1000 * sorted(gui)[int(.95 * (len(gui) - 1))], 2) if gui else 0,
            "update_gui_ms_p99": round(1000 * sorted(gui)[int(.99 * (len(gui) - 1))], 2) if gui else 0,
            "update_gui_ms_max": round(1000 * max(gui), 2) if gui else 0,
            "update_gui_per_s": round(len(gui) / wall, 1),
        }
        if page == "Pathology":
            stats = engine.get_stats()
            results["pages"][page]["engine"] = {k: stats[k] for k in ("underruns", "overruns", "dropped_samples")}
            engine.stop_simulation()

    # Driven from Tk's own mainloop (as in the real app): a polling pump with update() would add its own load.
    def step(index=0, phase="show"):
        if phase == "show":
            if index >= len(pages):
                app.quit()
                return
            app._show_frame(pages[index])
            app.after(1000, step, index, "measure")      # settle
        elif phase == "measure":
            if pages[index] == "Pathology":
                engine.start_simulation()
            renders.clear(), gui.clear(), items.clear()
            state["cpu0"], state["wall0"] = thread_cpu(), time.monotonic()
            if args.profile:
                state["prof"] = cProfile.Profile()
                state["prof"].enable()
            app.after(int(args.seconds * 1000), step, index, "done")
        else:
            if args.profile:
                state["prof"].disable()
                out = io.StringIO()
                pstats.Stats(state["prof"], stream=out).sort_stats("tottime").print_stats(14)
                print(f"##### {pages[index]}\n" + "\n".join(l[:150] for l in out.getvalue().splitlines()[4:24]), file=sys.stderr)
            finish_page(pages[index])
            step(index + 1, "show")

    app.after(1500, step)
    try:
        app.mainloop()
    finally:
        stop.set()
        app.destroy()
    text = json.dumps(results, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text)


if __name__ == "__main__":
    main()
