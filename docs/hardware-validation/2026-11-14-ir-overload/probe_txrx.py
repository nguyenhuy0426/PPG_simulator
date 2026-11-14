"""Bench probe: DAC->LED->OPT101->Grove ADC, read three ways. Parks both DACs at 0 on exit.

Usage: python probe_txrx.py OUT.json [--max-mv 3000]
"""
import json, sys, time, statistics as st
from smbus2 import SMBus, i2c_msg

ADC = 0x08
DACS = (0x60, 0x61)
CHS = (0, 4)
FS_MV = 3280.0
out_path = sys.argv[1]
max_mv = float(sys.argv[sys.argv.index("--max-mv") + 1]) if "--max-mv" in sys.argv else 3000.0
bus = SMBus(1)


def code(mv):
    return max(0, min(4095, int(round(mv / FS_MV * 4095))))


def dac(addr, c):
    bus.write_byte_data(addr, (c >> 8) & 0x0F, c & 0xFF)  # MCP4725 fast write


def dac_readback(addr):
    m = i2c_msg.read(addr, 5)
    bus.i2c_rdwr(m)
    b = list(m)
    return {"dac": (b[1] << 4) | (b[2] >> 4), "eeprom": ((b[3] & 0x0F) << 8) | b[4], "pd": (b[0] >> 1) & 3}


def r_word(reg):          # vendor: STOP-terminated select, then SMBus read word (repeated start)
    bus.write_byte(ADC, reg)
    return bus.read_word_data(ADC, reg), None


def r_block3(reg):        # codex: select + read_i2c_block_data 3 bytes
    bus.write_byte(ADC, reg)
    b = bus.read_i2c_block_data(ADC, reg, 3)
    return b[0] | (b[1] << 8), b[2]


def r_plain3(reg):        # select with STOP, then a plain read (no register byte resent)
    bus.write_byte(ADC, reg)
    m = i2c_msg.read(ADC, 3)
    bus.i2c_rdwr(m)
    b = list(m)
    return b[0] | (b[1] << 8), b[2]


METHODS = {"word": r_word, "block3": r_block3, "plain3": r_plain3}


def sample(ch, n=20):
    res = {}
    for name, fn in METHODS.items():
        for kind, base in (("raw", 0x10), ("mv", 0x20)):
            vals, thirds = [], []
            for _ in range(n):
                try:
                    v, t = fn(base + ch)
                    vals.append(v); thirds.append(t)
                except OSError as e:
                    vals.append(None); thirds.append(str(e))
            res[f"{name}_{kind}"] = {"v": vals, "third": thirds}
    return res


def summ(vals):
    v = [x for x in vals if isinstance(x, int)]
    return (min(v), int(st.median(v)), max(v)) if v else None


log = {"meta": {"t": time.time(), "max_mv": max_mv}, "readback": {}, "map": [], "sweep": [], "hold": []}
try:
    for a in DACS:
        dac(a, 0)
    time.sleep(0.3)
    log["readback"]["after_zero"] = {hex(a): dac_readback(a) for a in DACS}
    # A. mapping
    for label, codes in (("both_off", (0, 0)), ("0x60_on", (code(1000), 0)), ("0x61_on", (0, code(1000)))):
        dac(0x60, codes[0]); dac(0x61, codes[1]); time.sleep(0.4)
        row = {"label": label, "rb": {hex(a): dac_readback(a)["dac"] for a in DACS}}
        for ch in CHS:
            row[f"A{ch}"] = sample(ch, 10)
        log["map"].append(row)
        print(label, row["rb"], {f"A{ch}": summ(row[f"A{ch}"]["word_mv"]["v"]) for ch in CHS}, flush=True)
    # B. static sweep, one DAC at a time
    for a in DACS:
        for mv in range(0, int(max_mv) + 1, 100):
            dac(0x60, 0); dac(0x61, 0)
            dac(a, code(mv)); time.sleep(0.25)
            row = {"dac": hex(a), "mv": mv, "code": code(mv), "rb": dac_readback(a)["dac"]}
            for ch in CHS:
                row[f"A{ch}"] = sample(ch, 12)
            log["sweep"].append(row)
            print(hex(a), mv, "rb", row["rb"], " ".join(
                f"A{ch}:w{summ(row[f'A{ch}']['word_mv']['v'])} b3{summ(row[f'A{ch}']['block3_mv']['v'])}"
                f" raw_b3{summ(row[f'A{ch}']['block3_raw']['v'])} raw_p3{summ(row[f'A{ch}']['plain3_raw']['v'])}"
                for ch in CHS), flush=True)
        dac(a, 0); time.sleep(0.5)
    # C. hold each DAC at a mid level for 20 s, log mV at ~40 Hz on both channels
    for a in DACS:
        dac(0x60, 0); dac(0x61, 0); time.sleep(0.5)
        dac(a, code(1500))
        t0 = time.monotonic()
        while time.monotonic() - t0 < 20:
            row = {"dac": hex(a), "t": time.monotonic() - t0}
            for ch in CHS:
                row[f"A{ch}"] = r_word(0x20 + ch)[0]
            log["hold"].append(row)
            time.sleep(0.02)
        hs = [r for r in log["hold"] if r["dac"] == hex(a)]
        for ch in CHS:
            v = [r[f"A{ch}"] for r in hs]
            print(f"hold {hex(a)} A{ch}: first1s {st.median(v[:40])} last1s {st.median(v[-40:])} min {min(v)} max {max(v)}", flush=True)
finally:
    for a in DACS:
        try:
            dac(a, 0)
        except OSError:
            pass
    json.dump(log, open(out_path, "w"))
    print("saved", out_path, "DACs parked at 0")
