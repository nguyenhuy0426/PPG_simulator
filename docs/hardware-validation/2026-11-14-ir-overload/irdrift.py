"""IR drift at a constant DAC code: is it heat/exposure dependent, does it reset after a rest, are the jumps real?
Phases (both lanes logged ~100 Hz, MCP4725 readback + CPU temp + under-voltage flag every 0.5 s):
  dark 30 s -> IR+RED 1000 mV 150 s (cold start) -> IR off 5 s -> on 30 s (warm restart)
  -> IR off 60 s -> on 30 s (rested restart) -> IR off 60 s -> IR 1000 mV pulsed 50 ms / 500 ms for 90 s
  -> IR off 60 s -> IR 300 mV 90 s. RED stays at 1000 mV throughout as the control lane.
Run with the app stopped (only client on the bus): python irdrift.py out.json"""
import json, sys, time
from smbus2 import SMBus, i2c_msg
ADC, FS = 0x08, 3280.0
RED, IR = 0x60, 0x61
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
def dac(a, c): bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)
def dac_read(a):
    m = i2c_msg.read(a, 3); bus.i2c_rdwr(m); b = list(m); return (b[1] << 4) | (b[2] >> 4)
def mv(ch):
    bus.write_byte(ADC, 0x20 + ch); return bus.read_word_data(ADC, 0x20 + ch)
def sysinfo():
    t = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    try: uv = int(open("/sys/class/hwmon/hwmon1/in0_lcrit_alarm").read())
    except OSError: uv = None
    return t, uv

T0 = time.monotonic()
rows, info, marks, pulses = [], [], [], []
last_info = [0.0]
def log_for(seconds, period=0.01):
    end = time.monotonic() + seconds
    while (now := time.monotonic()) < end:
        rows.append((round(now - T0, 4), mv(0), mv(4)))
        if now - last_info[0] >= 0.5:
            last_info[0] = now
            info.append((round(now - T0, 2), dac_read(IR), dac_read(RED)) + sysinfo())
        time.sleep(max(0.0, period - (time.monotonic() - now)))
def phase(name, ir_mv, seconds):
    dac(IR, code(ir_mv)); marks.append((name, round(time.monotonic() - T0, 3), ir_mv)); log_for(seconds)
    print(f"{name}: done at {time.monotonic() - T0:.0f} s", flush=True)

try:
    dac(IR, 0); dac(RED, 0); marks.append(("dark", 0.0, 0)); log_for(30)
    dac(RED, code(1000))
    phase("cold_1000", 1000, 150)
    phase("off_5", 0, 5)
    phase("warm_1000", 1000, 30)
    phase("off_60", 0, 60)
    phase("rested_1000", 1000, 30)
    phase("off_60b", 0, 60)
    marks.append(("pulsed_1000", round(time.monotonic() - T0, 3), 1000))
    end = time.monotonic() + 90
    while time.monotonic() < end:
        t_on = time.monotonic(); dac(IR, code(1000)); time.sleep(0.03)
        reads = [mv(4) for _ in range(5)]
        dac(IR, 0); time.sleep(0.03); dark = mv(4)
        pulses.append((round(t_on - T0, 3), reads, dark, mv(0)))
        time.sleep(max(0.0, 0.5 - (time.monotonic() - t_on)))
    print("pulsed: done", flush=True)
    phase("off_60c", 0, 60)
    phase("hold_300", 300, 90)
finally:
    dac(RED, 0); dac(IR, 0)
    json.dump(dict(marks=marks, rows=rows, info=info, pulses=pulses), open(sys.argv[1], "w"))
    print("saved; DACs parked", len(rows), "rows")
