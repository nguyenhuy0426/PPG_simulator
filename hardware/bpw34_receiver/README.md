# Dual BPW34 receiver for DATN: PPG-Simulator

This is a complete KiCad 10 project for a 70 x 32 mm, two-channel photodiode receiver that can replace the dual-OPT101 board mechanically. The BPW34 optical centres remain 38.5 mm apart and use the same four M3 mounting-hole locations as the existing receiver frame.

## Electrical design

Each channel is independent and contains one BPW34, one OPA333 transimpedance amplifier, a 1 Mohm feedback resistor, and a 22 pF C0G/NP0 feedback capacitor. A 100k/10k divider creates a filtered 0.30 V reference from the 3.3 V Grove supply. Light-induced reverse current therefore raises the output:

`VOUT approximately 0.30 V + IPD x 1 Mohm`

The 100 ohm output resistor isolates the op-amp from cable and ADC input capacitance. C1/C2 are C0G/NP0 because their value sets TIA stability; C3-C6 are non-polar 100 nF X7R ceramic capacitors. No electrolytic capacitor is required.

The preferred amplifier is `OPA333AIDBVR` in SOT-23-5. The lower-cost `MCP6001T-I/OT` has the same pinout and footprint, but higher offset and drift. The board does not support LM358 because its input/output headroom is a poor match for a 3.3 V photodiode TIA.

## Connectors

| Connector | Pin 1 | Pin 2 | Pin 3 | Pin 4 |
|---|---|---|---|---|
| J1, Grove A2 | OUT_RED | NC | 3V3_RED | GND_RED |
| J2, Grove A0 | OUT_IR | NC | 3V3_IR | GND_IR |
| J3, ADS1115 | OUT_RED | GND_RED | OUT_IR | GND_IR |

J1 and J2 are 1x4 male headers with 2.00 mm pitch. J3 is a 1x4 male header with 2.54 mm pitch. J3 intentionally carries no supply; power the ADS1115 normally and connect both J3 ground pins to its GND. The channel grounds remain separate on this PCB and meet at the HAT or ADS1115.

The Grove Base Hat must be configured for 3.3 V. Pin 2 of each Grove connector is deliberately unused.

## BPW34 polarity

Pad 1 is the cathode (`K`) and is square. Pad 2 is the anode (`A`) and is round. Match the BPW34 cathode marking to `K`; reversing the diode changes the bias and output polarity.

## Manufacturing and assembly

- 2 layers, FR-4, 1.6 mm, 70 x 32 mm.
- Solder D1/D2 and the three headers on the front.
- Solder U1/U2 and all 0805 parts on the rear.
- The rear components are arranged as two channel blocks: the feedback pair is
  in the upper row, the OPA333 and 100 ohm output path are in the middle, and
  the VREF divider is in the outer column. All reference designators read
  horizontally from the rear.
- The high-impedance `SUM_RED`, `SUM_IR`, `FB_RED`, and `FB_IR` routes remain
  on B.Cu and are kept local to their channel. The long supply/output runs use
  the opposite layer where needed, so they do not cut through the TIA loops.
- Every routed copper segment on F.Cu and B.Cu is horizontal or vertical; the
  layout intentionally contains no diagonal track segments.
- Both sides carry pin markings. On the rear, every J1/J2/J3 pad is labelled
  individually with an abbreviation; the nearby legend
  defines `R=OUT_RED`, `I=OUT_IR`, `V=3V3`, `N=NC`, and `GR/GI=channel GND`.
  D1/D2 also show `K` and `A`. Pin numbers are deliberately omitted from the
  rear labels. Read the mirrored rear silkscreen while
  looking directly at the rear.
- Fit the 22 pF parts as C0G/NP0, not X7R.
- Trim through-hole leads on the rear to at most 2 mm for the slide-in frame.
- If the output sits near 3.3 V under normal illumination, replace R1/R2 with 330 kohm. Do not parallel the RED and IR outputs.

## Generated evidence

- `reports/erc.rpt`: schematic electrical-rule check.
- `reports/drc.rpt`: PCB DRC, unconnected-item and schematic-parity check.
- `reports/pin_contract.json`: exact net/pin and mechanical contract audit.
- `reports/schematic.pdf` and `reports/schematic.png`: readable schematic.
- `reports/pcb_top.png`, `reports/pcb_bottom.png`: PCB renders.
- `reports/wiring_guide.png`: routing and pad-number guide.
- `fabrication/`: Gerbers and plated/non-plated drill files.
- `mechanical/`: adapter STLs, collision report and nominal optical report.

The CAD checks do not prove analog gain, noise, optical leakage, print shrinkage or physical fit. Measure the real LED current/output and perform a dark-box leakage test before ordering a large batch.
