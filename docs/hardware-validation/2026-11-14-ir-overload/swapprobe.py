"""Grove HAT channel cross-talk: IR DAC 600 mV, RED DAC 1500 mV (well apart), read A4/A0 alternately as the app
does (write_byte pointer, then read_word), with a wait between pointer write and read. Counts samples that
carry the other channel's level. App stopped: python swapprobe.py"""
import time, statistics as st
from smbus2 import SMBus
bus = SMBus(1); ADC = 0x08; FS = 3280.0
code = lambda mv: int(round(mv / FS * 4095))
def dac(a, c): bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
def wait(s):
    end = time.perf_counter() + s
    while time.perf_counter() < end: pass
def rd(ch, gap):
    bus.write_byte(ADC, 0x20 + ch)
    if gap: wait(gap)
    return bus.read_word_data(ADC, 0x20 + ch)
try:
    dac(0x61, code(600)); dac(0x60, code(1500)); time.sleep(1.5)
    ref4 = st.median(rd(4, 0.002) for _ in range(50)); ref0 = st.median(rd(0, 0.002) for _ in range(50))
    print(f"levels (2 ms wait): A4 {ref4} mV, A0 {ref0} mV", flush=True)
    mid = (ref4 + ref0) / 2
    for gap in (0, 50e-6, 100e-6, 200e-6, 500e-6, 1e-3):
        n, bad4, bad0 = 3000, 0, 0
        t0 = time.perf_counter()
        for _ in range(n):
            a4 = rd(4, gap); a0 = rd(0, gap)
            bad4 += (a4 > mid) if ref4 < mid else (a4 < mid)
            bad0 += (a0 < mid) if ref0 > mid else (a0 > mid)
        rate = 2 * n / (time.perf_counter() - t0)
        print(f"wait {gap*1e6:5.0f} us: A4 wrong {bad4}/{n} ({100*bad4/n:.2f} %), A0 wrong {bad0}/{n} ({100*bad0/n:.2f} %), {rate:.0f} reads/s", flush=True)
finally:
    dac(0x60, 0); dac(0x61, 0); print("parked")
