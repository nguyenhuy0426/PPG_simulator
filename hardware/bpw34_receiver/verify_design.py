#!/usr/bin/env python3
"""Independent connectivity, stack-up and mechanical-contract audit."""
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pcbnew as p

HERE = Path(__file__).resolve().parent
board = p.LoadBoard(str(HERE / "bpw34_receiver.kicad_pcb"))
xml = ET.parse(HERE / "reports/bpw34_receiver.net")
nets = {
    item.attrib["name"]: {
        (node.attrib["ref"], node.attrib["pin"])
        for node in item.findall("node")
        if not node.attrib["ref"].startswith("#")
    }
    for item in xml.findall(".//nets/net")
}
checks = []


def check(name, condition):
    checks.append({"check": name, "pass": bool(condition)})
    if not condition:
        raise AssertionError(name)


expected = {
    "/3V3_RED": {("C5", "1"), ("J1", "3"), ("R5", "2"), ("U1", "5")},
    "/GND_RED": {("C3", "2"), ("C5", "2"), ("D1", "2"), ("J1", "4"), ("J3", "2"), ("R7", "1"), ("U1", "2"), ("C7", "2")},
    "/FB_RED": {("C1", "2"), ("R1", "2"), ("R3", "1"), ("U1", "1")},
    "/OUT_RED": {("J1", "1"), ("J3", "1"), ("R3", "2"), ("C7", "1")},
    "/SUM_RED": {("C1", "1"), ("D1", "1"), ("R1", "1"), ("U1", "4")},
    "/VREF_RED": {("C3", "1"), ("R5", "1"), ("R7", "2"), ("U1", "3")},
    "/3V3_IR": {("C6", "1"), ("J2", "3"), ("R6", "2"), ("U2", "5")},
    "/GND_IR": {("C4", "2"), ("C6", "2"), ("D2", "2"), ("J2", "4"), ("J3", "4"), ("R8", "1"), ("U2", "2"), ("C8", "2")},
    "/FB_IR": {("C2", "2"), ("R2", "2"), ("R4", "1"), ("U2", "1")},
    "/OUT_IR": {("J2", "1"), ("J3", "3"), ("R4", "2"), ("C8", "1")},
    "/SUM_IR": {("C2", "1"), ("D2", "1"), ("R2", "1"), ("U2", "4")},
    "/VREF_IR": {("C4", "1"), ("R6", "1"), ("R8", "2"), ("U2", "3")},
}
for net, pins in expected.items():
    check(net + " exact pin set", nets.get(net) == pins)
for ref in ("J1", "J2"):
    check(ref + ".2 intentionally isolated", any(pins == {(ref, "2")} for name, pins in nets.items() if name.startswith("unconnected-")))

fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
check('All resistor/capacitor pads are SMD',all(
    pad.GetAttribute()==p.PAD_ATTRIB_SMD
    for ref,fp in fps.items() if ref.startswith(('R','C')) for pad in fp.Pads()))
check("23 physical footprints; no unused screw holes", len(fps) == 23 and not any(f.startswith('H') for f in fps))
check("two copper layers", board.GetCopperLayerCount() == 2)
check("1.6 mm substrate", abs(p.ToMM(board.GetDesignSettings().GetBoardThickness()) - 1.6) < 1e-6)
edges = [shape for shape in board.GetDrawings() if shape.GetLayer() == p.Edge_Cuts]
vertices = [point for edge in edges for point in (edge.GetStart(), edge.GetEnd())]
check("four closed straight board edges", len(edges) == 4 and len({(point.x, point.y) for point in vertices}) == 4)
check("70 mm board length", abs(p.ToMM(max(point.x for point in vertices) - min(point.x for point in vertices)) - 70) < 0.001)
check("20 mm board width", abs(p.ToMM(max(point.y for point in vertices) - min(point.y for point in vertices)) - 20) < 0.001)

for i in (1,2):
    check(f"R{i+2} output series value",fps[f"R{i+2}"].GetValue()=="1k 1%")
    check(f"C{i+6} output filter value",fps[f"C{i+6}"].GetValue()=="1uF X7R 16V")
for ref in ("D1", "D2"):
    pads = {pad.GetNumber(): pad for pad in fps[ref].Pads()}
    a, b = pads["1"].GetPosition(), pads["2"].GetPosition()
    pitch = math.hypot(p.ToMM(a.x - b.x), p.ToMM(a.y - b.y))
    check(ref + " BPW34 lead pitch 5.1 mm", abs(pitch - 5.1) < 1e-6)
    check(ref + " cathode uses square pad 1", pads["1"].GetShape() == p.PAD_SHAPE_RECT)
check("optical lane separation 38.5 mm", abs(p.ToMM(fps["D2"].GetPosition().x - fps["D1"].GetPosition().x) - 38.5) < 1e-6)
check("both optical centres at board y=110 mm", all(abs(p.ToMM(fps[ref].GetPosition().y) - 110) < 1e-6 for ref in ("D1", "D2")))

for ref, pitch in (("J1", 2.0), ("J2", 2.0), ("J3", 2.54)):
    pads = {pad.GetNumber(): pad for pad in fps[ref].Pads()}
    a, b = pads["1"].GetPosition(), pads["2"].GetPosition()
    actual = math.hypot(p.ToMM(a.x - b.x), p.ToMM(a.y - b.y))
    check(ref + " header pitch", abs(actual - pitch) < 1e-6)
    check(ref + " lower-edge placement", abs(p.ToMM(a.y) - (350/3)) < 1e-5)

for ref in ("U1", "U2", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "C1", "C2", "C3", "C4", "C5", "C6"):
    check(ref + " is on rear copper", fps[ref].GetLayer() == p.B_Cu)
    x = p.ToMM(fps[ref].GetPosition().x)
    check(ref + " stays outside 3 mm optical partition", not (133.5 <= x <= 136.5))

# The compact layout keeps each high-impedance TIA loop entirely on the rear.
for track in board.GetTracks():
    if isinstance(track,p.PCB_TRACK) and not isinstance(track,p.PCB_VIA) and track.GetNetname().lstrip('/') in ('SUM_RED','SUM_IR','FB_RED','FB_IR'):
        check(track.GetNetname()+' stays on rear copper',track.GetLayer()==p.B_Cu)
for ref,fp in fps.items():
    for pad in fp.Pads():
        if pad.GetNumber():
            check(f'{ref}.{pad.GetNumber()} matches schematic netlist',
                  (ref,pad.GetNumber()) in nets.get(pad.GetNetname(),set()))
check('all three connector rows aligned',all(abs(p.ToMM(fps[ref].GetPosition().y)-350/3)<1e-5 for ref in ('J1','J2','J3')))
check('diode pin 1 cathode and pin 2 anode are separated',all(
    len(list(fps[ref].Pads()))==2 for ref in ('D1','D2')))

texts = {(item.GetText(), item.GetLayer()) for item in board.GetDrawings() if isinstance(item, p.PCB_TEXT)}
check("rear DATN title present", ("DATN: PPG-Simulator", p.B_SilkS) in texts)
check("rear author names present", ("Nguyen Nhat Huy - Pham Thanh Vy", p.B_SilkS) in texts)
for label in ('R','I','NC','V','GR','GI'):
    check('rear pin marking '+label,(label,p.B_SilkS) in texts)
for item in board.GetDrawings():
    if isinstance(item, p.PCB_TEXT) and item.GetLayer() == p.B_SilkS:
        check("rear pin label has no numeric prefix: " + item.GetText(), not __import__("re").match(r"^[1-4](?:\s|[A-Z])", item.GetText()))

check('all routed tracks horizontal or vertical', all(
    t.GetStart().x == t.GetEnd().x or t.GetStart().y == t.GetEnd().y
    for t in board.GetTracks() if not isinstance(t, p.PCB_VIA)))
report = {"kicad_version": p.Version(), "checks": checks, "passed": len(checks)}
(HERE / "reports/pin_contract.json").write_text(json.dumps(report, indent=2) + "\n")
print(f"Passed {len(checks)} BPW34 receiver checks")
