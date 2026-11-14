"""RED vs IR turn-on at the same instant. Both DACs 0 -> 1000 mV together, A0/A4 logged ~400 Hz for 15 s.
Trials 1-4 plain step; trials 5-8 RED kicked to 2000 mV (10 mA, below the 20 mA LED max) for 50 ms first.
Run with the app stopped: python probe9.py out.json"""
import json, sys, time
from smbus2 import SMBus, i2c_msg
ADC, FS = 0x08, 3280.0
RED, IR = 0x60, 0x61
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
def dac(a, c): bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
def dac_read(a):
    m = i2c_msg.read(a, 3); bus.i2c_rdwr(m); b = list(m); return ((b[1] << 4) | (b[2] >> 4))
def mv(ch):
    bus.write_byte(ADC, 0x20 + ch); return bus.read_word_data(ADC, 0x20 + ch)
log = []
try:
    for trial in range(8):
        dac(RED, 0); dac(IR, 0); time.sleep(4)
        dark = (mv(0), mv(4))
        kick = trial >= 4
        t0 = time.monotonic()
        if kick:
            dac(RED, code(2000)); dac(IR, code(1000)); time.sleep(0.05); dac(RED, code(1000))
        else:
            dac(RED, code(1000)); dac(IR, code(1000))
        rows, rb = [], []
        while (t := time.monotonic() - t0) < 15:
            rows.append((round(t, 4), mv(0), mv(4)))
            if len(rows) % 200 == 0: rb.append((round(t, 2), dac_read(RED), dac_read(IR)))
        def first(idx, thr):
            return next((r[0] for r in rows if r[idx] >= thr), None)
        at = lambda s: [r for r in rows if r[0] >= s][0][1:]
        rec = dict(trial=trial, kick=kick, dark=dark, rows=rows, readback=rb,
                   red_200=first(1, 200), red_600=first(1, 600), ir_200=first(2, 200),
                   at={s: at(s) for s in (0.1, 0.5, 1, 2, 5, 10, 14.9)})
        log.append(rec)
        print(f"trial {trial} kick={kick} RED>200mV {rec['red_200']}s >600mV {rec['red_600']}s IR>200mV {rec['ir_200']}s",
              " ".join(f"{s}s:{v[0]}/{v[1]}" for s, v in rec['at'].items()),
              "readback", set((a, b) for _, a, b in rb), flush=True)
finally:
    dac(RED, 0); dac(IR, 0)
    json.dump(log, open(sys.argv[1], "w")); print("saved; DACs parked")
