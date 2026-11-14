"""RED alone 0 -> 1000 mV, IR DAC held at 0: does A0 drop below its dark level while RED is commanded but
unlit, and does A4 (IR OPT101, dark) move with it? 10 trials x 10 s. App stopped: python probe10.py out.json"""
import json, sys, time, statistics as st
from smbus2 import SMBus
ADC, FS, RED, IR = 0x08, 3280.0, 0x60, 0x61
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
def dac(a, c): bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
def mv(ch):
    bus.write_byte(ADC, 0x20 + ch); return bus.read_word_data(ADC, 0x20 + ch)
log = []
try:
    dac(IR, 0)
    for trial in range(10):
        dac(RED, 0); time.sleep(3)
        pre = [(mv(0), mv(4)) for _ in range(200)]
        t0 = time.monotonic(); dac(RED, code(1000)); rows = []
        while (t := time.monotonic() - t0) < 10:
            rows.append((round(t, 4), mv(0), mv(4)))
        lit = next((r[0] for r in rows if r[1] >= 200), None)
        unlit = [r for r in rows if lit is None or r[0] < lit]
        m = lambda v: round(st.mean(v), 2) if v else None
        rec = dict(trial=trial, lit=lit, pre_a0=m([a for a, _ in pre]), pre_a4=m([b for _, b in pre]),
                   unlit_a0=m([r[1] for r in unlit]), unlit_a4=m([r[2] for r in unlit]),
                   lit_a0=m([r[1] for r in rows if lit is not None and r[0] >= lit]),
                   lit_a4=m([r[2] for r in rows if lit is not None and r[0] >= lit]), rows=rows)
        log.append(rec)
        print({k: v for k, v in rec.items() if k != "rows"}, flush=True)
finally:
    dac(RED, 0); dac(IR, 0); json.dump(log, open(sys.argv[1], "w")); print("saved; DACs parked")
