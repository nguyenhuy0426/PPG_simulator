# Official OPT101 + LED/IR driver panel

Open `ppg_panel.kicad_pro` in KiCad 10. This 70 × 60 mm, 1.6 mm thick,
two-layer panel contains one 70 × 20 mm OPT101 receiver and one 70 × 40 mm
shared-I²C LED/IR driver. Their nets are isolated. BPW34 is not included.

The outer rectangle is `Edge.Cuts`. One full-width V-score centre line is on
`Cmts.User`, 20 mm from the top (KiCad Y = 70 mm); it is not a milled slot.
Separate the bare boards before assembly. Confirm V-score depth, tolerances,
clearances and pricing for two designs with the board house.

To rebuild from the two source PCB files, run `build_panel.py` with KiCad 10
Python, then run `verify_panel.py` and KiCad DRC. The manifest records source
hashes. The independent audit checks source parity, electrical separation and
copper clearance from the score; CAD checks do not qualify a physical board.

The driver restores v1.9 and does not include later v2.0 manufacturing-rule
changes. Old three-board Gerbers and assembly files are obsolete and have
been removed. Verify current fabrication requirements, then regenerate and
inspect the panel Gerbers and drills before ordering.
