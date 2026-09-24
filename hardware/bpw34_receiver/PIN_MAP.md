# BPW34 receiver pin map

| Reference | Pin | Net | Purpose |
|---|---:|---|---|
| D1 | 1 / K | SUM_RED | RED photodiode cathode to TIA summing node |
| D1 | 2 / A | GND_RED | RED photodiode anode |
| D2 | 1 / K | SUM_IR | IR photodiode cathode to TIA summing node |
| D2 | 2 / A | GND_IR | IR photodiode anode |
| U1/U2 | 1 | FB_RED / FB_IR | op-amp output before 100 ohm isolation resistor |
| U1/U2 | 2 | GND_RED / GND_IR | negative supply |
| U1/U2 | 3 | VREF_RED / VREF_IR | non-inverting input, approximately 0.30 V |
| U1/U2 | 4 | SUM_RED / SUM_IR | inverting input |
| U1/U2 | 5 | 3V3_RED / 3V3_IR | positive supply |
| J1 | 1,2,3,4 | OUT_RED, NC, 3V3_RED, GND_RED | Grove A2 |
| J2 | 1,2,3,4 | OUT_IR, NC, 3V3_IR, GND_IR | Grove A0 |
| J3 | 1,2,3,4 | OUT_RED, GND_RED, OUT_IR, GND_IR | ADS1115 signal/return pairs |
