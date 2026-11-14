"""RED step 0->1500 mV, 6 trials: A0 (RED RX), A4 (IR RX, dark, sees RED stray light) and DAC 0x60 readback."""
import json, sys, time, statistics as st
from smbus2 import SMBus, i2c_msg
ADC, FS = 0x08, 3280.0
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
dac = lambda a, c: bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
def mv(ch):
    bus.write_byte(ADC, 0x20 + ch); return bus.read_word_data(ADC, 0x20 + ch)
def readback(a):
    m = i2c_msg.read(a, 5); bus.i2c_rdwr(m); b = list(m); return (b[1] << 4) | (b[2] >> 4)
out = []
try:
    dac(0x60, 0); dac(0x61, 0); time.sleep(2)
    for trial in range(6):
        pre = [mv(4) for _ in range(300)]
        rows = []; t0 = time.monotonic(); dac(0x60, code(1500))
        while time.monotonic() - t0 < 10:
            t = time.monotonic() - t0
            rows.append((round(t, 4), mv(0), mv(4), readback(0x60) if len(rows) % 50 == 0 else None))
        dac(0x60, 0)
        on = next((t for t, a0, a4, _ in rows if a0 > 300), None)
        dark = [a4 for t, a0, a4, _ in rows if a0 < 30]
        lit = [a4 for t, a0, a4, _ in rows if a0 > 300]
        rb = {r for *_, r in rows if r is not None}
        print(f"trial {trial}: A0>300 at {on}s; A4 before {st.mean(pre):.2f}, while A0 dark {st.mean(dark) if dark else float('nan'):.2f} (n={len(dark)}), "
              f"while A0 lit {st.mean(lit) if lit else float('nan'):.2f}; DAC readback codes {sorted(rb)} (want {code(1500)})", flush=True)
        out.append(dict(pre=pre, rows=rows)); time.sleep(4)
finally:
    dac(0x60, 0); dac(0x61, 0); json.dump(out, open(sys.argv[1], "w"))
