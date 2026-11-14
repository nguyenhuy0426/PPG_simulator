"""IR <-> RED crosstalk and per-lane gain/offset at DC. Static DAC pairs, median of 200 reads each.
App stopped: python xtalk.py"""
import time, statistics as st
from smbus2 import SMBus
bus = SMBus(1); ADC = 0x08; FS = 3280.0
code = lambda mv: int(round(mv / FS * 4095))
def dac(a, mv): c = code(mv); bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
def rd(ch): bus.write_byte(ADC, 0x20 + ch); return bus.read_word_data(ADC, 0x20 + ch)
def med(ch): return st.median(rd(ch) for _ in range(200))
try:
    for ir, red in ((0, 0), (1000, 0), (0, 1000), (1000, 1000), (1050, 1000), (950, 1000), (1000, 1050), (1000, 950),
                    (800, 0), (1200, 0), (0, 800), (0, 1200), (0, 0)):
        dac(0x61, ir); dac(0x60, red); time.sleep(0.8)
        print(f"IR DAC {ir:5d}  RED DAC {red:5d}  ->  A4 {med(4):6.1f}  A0 {med(0):6.1f}", flush=True)
finally:
    dac(0x60, 0); dac(0x61, 0); print("parked")
