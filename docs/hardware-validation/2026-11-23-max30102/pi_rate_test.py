# Standalone flicker (smbus2) at a capped write rate: does the MAX30102 HR depend on the toggle rate?
import os, sys, time, math
sys.path.insert(0, os.getcwd())
pass  # app may be running
from smbus2 import SMBus
from config import DAC_ADDR_IR, DAC_ADDR_RED, DAC_FULLSCALE_MV, DAC_MAX_VALUE
def code(mv): return max(0, min(DAC_MAX_VALUE, int(round(mv / DAC_FULLSCALE_MV * DAC_MAX_VALUE))))
def pulse(ph): return (math.exp(-((ph-0.20)/0.07)**2) + 0.45*math.exp(-((ph-0.48)/0.10)**2)) / 1.0005
with SMBus(1) as bus:
    w = lambda a, c: bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
    try:
        w(DAC_ADDR_IR, 0); w(DAC_ADDR_RED, 0)
        print(f"{time.time():.3f} dark 6 s", flush=True); time.sleep(6)
        for rate in [float(r) for r in sys.argv[1:]]:
            print(f"{time.time():.3f} flicker on: HR 75 rate {rate:.0f}", flush=True)
            t0 = time.perf_counter(); n = 0; on = False; nxt = t0
            while (t := time.perf_counter()) - t0 < 30:
                if rate > 0:
                    if t < nxt: continue
                    nxt += 1.0 / rate
                on = not on
                w(DAC_ADDR_RED, code(600 + 300 * pulse(((t - t0) * 75 / 60) % 1.0)) if on else 0); n += 1
            print(f"{time.time():.3f} flicker off: {n/30:.0f} writes/s", flush=True)
            w(DAC_ADDR_RED, 0); time.sleep(3)
    finally:
        w(DAC_ADDR_RED, 0); w(DAC_ADDR_IR, 0); print("DACs parked", flush=True)
