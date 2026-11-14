import time
from smbus2 import SMBus, i2c_msg
bus = SMBus(1)
def rb(a):
    m = i2c_msg.read(a, 5); bus.i2c_rdwr(m); b = list(m); return (b[1] << 4) | (b[2] >> 4)
for a in (0x60, 0x61):
    codes = []
    for _ in range(40):
        try: codes.append(rb(a))
        except OSError as e: codes.append(None)
        time.sleep(0.025)
    ok = [c for c in codes if c is not None]
    print(hex(a), "codes min/max", min(ok), max(ok), "->", round(min(ok)/4095*3280), "-", round(max(ok)/4095*3280), "mV; errors", codes.count(None))
