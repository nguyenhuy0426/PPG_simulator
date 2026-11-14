"""IR ~700 mV ceiling: staircase, RED-load interaction, hold sag, idle channels. Parks DACs at 0.

Run with the app stopped (only client on the bus): python probe4.py out.json
"""
import json, sys, time, statistics as st
from smbus2 import SMBus

ADC, FS = 0x08, 3280.0
RED, IR = (0x60, 0), (0x61, 4)
bus = SMBus(1)
code = lambda mv: max(0, min(4095, int(round(mv / FS * 4095))))
dac = lambda a, c: bus.write_byte_data(a, (c >> 8) & 0x0F, c & 0xFF)


def mv(ch):
    bus.write_byte(ADC, 0x20 + ch)
    return bus.read_word_data(ADC, 0x20 + ch)


def med(ch, n=5):
    return st.median(mv(ch) for _ in range(n))


log = {"idle": {}, "ir_up": [], "ir_down": [], "red_up": [], "load": [], "hold": []}
try:
    dac(*[RED[0], 0]); dac(IR[0], 0); time.sleep(1)
    log["idle"] = {ch: med(ch) for ch in range(8)}
    print("idle all channels:", log["idle"], flush=True)
    # 1. IR staircase up and down, RED off
    for lvl in range(0, 2001, 50):
        dac(IR[0], code(lvl)); time.sleep(0.25); log["ir_up"].append((lvl, med(4)))
    for lvl in range(2000, -1, -50):
        dac(IR[0], code(lvl)); time.sleep(0.25); log["ir_down"].append((lvl, med(4)))
    dac(IR[0], 0)
    print("IR up  :", " ".join(f"{l}:{v:.0f}" for l, v in log["ir_up"][::2]), flush=True)
    print("IR down:", " ".join(f"{l}:{v:.0f}" for l, v in log["ir_down"][::2]), flush=True)
    time.sleep(3)
    # 2. RED staircase for reference
    for lvl in range(0, 2501, 100):
        dac(RED[0], code(lvl)); time.sleep(0.25); log["red_up"].append((lvl, med(0)))
    dac(RED[0], 0)
    print("RED up :", " ".join(f"{l}:{v:.0f}" for l, v in log["red_up"]), flush=True)
    time.sleep(3)
    # 3. Does RED drawing current change the IR ceiling? (shared 5 V / LM358)
    for ir_lvl in (400, 1500):
        for red_lvl in (0, 2500, 0):
            dac(RED[0], code(red_lvl)); dac(IR[0], code(ir_lvl)); time.sleep(0.5)
            log["load"].append((ir_lvl, red_lvl, med(4, 9), med(0, 5)))
            print(f"load IR {ir_lvl} RED {red_lvl}: A4 {log['load'][-1][2]:.0f} A0 {log['load'][-1][3]:.0f}", flush=True)
        dac(IR[0], 0); dac(RED[0], 0); time.sleep(2)
    # 4. Hold IR at 1500 mV for 15 s
    dac(IR[0], code(1500)); t0 = time.monotonic()
    while time.monotonic() - t0 < 15:
        log["hold"].append((round(time.monotonic() - t0, 2), med(4, 3))); time.sleep(0.2)
    dac(IR[0], 0)
    h = log["hold"]
    print("hold 1500:", " ".join(f"{t:.0f}s:{v:.0f}" for t, v in h[::10]), flush=True)
finally:
    dac(0x60, 0); dac(0x61, 0)
    json.dump(log, open(sys.argv[1], "w"))
    print("saved; DACs parked")
