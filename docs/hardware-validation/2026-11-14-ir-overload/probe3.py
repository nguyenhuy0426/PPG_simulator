"""RED/IR turn-on behaviour and ceilings. Voltage register only. Parks DACs at 0."""
import json, sys, time, statistics as st
from smbus2 import SMBus, i2c_msg

ADC, FS = 0x08, 3280.0
RED, IR = (0x60, 0), (0x61, 4)
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
dac = lambda a, c: bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)


def mv(ch):
    bus.write_byte(ADC, 0x20 + ch)
    return bus.read_word_data(ADC, 0x20 + ch)


def readback(a):
    m = i2c_msg.read(a, 5); bus.i2c_rdwr(m); b = list(m)
    return (b[1] << 4) | (b[2] >> 4)


log = {"turnon": [], "ramp": [], "ceiling": []}
try:
    dac(0x60, 0); dac(0x61, 0); time.sleep(3)
    # 1. turn-on from long off: RX every ~5 ms for 3 s
    for (a, ch), lvl in [(RED, 300), (RED, 300), (RED, 600), (RED, 600), (RED, 1000), (RED, 1000),
                         (RED, 300), (IR, 150), (IR, 150)]:
        dark = st.median(mv(ch) for _ in range(5))
        dac(a, code(lvl)); t0 = time.monotonic(); s = []
        while (t := time.monotonic() - t0) < 3.0:
            s.append((round(t, 4), mv(ch)))
        rb = readback(a)
        dac(a, 0)
        on = next((t for t, v in s if v > dark + 60), None)
        final = st.median(v for t, v in s if t > 2.5)
        log["turnon"].append({"dac": hex(a), "mv": lvl, "dark": dark, "readback": rb, "on_s": on, "final": final, "s": s})
        print(f"turn-on {hex(a)} {lvl:4d} mV: readback {rb} (want {code(lvl)}), dark {dark}, on after "
              f"{'never' if on is None else f'{on*1000:.0f} ms'}, final {final}", flush=True)
        time.sleep(3)
    # 2. slow ramp up then down (hysteresis), 25 mV steps, 0.3 s each, no off gaps
    for a, ch in (RED,):
        for lvl in list(range(0, 1301, 25)) + list(range(1300, -1, -25)):
            dac(a, code(lvl)); time.sleep(0.3)
            log["ramp"].append((lvl, st.median(mv(ch) for _ in range(3))))
        dac(a, 0)
        up = dict(log["ramp"][:53]); down = dict(log["ramp"][53:])
        print("ramp RED up/down:", " ".join(f"{l}:{up[l]:.0f}/{down[l]:.0f}" for l in range(0, 1301, 100)), flush=True)
    time.sleep(3)
    # 3. ceilings: short pulses at high drive
    for (a, ch), lvls in ((RED, (1800, 2000, 2200, 2500, 2800)), (IR, (650, 700, 800))):
        for lvl in lvls:
            dac(a, code(lvl)); time.sleep(0.04)
            v = st.median(mv(ch) for _ in range(5)); dac(a, 0)
            log["ceiling"].append((hex(a), lvl, v)); print(f"ceiling {hex(a)} {lvl} mV -> {v} mV", flush=True)
            time.sleep(1.5)
finally:
    dac(0x60, 0); dac(0x61, 0)
    json.dump(log, open(sys.argv[1], "w"))
    print("saved; DACs parked")
