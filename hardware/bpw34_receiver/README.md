# Dual BPW34 receiver for DATN: PPG-Simulator

This is a complete KiCad 10 project for a 70 x 30 mm, two-channel photodiode receiver that can replace the dual-OPT101 board mechanically. The BPW34 optical centres remain 38.5 mm apart and use the same four M3 mounting-hole locations as the existing receiver frame.

## Electrical design

Each channel is independent and contains one BPW34, one OPA333 transimpedance amplifier, a 1 Mohm feedback resistor, and a 22 pF C0G/NP0 feedback capacitor. A 100k/10k divider creates a filtered 0.30 V reference from the 3.3 V Grove supply. Light-induced reverse current therefore raises the output:

`VOUT approximately 0.30 V + IPD x 1 Mohm`

R3/R4 = 1 kohm and C7/C8 = 1 uF X7R 16 V form an output low-pass filter (159 Hz nominal). The capacitor connects after the resistor to its channel ground. Attenuation at 20 Hz is approximately 0.8%; this is not a 50 Hz notch filter. C1/C2 are C0G/NP0 because their value sets TIA stability; C3-C6 are non-polar 100 nF X7R ceramic capacitors. No electrolytic capacitor is required.

The preferred amplifier is `OPA333AIDBVR` in SOT-23-5. The lower-cost `MCP6001T-I/OT` has the same pinout and footprint, but higher offset and drift. The board does not support LM358 because its input/output headroom is a poor match for a 3.3 V photodiode TIA.

The schematic now draws R1/C1 and R2/C2 as two visible parallel feedback branches between each BPW34 cathode (SUM) and the OPA333 output (FB). A supply arrow marks each channel's `3V3_RED` or `3V3_IR` net; a ground symbol marks `GND_RED` or `GND_IR`. The two channel grounds remain separate. The former diamond-shaped `PWR_FLAG` symbols have been removed; the Grove connector power pins are declared as the external source for KiCad ERC.

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

- 2 layers, FR-4, 1.6 mm, 70 x 30 mm.
- Solder D1/D2 and the three headers on the front.
- Solder U1/U2 and all 0805 parts on the rear.
- The rear components are arranged as two channel blocks: the feedback pair is
  in the upper row, the OPA333 and 1 kohm output path are in the middle, and
  the VREF divider is in the outer column. All reference designators read
  horizontally from the rear.
- The high-impedance `SUM_RED`, `SUM_IR`, `FB_RED`, and `FB_IR` routes remain
  on B.Cu and are kept local to their channel. The long supply/output runs use
  the opposite layer where needed, so they do not cut through the TIA loops.
- Every routed copper segment on F.Cu and B.Cu is horizontal or vertical; the
  layout intentionally contains no diagonal track segments.
- The 3.3 V supply traces now approach the lower connectors on the inside of
  each mounting hole and run around the outer edge on the rear. The closest
  routed copper stays 0.7 mm from any M3 drill opening, and at least 1.7 mm
  from either lower opening H3/H4. These are copper-edge to drill-edge values;
  the drilled opening does not sever a trace.
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

## Compact mechanical revision v1.3

Use `mechanical/frame_70x30_bpw34_print.stl`. Optical centres are (15.75,15) and (54.25,15) mm on the PCB, maintaining the original world optical axes. Header row is Y=25 mm; M3 hole centres are X=4.5/65.5, Y=3.5/26.5 mm. The old 70x32 frame is superseded.
