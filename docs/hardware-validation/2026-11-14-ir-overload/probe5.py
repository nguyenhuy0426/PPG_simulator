"""RED turn-on: DAC 0 -> 1000 mV step, A0 read as fast as possible for 12 s, three times; also IR."""
import json, sys, time, statistics as st
from smbus2 import SMBus
ADC, FS = 0x08, 3280.0
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
dac = lambda a, c: bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
def mv(ch):
    bus.write_byte(ADC, 0x20 + ch); return bus.read_word_data(ADC, 0x20 + ch)
out = {}
try:
    dac(0x60, 0); dac(0x61, 0); time.sleep(2)
    for name, a, ch in (("red1", 0x60, 0), ("red2", 0x60, 0), ("ir", 0x61, 4), ("red3", 0x60, 0)):
        rows = []; t0 = time.monotonic(); dac(a, code(1000))
        while time.monotonic() - t0 < 12:
            rows.append((round(time.monotonic() - t0, 4), mv(ch)))
        dac(a, 0); out[name] = rows
        def at(t): return st.median(v for tt, v in rows if t <= tt < t + 0.2)
        first = next((tt for tt, v in rows if v > 100), None)
        print(name, "first>100mV at", first, "s; median @0,0.5,1,2,4,8,11.5s:",
              [round(at(t)) for t in (0, 0.5, 1, 2, 4, 8, 11.5)], "rate", round(len(rows) / 12), "Hz", flush=True)
        time.sleep(3)
finally:
    dac(0x60, 0); dac(0x61, 0); json.dump(out, open(sys.argv[1], "w"))
