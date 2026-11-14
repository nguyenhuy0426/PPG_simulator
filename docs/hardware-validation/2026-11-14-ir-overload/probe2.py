"""Pulse transfer + low-level hold + crosstalk. Voltage register only (verified reliable). Parks DACs at 0."""
import json, sys, time, statistics as st
from smbus2 import SMBus

ADC, FS = 0x08, 3280.0
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
dac = lambda a, c: bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)


def mv(ch):
    bus.write_byte(ADC, 0x20 + ch)
    return bus.read_word_data(ADC, 0x20 + ch)


PAIR = {0x60: 0, 0x61: 4}
log = {"pulse": [], "hold": [], "xtalk": []}
try:
    dac(0x60, 0); dac(0x61, 0); time.sleep(5)
    # 1. pulse transfer: 40 ms on, read, 1.2 s off
    for a, ch in PAIR.items():
        for lvl in list(range(100, 1001, 100)) + list(range(1250, 3001, 250)):
            dark = mv(ch)
            dac(a, code(lvl)); time.sleep(0.040)
            v = [mv(ch) for _ in range(3)]
            dac(a, 0)
            log["pulse"].append({"dac": hex(a), "mv": lvl, "dark": dark, "v": v})
            print(f"pulse {hex(a)} {lvl:5d} mV -> A{ch} {st.median(v):5.0f} (dark {dark})", flush=True)
            time.sleep(1.2)
        time.sleep(5)
    # 2. hold at low and mid level, 15 s each, 5 s off between
    for a, ch in PAIR.items():
        for lvl in (300, 600):
            dac(a, code(lvl)); t0 = time.monotonic(); s = []
            while time.monotonic() - t0 < 15:
                s.append((time.monotonic() - t0, mv(ch))); time.sleep(0.05)
            dac(a, 0)
            log["hold"].append({"dac": hex(a), "mv": lvl, "s": s})
            f = [v for t, v in s if t < 0.5]; l = [v for t, v in s if t > 14]
            print(f"hold {hex(a)} {lvl} mV A{ch}: first {st.median(f):.0f} last {st.median(l):.0f} ({100*(st.median(l)/st.median(f)-1):+.1f} %)", flush=True)
            time.sleep(8)
    # 3. crosstalk: IR at 300 mV steady, RED toggled to 1500 mV
    dac(0x61, code(300)); time.sleep(3)
    for state in (0, 1500, 0, 1500, 0):
        dac(0x60, code(state)); time.sleep(1.0)
        v4 = [mv(4) for _ in range(10)]; v0 = [mv(0) for _ in range(5)]
        log["xtalk"].append({"red": state, "A4": v4, "A0": v0})
        print(f"xtalk RED={state:4d}: A4 {st.median(v4):.0f} A0 {st.median(v0):.0f}", flush=True)
finally:
    dac(0x60, 0); dac(0x61, 0)
    json.dump(log, open(sys.argv[1], "w"))
    print("saved; DACs parked at 0")
