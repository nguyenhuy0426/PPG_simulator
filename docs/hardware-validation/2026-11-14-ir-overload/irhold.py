"""Highest IR DAC level that holds: IR alone held 60 s at each level after a 45 s rest, RED off, ~50 Hz log.
Run with the app stopped: python irhold.py out.json"""
import json, sys, time
from smbus2 import SMBus, i2c_msg
ADC, FS, RED, IR = 0x08, 3280.0, 0x60, 0x61
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
def dac(a, c): bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
def dac_read(a):
    m = i2c_msg.read(a, 3); bus.i2c_rdwr(m); b = list(m); return (b[1] << 4) | (b[2] >> 4)
def mv(ch):
    bus.write_byte(ADC, 0x20 + ch); return bus.read_word_data(ADC, 0x20 + ch)
out = []
try:
    dac(RED, 0)
    for level in (450, 600, 750, 900):
        dac(IR, 0); time.sleep(45)
        dac(IR, code(level)); t0 = time.monotonic(); rows = []
        while (t := time.monotonic() - t0) < 60:
            rows.append((round(t, 3), mv(4))); time.sleep(0.02)
        out.append(dict(level=level, readback=dac_read(IR), rows=rows))
        s = lambda a, b: sorted(v for tt, v in rows if a <= tt < b)
        med = lambda a, b: s(a, b)[len(s(a, b)) // 2]
        print(f"IR {level} mV (code {out[-1]['readback']}): 0-1s {med(0, 1)}  10s {med(9, 11)}  30s {med(29, 31)}  58-60s {med(58, 60)}", flush=True)
finally:
    dac(IR, 0); dac(RED, 0); json.dump(out, open(sys.argv[1], "w")); print("saved; DACs parked")
