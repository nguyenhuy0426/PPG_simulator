"""RED turn-on delay: parked at 0 vs parked at a small bias, interleaved, 8 trials each."""
import json, sys, time
from smbus2 import SMBus
ADC, FS = 0x08, 3280.0
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
dac = lambda a, c: bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
def mv(ch):
    bus.write_byte(ADC, 0x20 + ch); return bus.read_word_data(ADC, 0x20 + ch)
res = {0: [], 100: [], 200: []}
try:
    dac(0x61, 0)
    for trial in range(8):
        for park in (0, 100, 200):
            dac(0x60, code(park)); time.sleep(4)
            base = sorted(mv(0) for _ in range(50))[25]
            t0 = time.monotonic(); dac(0x60, code(1500)); on = None
            while time.monotonic() - t0 < 8:
                if mv(0) > base + 300: on = round(time.monotonic() - t0, 3); break
            res[park].append(on); print(f"trial {trial} park {park} mV (A0 {base}) -> on after {on}s", flush=True)
finally:
    dac(0x60, 0); dac(0x61, 0); json.dump(res, open(sys.argv[1], "w"))
