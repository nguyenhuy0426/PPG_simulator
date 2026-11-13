# LED/IR driver — official shared-I²C design

Open `led_ir_driver.kicad_pro` in KiCad 10. This 70 × 40 mm board restores
the v1.9 shared-bus design. It has two MCP4725 module sockets, an LM358 and
two independent LED current drivers. The official two-board panel is in
[`../ppg_panel/`](../ppg_panel/README.md).

## I²C wiring

J2 uses two separate headers: 1×2 at 2.54 mm for pins 1–2 and 1×4 at
2.00 mm for pins 3–6. Connect the four-wire Pi/Grove I²C cable to pins **3–6**:

| J2 pin | Signal |
|---|---|
| 1 | IR DAC output |
| 2 | GND |
| 3 | SCL |
| 4 | SDA |
| 5 | 3.3 V |
| 6 | GND |

J1 (IR) and J3 (RED) share SCL, SDA, 3.3 V and GND. Their DAC outputs are
separate. Set the modules to distinct addresses: IR `0x60`, RED `0x61`;
verify the module variant and ADDR solder links. Use 3.3 V on the I²C header,
not 5 V. The driver 5 V supply and Pi must share GND. Check the actual cable
pin order before connecting. J8/J9, R11–R14 and JP1–JP4 from v2.0 are absent.
Module pull-ups are in parallel; check the resulting bus electrically.

See [connectivity review](CONNECTIVITY_REVIEW.md), [pin map](PIN_MAP.md) and
[electrical audit](ELECTRICAL_AUDIT.md) for circuit details. These documents
correspond to the restored v1.9 source and include historical observations.

## Verification and fabrication

The restored driver passed KiCad ERC, PCB DRC and schematic parity checks.
The later v2.0 board-house changes (0.5 mm ground-pour clearance and 1.5 mm
I²C-header pads) have not been applied to this restored version. There is no
current manufacturing release: verify clearances, pad sizes, mechanics and
board-house requirements, then regenerate and inspect Gerbers and drills.
Check current, startup behavior and stability on assembled hardware; CAD
checks do not prove electrical operation. The MCP4725 may restore a nonzero
EEPROM output at startup.
