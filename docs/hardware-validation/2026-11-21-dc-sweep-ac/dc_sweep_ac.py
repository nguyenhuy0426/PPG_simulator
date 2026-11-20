"""DC sweep at a fixed AC on the real DACs/ADC: Classic output, TX commanded and RX received kept per step.

Usage (from the app directory, with the app stopped; it takes the app's instance lock):
    .venv/bin/python dc_sweep_ac.py OUT.json [--start 300 --stop 1500 --step 50 --seconds 15 --ac 45]

The saved config (HR, SpO2, RR, noise ...) is the base; IR and RED get the same DC at each step and the AC
stays fixed on both. The output runs without a stop between steps. TX is the commanded voltage the generator
wrote (not a measured DAC voltage). Both DACs are parked at 0 V on exit.
"""
import argparse
import json
import os
import statistics as st
import sys
import time

sys.path.insert(0, os.getcwd())
import instance_lock  # noqa: E402
instance_lock.acquire()
from config import ADC_CHANNEL_IR, ADC_CHANNEL_RED  # noqa: E402
from config_store import apply_config_to_params, load_config  # noqa: E402
from core.signal_engine import SignalEngine  # noqa: E402
from hw.opt101_rx import OPT101Receiver, raw_to_millivolts  # noqa: E402

CHANNELS = (("IR", ADC_CHANNEL_IR), ("RED", ADC_CHANNEL_RED))
POLL_S = 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--start", type=float, default=300.0)
    ap.add_argument("--stop", type=float, default=1500.0)
    ap.add_argument("--step", type=float, default=50.0)
    ap.add_argument("--seconds", type=float, default=15.0)
    ap.add_argument("--ac", type=float, default=45.0)
    ap.add_argument("--balance", action="store_true", help="run core.ac_balance (feedforward + loop) as the app does")
    args = ap.parse_args()
    levels = []
    dc = args.start
    while dc <= args.stop + 1e-6:
        levels.append(round(dc, 3))
        dc += args.step

    eng = SignalEngine.get_instance()
    rx = OPT101Receiver.get_instance()
    log = {"args": vars(args), "steps": [], "started": time.time()}
    try:
        eng.begin()
        if not eng.dac_manager.is_ready:
            raise SystemExit("DACs not ready")
        apply_config_to_params(load_config(), eng.ppg_params)
        p = eng.ppg_params
        p.lock_ac, p.lock_dc = False, False
        p.ac_ir_mv, p.ac_red_mv = args.ac, args.ac
        p.dc_ir_mv = p.dc_red_mv = levels[0]
        p.output_dc_offset_mv = 0.0
        if not rx.begin():
            raise SystemExit("ADC not ready")
        rx.start()
        log["base"] = {k: getattr(p, k) for k in ("heart_rate", "spo2", "resp_rate", "noise_level", "condition",
                                                    "spo2_coeff_a", "spo2_coeff_b", "ac_polarity")}
        eng.start_simulation(p.condition)
        balance = None
        if args.balance:
            from core.ac_balance import AcBalance
            balance = AcBalance(eng, rx)
        tx_last = -1.0
        for i, dc in enumerate(levels):
            eng.update_ac_dc(args.ac, dc, dc)
            eng.update_ac_levels(args.ac, args.ac)
            q = eng.ppg_params
            t0 = time.monotonic()
            hist = eng.get_display_history()
            tx_change = hist[-1][0] if hist else 0.0
            step = {"dc_mv": dc, "t0": t0, "tx_change_stamp": tx_change,
                    "set": {"dc_ir": q.dc_ir_mv, "dc_red": q.dc_red_mv, "ac_ir": q.ac_ir_mv, "ac_red": q.ac_red_mv,
                            "pi": q.perfusion_index},
                    "tx": [], "rx": {name: [] for name, _ in CHANNELS}}
            rx_last = {ch: t0 for _, ch in CHANNELS}
            while time.monotonic() - t0 < args.seconds:
                time.sleep(POLL_S)
                if balance is not None:
                    balance.tick()
                    step.setdefault("factors", []).append((time.monotonic(), *eng.ac_compensation))
                for row in eng.get_display_history():
                    if row[0] > tx_last:
                        step["tx"].append((row[0], row[1] * 1000.0, row[2] * 1000.0))
                        tx_last = row[0]
                for name, ch in CHANNELS:
                    new = [s for s in rx.get_samples_since(ch, rx_last[ch]) if s.timestamp > rx_last[ch]]
                    if new:
                        step["rx"][name] += [(s.timestamp, s.raw, bool(s.saturated)) for s in new]
                        rx_last[ch] = new[-1].timestamp
            step["engine"] = eng.get_stats()
            if balance is not None:
                step["balance"] = {n: {k: getattr(s, k) for k in ("feedforward", "trim", "ratio", "tx_ac", "rx_ac", "reason")}
                                   for n, s in balance.state.items()}
            step["adc_errors"] = {name: rx.error_count(ch) for name, ch in CHANNELS}
            log["steps"].append(step)
            late = {name: [raw_to_millivolts(r) for t, r, _s in step["rx"][name] if t >= t0 + 3.0]
                    for name, _ in CHANNELS}
            summary = "  ".join(
                f"{name} n={len(v)} med {st.median(v):6.0f} p5-p95 {sorted(v)[-len(v)//20] - sorted(v)[len(v)//20]:5.0f}"
                if len(v) > 50 else f"{name} n={len(v)}" for name, v in late.items())
            extra = "" if balance is None else " | k IR {:.3f} RED {:.3f} | loop {} {}".format(
                *eng.ac_compensation, balance.state["IR"].reason, balance.state["RED"].reason)
            print(f"DC {dc:6.0f} mV{extra} | set IR {q.dc_ir_mv:.0f}/{q.ac_ir_mv:.1f} RED {q.dc_red_mv:.0f}/{q.ac_red_mv} | "
                  f"tx {len(step['tx'])} | {summary}", flush=True)
    finally:
        try:
            eng.stop_simulation()
        finally:
            rx.shutdown()
            eng.shutdown()
            log["finished"] = time.time()
            with open(args.out, "w") as f:
                json.dump(log, f)
            print(f"saved {args.out}; DACs parked", flush=True)


if __name__ == "__main__":
    main()
