#!/usr/bin/env python3
"""Generate the dual-BPW34 receiver schematic and PCB with KiCad 10.

The two channels are electrically independent up to the ADS1115 header.  Each
Grove cable powers one channel, matching the existing A2/RED and A0/IR wiring.
"""
import argparse
import csv
import json
import re
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "bpw34_receiver"
ROOT = str(uuid.uuid5(uuid.NAMESPACE_URL, "ppg-bpw34-receiver-v1"))


def uid(text):
    return str(uuid.uuid5(uuid.UUID(ROOT), text))


def q(text):
    return json.dumps(str(text))


def effects(size=1.27):
    return f"(effects (font (size {size} {size})))"


PINS = {
    "BPW34": [
        ("1", "K", "passive", 5.08, 0, 180),
        ("2", "A", "passive", -5.08, 0, 0),
    ],
    "OPA333": [
        ("1", "OUT", "output", 15.24, 0, 180),
        ("2", "V-", "power_in", 0, -12.7, 90),
        ("3", "IN+", "input", -15.24, -2.54, 0),
        ("4", "IN-", "input", -15.24, 2.54, 0),
        ("5", "V+", "power_in", 0, 12.7, 270),
    ],
    "R": [
        ("1", "~", "passive", -5.08, 0, 0),
        ("2", "~", "passive", 5.08, 0, 180),
    ],
    "C": [
        ("1", "~", "passive", 0, 5.08, 270),
        ("2", "~", "passive", 0, -5.08, 90),
    ],
    "Grove": [
        ("1", "SIGNAL", "passive", -10.16, 7.62, 0),
        ("2", "UNUSED", "passive", -10.16, 2.54, 0),
        ("3", "3V3", "passive", -10.16, -2.54, 0),
        ("4", "GND", "passive", -10.16, -7.62, 0),
    ],
    "ADS": [
        ("1", "OUT_RED", "passive", -10.16, 7.62, 0),
        ("2", "GND_RED", "passive", -10.16, 2.54, 0),
        ("3", "OUT_IR", "passive", -10.16, -2.54, 0),
        ("4", "GND_IR", "passive", -10.16, -7.62, 0),
    ],
    "PWR_FLAG": [("1", "pwr", "power_out", 0, 0, 90)],
    "MountingHole": [],
}


def lib_symbol(name):
    refs = {
        "BPW34": "D",
        "OPA333": "U",
        "R": "R",
        "C": "C",
        "Grove": "J",
        "ADS": "J",
        "PWR_FLAG": "#FLG",
        "MountingHole": "H",
    }
    hide = "(pin_numbers (hide yes))" if name in ("R", "C", "PWR_FLAG") else ""
    out = [
        f'(symbol "PPG:{name}" {hide} (pin_names (offset 0.5) {"(hide yes)" if name in ("R", "C", "PWR_FLAG") else ""}) (in_bom yes) (on_board yes)',
        f'(property "Reference" "{refs[name]}" (at 0 13.97 0) {effects()})',
        f'(property "Value" "{name}" (at 0 11.43 0) {effects()})',
        f'(symbol "{name}_0_1"',
    ]
    if name == "OPA333":
        out.append('(polyline (pts (xy -7.62 7.62) (xy 7.62 0) (xy -7.62 -7.62) (xy -7.62 7.62)) (stroke (width 0.254) (type default)) (fill (type background)))')
        out.append(f'(text "+" (at -5.08 -2.54 0) {effects(1.4)})')
        out.append(f'(text "-" (at -5.08 2.54 0) {effects(1.4)})')
    elif name == "BPW34":
        out.extend([
            '(polyline (pts (xy -1.27 -3.81) (xy -1.27 3.81)) (stroke (width 0.254) (type default)) (fill (type none)))',
            '(polyline (pts (xy -1.27 0) (xy 2.54 -3.81) (xy 2.54 3.81) (xy -1.27 0)) (stroke (width 0.254) (type default)) (fill (type none)))',
            '(polyline (pts (xy 4.57 -4.57) (xy 2.54 -2.54)) (stroke (width 0.254) (type default)) (fill (type none)))',
            '(polyline (pts (xy 4.57 0) (xy 2.54 2.03)) (stroke (width 0.254) (type default)) (fill (type none)))',
        ])
    elif name in ("Grove", "ADS"):
        out.append('(rectangle (start -5.08 10.16) (end 5.08 -10.16) (stroke (width 0.254) (type default)) (fill (type background)))')
    elif name == "R":
        out.append('(rectangle (start -2.54 1.27) (end 2.54 -1.27) (stroke (width 0.254) (type default)) (fill (type none)))')
    elif name == "C":
        out.extend([
            '(polyline (pts (xy -2.54 -0.762) (xy 2.54 -0.762)) (stroke (width 0.254) (type default)) (fill (type none)))',
            '(polyline (pts (xy -2.54 0.762) (xy 2.54 0.762)) (stroke (width 0.254) (type default)) (fill (type none)))',
        ])
    elif name == "PWR_FLAG":
        out.append('(polyline (pts (xy 0 0) (xy 0 2.54) (xy 1.27 3.81) (xy 0 5.08) (xy -1.27 3.81) (xy 0 2.54)) (stroke (width 0.254) (type default)) (fill (type none)))')
    else:
        out.append('(circle (center 0 0) (radius 2.54) (stroke (width 0.254) (type default)) (fill (type none)))')
    out += [")", f'(symbol "{name}_1_1"']
    for num, label, kind, x, y, angle in PINS[name]:
        length = 0 if name == "PWR_FLAG" else 5.08
        out.append(f'(pin {kind} line (at {x} {y} {angle}) (length {length}) (name {q(label)} {effects(1)}) (number "{num}" {effects(1)}))')
    return "\n".join(out + ["))"])


def write_schematic():
    out = [
        f'(kicad_sch (version 20250114) (generator "eeschema") (uuid {ROOT}) (paper "A3")',
        '(title_block (title "DATN: PPG-Simulator - Dual BPW34 receiver") (date "2026-09-24") (rev "1.1") (comment 1 "Nguyen Nhat Huy - Pham Thanh Vy") (comment 2 "70 x 32 mm / Grove A2 RED + A0 IR / ADS1115 output"))',
        "(lib_symbols",
        *(lib_symbol(name) for name in PINS),
        ")",
    ]
    placed = set()

    def wire(a, b):
        out.append(f'(wire (pts (xy {a[0]} {a[1]}) (xy {b[0]} {b[1]})) (stroke (width 0) (type default)) (uuid {uid("wire" + str((a,b))) }))')

    def junction(x, y, tag):
        out.append(f'(junction (at {x} {y}) (diameter 0) (color 0 0 0 0) (uuid {uid("junction" + tag + str((x,y))) }))')

    def label(text, x, y):
        out.append(f'(label {q(text)} (at {x} {y} 0) (effects (font (size 1 1)) (justify left bottom)) (uuid {uid("label" + text + str((x,y))) }))')

    def text(value, x, y, size=1.27):
        out.append(f'(text {q(value)} (at {x} {y} 0) {effects(size)} (uuid {uid("text" + value + str((x,y))) }))')

    def nc(x, y, ref):
        out.append(f'(no_connect (at {x} {y}) (uuid {uid("nc" + ref + str((x,y))) }))')

    def place(kind, ref, value, x, y, fp="", angle=0):
        out.append(f'(symbol (lib_id "PPG:{kind}") (at {x} {y} {angle}) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid {uid(ref)})')
        for prop, val, py, hide in [
            ("Reference", ref, y - 14, False),
            ("Value", value, y - 11, False),
            ("Footprint", fp, y, True),
        ]:
            px = x
            if kind in ("R", "C") and prop in ("Reference", "Value"):
                px = x + 1.27
                py = y + (-2.54 if prop == "Reference" else 2.54)
            if kind in ("PWR_FLAG", "MountingHole"):
                py = y - 5 if prop == "Reference" else y - 3
            out.append(f'(property "{prop}" {q(val)} (at {px} {py} 0) (effects (font (size 1.05 1.05)) {"(hide yes)" if hide or ref.startswith("#") else ""}))')
        for num, *_ in PINS[kind]:
            out.append(f'(pin "{num}" (uuid {uid(ref + num)}))')
        out.append(f'(instances (project "{NAME}" (path "/{ROOT}" (reference "{ref}") (unit 1)))))')
        placed.add(ref)

    channels = [
        dict(ch="RED", idx=1, y=73.66, grove="A2 / RED"),
        dict(ch="IR", idx=2, y=157.48, grove="A0 / IR"),
    ]
    for data in channels:
        ch, idx, y = data["ch"], data["idx"], data["y"]
        top, bottom = y - 30.48, y + 30.48
        refs = {
            "d": f"D{idx}", "u": f"U{idx}", "rf": f"R{idx}", "cf": f"C{idx}",
            "rout": f"R{idx+2}", "rtop": f"R{idx+4}", "rbot": f"R{idx+6}",
            "cvref": f"C{idx+2}", "cdec": f"C{idx+4}", "j": f"J{idx}",
        }
        text(f"{ch} CHANNEL - BPW34 -> 1 Mohm TIA -> {data['grove']}", 116.84, top - 7.62, 1.5)
        place("BPW34", refs["d"], f"BPW34 {ch}", 63.5, y - 2.54, "PPG:BPW34_THT")
        place("OPA333", refs["u"], "OPA333AIDBVR", 111.76, y, "PPG:SOT23_5_Hand")
        place("R", refs["rf"], "1M 1%", 111.76, y - 20.32, "PPG:R0805_Hand")
        place("C", refs["cf"], "22pF C0G", 101.6, y - 10.16, "PPG:C0805_Hand")
        place("R", refs["rout"], "100R", 139.7, y, "PPG:R0805_Hand")
        place("Grove", refs["j"], data["grove"], 185.42, y, "PPG:Header_1x04_P2mm")

        # Main optical and feedback path.  The photodiode anode is grounded;
        # reverse photocurrent therefore drives the TIA output upward.
        wire((68.58, y - 2.54), (96.52, y - 2.54))
        label(f"SUM_{ch}", 78.74, y - 2.54)
        wire((96.52, y - 2.54), (96.52, y - 20.32))
        wire((96.52, y - 20.32), (106.68, y - 20.32))
        wire((116.84, y - 20.32), (127, y - 20.32))
        wire((127, y - 20.32), (127, y))
        wire((127, y), (134.62, y))
        label(f"FB_{ch}", 127, y)
        wire((96.52, y - 2.54), (101.6, y - 2.54))
        wire((101.6, y - 2.54), (101.6, y - 15.24))
        wire((101.6, y - 15.24), (101.6, y - 15.24))
        wire((101.6, y - 5.08), (127, y - 5.08))
        wire((127, y - 5.08), (127, y))
        junction(96.52, y - 2.54, ch)
        junction(127, y, ch)
        wire((144.78, y), (175.26, y))
        wire((175.26, y), (175.26, y - 7.62))
        label(f"OUT_{ch}", 149.86, y)

        # Reference: 3.3 V -> 100k -> VREF (~0.30 V) -> 10k -> GND.
        place("R", refs["rtop"], "100k 1%", 35.56, y - 12.7, "PPG:R0805_Hand", 90)
        place("R", refs["rbot"], "10k 1%", 35.56, y + 12.7, "PPG:R0805_Hand", 90)
        place("C", refs["cvref"], "100nF X7R", 45.72, y + 12.7, "PPG:C0805_Hand")
        place("C", refs["cdec"], "100nF X7R", 149.86, y + 12.7, "PPG:C0805_Hand")
        wire((35.56, y - 22.86), (35.56, y - 17.78))
        label(f"3V3_{ch}", 35.56, y - 22.86)
        wire((35.56, y - 7.62), (35.56, y + 7.62))
        wire((35.56, y + 17.78), (35.56, y + 22.86))
        label(f"GND_{ch}", 35.56, y + 22.86)
        wire((35.56, y), (96.52, y))
        wire((96.52, y), (96.52, y + 2.54))
        label(f"VREF_{ch}", 50.8, y)
        wire((45.72, y + 7.62), (45.72, y))
        wire((45.72, y), (35.56, y))
        wire((45.72, y + 17.78), (45.72, y + 22.86))
        label(f"GND_{ch}", 45.72, y + 22.86)
        junction(35.56, y, ch + "vref")

        # Channel-local supply labels avoid graphical crossings. Every repeated
        # label below is the same electrical net and is shown beside its pin.
        wire((58.42, y - 2.54), (53.34, y - 2.54))
        label(f"GND_{ch}", 53.34, y - 2.54)
        wire((111.76, y - 12.7), (111.76, y - 17.78))
        label(f"3V3_{ch}", 111.76, y - 17.78)
        place("PWR_FLAG", f"#FLG{idx}1", "PWR_FLAG", 111.76, y - 17.78)
        wire((111.76, y + 12.7), (111.76, y + 17.78))
        label(f"GND_{ch}", 111.76, y + 17.78)
        place("PWR_FLAG", f"#FLG{idx}2", "PWR_FLAG", 111.76, y + 17.78)
        wire((149.86, y + 7.62), (154.94, y + 7.62))
        label(f"3V3_{ch}", 154.94, y + 7.62)
        wire((149.86, y + 17.78), (154.94, y + 17.78))
        label(f"GND_{ch}", 154.94, y + 17.78)
        wire((175.26, y + 2.54), (170.18, y + 2.54))
        label(f"3V3_{ch}", 170.18, y + 2.54)
        wire((175.26, y + 7.62), (170.18, y + 7.62))
        label(f"GND_{ch}", 170.18, y + 7.62)
        nc(175.26, y - 2.54, refs["j"])
        text("Grove: 1=signal, 2=NC, 3=3V3, 4=GND", 185.42, bottom + 7.62, 1.0)

    # Paired return pins make the external ADS1115 connection unambiguous.
    place("ADS", "J3", "ADS1115: RED/GND/IR/GND", 243.84, 115.57, "PPG:Header_1x04_P2.54mm")
    ads_y = [107.95, 113.03, 118.11, 123.19]
    for net, yy in zip(("OUT_RED", "GND_RED", "OUT_IR", "GND_IR"), ads_y):
        wire((210.82, yy), (233.68, yy))
        label(net, 210.82, yy)
    text("J3 -> ADS1115: each signal travels with its own channel ground", 243.84, 135.89, 1.15)
    text("Power the ADS1115 separately. J3 does not provide VCC.", 243.84, 141.0, 1.15)
    text("Default gain: 1 MOhm. Approx. VOUT = 0.30 V + IPD x 1 MOhm.", 132.08, 205.74, 1.15)
    text("C1/C2 = 22 pF C0G stability capacitors; all 100 nF capacitors are non-polar ceramic.", 132.08, 211.0, 1.05)
    text("OPA333 SOT-23-5 may be replaced by pin-compatible MCP6001T-I/OT for lower cost.", 132.08, 216.0, 1.05)
    for i, x in enumerate((45.72, 86.36, 127, 167.64), 1):
        place("MountingHole", f"H{i}", "M3 / 3.2mm NPTH", x, 231.14, "PPG:MountingHole_M3")
    out += ['(sheet_instances (path "/" (page "1")))', ")"]
    (HERE / f"{NAME}.kicad_sch").write_text("\n".join(out))
    local = "\n".join(lib_symbol(name).replace(f'"PPG:{name}"', f'"{name}"', 1) for name in PINS)
    (HERE / "PPG.kicad_sym").write_text(f'(kicad_symbol_lib (version 20250114) (generator "kicad_symbol_editor")\n{local})')
    (HERE / "sym-lib-table").write_text('(sym_lib_table (version 7) (lib (name "PPG") (type "KiCad") (uri "${KIPRJMOD}/PPG.kicad_sym") (options "") (descr "Project-local BPW34 symbols")))\n')


def write_bpw34_footprint(path):
    path.write_text(r'''(footprint "BPW34_THT"
  (version 20240108) (generator pcbnew) (layer "F.Cu")
  (descr "Vishay BPW34 leaded top-view photodiode; 5.1 mm nominal lead spacing")
  (tags "BPW34 photodiode THT")
  (property "Reference" "REF**" (at 0 -3.4 0) (layer "F.SilkS") (effects (font (size 0.9 0.9) (thickness 0.13))))
  (property "Value" "BPW34_THT" (at 0 3.4 0) (layer "F.Fab") (effects (font (size 0.9 0.9) (thickness 0.13))))
  (attr through_hole)
  (fp_line (start -2.7 -2.15) (end 2.7 -2.15) (stroke (width 0.15) (type default)) (layer "F.SilkS"))
  (fp_line (start -2.7 2.15) (end 2.7 2.15) (stroke (width 0.15) (type default)) (layer "F.SilkS"))
  (fp_line (start -2.7 -2.15) (end -2.7 -1.25) (stroke (width 0.15) (type default)) (layer "F.SilkS"))
  (fp_line (start -2.7 1.25) (end -2.7 2.15) (stroke (width 0.15) (type default)) (layer "F.SilkS"))
  (fp_line (start 2.7 -2.15) (end 2.7 -1.25) (stroke (width 0.15) (type default)) (layer "F.SilkS"))
  (fp_line (start 2.7 1.25) (end 2.7 2.15) (stroke (width 0.15) (type default)) (layer "F.SilkS"))
  (fp_rect (start -2.85 -2.3) (end 2.85 2.3) (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))
  (fp_rect (start -3.25 -2.7) (end 3.25 2.7) (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))
  (fp_line (start -2.7 -2.15) (end -2.15 -1.6) (stroke (width 0.35) (type default)) (layer "F.SilkS"))
  (fp_circle (center 0 0) (end 0.6 0) (stroke (width 0.1) (type default)) (fill none) (layer "Dwgs.User"))
  (pad "1" thru_hole rect (at -2.55 0) (size 2 2) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (pad "2" thru_hole circle (at 2.55 0) (size 2 2) (drill 1.0) (layers "*.Cu" "*.Mask"))
  (model "${KIPRJMOD}/3dmodels/BPW34.wrl"
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0)))
)''')


def write_bpw34_model(path):
    # KiCad interprets legacy VRML coordinates in 0.1-inch (2.54 mm) units.
    def box(size_mm, centre_mm, colour, transparency=0.0):
        size = [value / 2.54 for value in size_mm]
        centre = [value / 2.54 for value in centre_mm]
        return f'''Transform {{ translation {centre[0]:.6f} {centre[1]:.6f} {centre[2]:.6f}
  children [ Shape {{ appearance Appearance {{ material Material {{ diffuseColor {colour[0]} {colour[1]} {colour[2]} transparency {transparency} }} }}
    geometry Box {{ size {size[0]:.6f} {size[1]:.6f} {size[2]:.6f} }} }} ] }}'''
    shapes = [
        box((5.4, 4.3, 3.2), (0, 0, 1.6), (0.72, 0.78, 0.83), 0.32),
        box((3.0, 2.5, 0.12), (0, 0, 3.18), (0.03, 0.12, 0.22), 0.0),
        box((0.45, 4.3, 0.14), (-2.45, 0, 3.13), (0.18, 0.18, 0.2), 0.0),
        box((0.35, 0.7, 1.4), (-2.55, 0, 0.7), (0.72, 0.72, 0.75), 0.0),
        box((0.35, 0.7, 1.4), (2.55, 0, 0.7), (0.72, 0.72, 0.75), 0.0),
    ]
    path.write_text("#VRML V2.0 utf8\n" + "\n".join(shapes) + "\n")


def write_project_footprints(share):
    library = HERE / "PPG.pretty"
    library.mkdir(exist_ok=True)
    sources = {
        "SOT23_5_Hand": "Package_TO_SOT_SMD.pretty/SOT-23-5_HandSoldering.kicad_mod",
        "R0805_Hand": "Resistor_SMD.pretty/R_0805_2012Metric_Pad1.20x1.40mm_HandSolder.kicad_mod",
        "C0805_Hand": "Capacitor_SMD.pretty/C_0805_2012Metric_Pad1.18x1.45mm_HandSolder.kicad_mod",
        "Header_1x04_P2mm": "Connector_PinHeader_2.00mm.pretty/PinHeader_1x04_P2.00mm_Vertical.kicad_mod",
        "Header_1x04_P2.54mm": "Connector_PinHeader_2.54mm.pretty/PinHeader_1x04_P2.54mm_Vertical.kicad_mod",
        "MountingHole_M3": "MountingHole.pretty/MountingHole_3.2mm_M3.kicad_mod",
    }
    models = HERE / "3dmodels"
    for name, source_name in sources.items():
        text = (share / "footprints" / source_name).read_text()
        text = re.sub(r'^\(footprint "[^"]+"', f'(footprint "{name}"', text)
        for model in re.findall(r'\(model "([^\"]+)"', text):
            suffix = model.split("}/")[-1]
            source = share / "3dmodels" / suffix
            if source.exists():
                destination = models / suffix
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                text = text.replace(model, "${KIPRJMOD}/3dmodels/" + suffix)
        (library / f"{name}.kicad_mod").write_text(text)
    models.mkdir(parents=True, exist_ok=True)
    write_bpw34_model(models / "BPW34.wrl")
    write_bpw34_footprint(library / "BPW34_THT.kicad_mod")
    (HERE / "fp-lib-table").write_text('(fp_lib_table (version 7) (lib (name "PPG") (type "KiCad") (uri "${KIPRJMOD}/PPG.pretty") (options "") (descr "Vendored BPW34 receiver footprints")))\n')
    return library


def write_pcb(share, cli):
    import pcbnew as p

    mm = p.FromMM
    vec = lambda x, y: p.VECTOR2I(mm(x), mm(y))
    board = p.BOARD()
    board.GetDesignSettings().SetCopperLayerCount(2)
    board.GetDesignSettings().SetBoardThickness(mm(1.6))
    net_path = HERE / "reports" / f"{NAME}.net"
    subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(net_path), str(HERE / f"{NAME}.kicad_sch")], check=True)
    xml = ET.parse(net_path)
    nets = {}
    pin_nets = {}
    for item in xml.findall(".//nets/net"):
        net = p.NETINFO_ITEM(board, item.attrib["name"])
        board.Add(net)
        nets[item.attrib["name"].lstrip("/")] = net
        for node in item.findall("node"):
            pin_nets[node.attrib["ref"], node.attrib["pin"]] = net

    library = write_project_footprints(share)

    def add(ref, footprint, value, x, y, angle=0, back=False):
        fp = p.FootprintLoad(str(library), footprint)
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.SetFPID(p.LIB_ID("PPG", footprint))
        fp.SetAttributes(fp.GetAttributes() & ~p.FP_EXCLUDE_FROM_BOM)
        fp.SetPosition(vec(x, y))
        fp.SetOrientationDegrees(angle)
        path = p.KIID_PATH()
        path.push_back(p.KIID(ROOT))
        path.push_back(p.KIID(uid(ref)))
        fp.SetPath(path)
        fp.Reference().SetTextSize(vec(0.8, 0.8))
        fp.Reference().SetTextThickness(mm(0.12))
        for pad in fp.Pads():
            if (ref, pad.GetNumber()) in pin_nets:
                pad.SetNet(pin_nets[ref, pad.GetNumber()])
        board.Add(fp)
        if back:
            fp.Flip(fp.GetPosition(), False)
        return fp

    def line(a, b, layer, width=0.15):
        shape = p.PCB_SHAPE()
        shape.SetShape(p.SHAPE_T_SEGMENT)
        shape.SetStart(vec(*a))
        shape.SetEnd(vec(*b))
        shape.SetLayer(layer)
        shape.SetWidth(mm(width))
        board.Add(shape)

    def silk(text, x, y, size=0.9, layer=p.F_SilkS, mirrored=False, angle=0):
        item = p.PCB_TEXT(board)
        item.SetText(text)
        item.SetPosition(vec(x, y))
        item.SetTextSize(vec(size, size))
        item.SetTextThickness(mm(0.13))
        item.SetLayer(layer)
        item.SetMirrored(mirrored)
        item.SetTextAngle(p.EDA_ANGLE(angle, p.DEGREES_T))
        board.Add(item)
        return item

    def route(net_name, points, layer=p.B_Cu, width=0.3):
        for start, end in zip(points, points[1:]):
            if start == end:
                continue
            track = p.PCB_TRACK(board)
            track.SetStart(vec(*start))
            track.SetEnd(vec(*end))
            track.SetWidth(mm(width))
            track.SetLayer(layer)
            track.SetNet(nets[net_name])
            board.Add(track)

    def via(net_name, x, y, diameter=0.8, drill=0.4):
        item = p.PCB_VIA(board)
        item.SetPosition(vec(x, y))
        item.SetWidth(mm(diameter))
        item.SetDrill(mm(drill))
        item.SetLayerPair(p.F_Cu, p.B_Cu)
        item.SetNet(nets[net_name])
        board.Add(item)

    def pad_xy(fp, number):
        for pad in fp.Pads():
            if pad.GetNumber() == str(number):
                pos = pad.GetPosition()
                return p.ToMM(pos.x), p.ToMM(pos.y)
        raise KeyError((fp.GetReference(), number))

    def tree(net_name, hub, nodes, layer=p.B_Cu, width=0.25):
        for x, y in nodes:
            route(net_name, [(x, y), (hub[0], y), hub], layer, width)

    for start, end in [((100, 100), (170, 100)), ((170, 100), (170, 132)), ((170, 132), (100, 132)), ((100, 132), (100, 100))]:
        line(start, end, p.Edge_Cuts, 0.05)

    footprints = {}
    # Each analogue channel is a compact, mirrored signal-flow block.  The
    # upper two rows are the parallel 1 Mohm / 22 pF feedback pair, the middle
    # row is OPA333 -> 100 ohm output isolation, and the outer column is the
    # 0.30 V reference divider.  This grid keeps the high-impedance summing
    # node short and leaves the lower edge clear for all three connectors.
    placements = {
        "RED": {
            "D": ("D1", "BPW34_THT", "BPW34 RED", 115.75, 116.0, 0, False),
            "U": ("U1", "SOT23_5_Hand", "OPA333AIDBVR", 119.0, 110.5, 0, True),
            "RF": ("R1", "R0805_Hand", "1M 1%", 119.0, 105.0, 180, True),
            "CF": ("C1", "C0805_Hand", "22pF C0G", 119.0, 107.5, 180, True),
            "RO": ("R3", "R0805_Hand", "100R", 124.5, 109.55, 180, True),
            "RT": ("R5", "R0805_Hand", "100k 1%", 108.5, 106.0, 90, True),
            "RB": ("R7", "R0805_Hand", "10k 1%", 108.5, 111.0, 90, True),
            "CV": ("C3", "C0805_Hand", "100nF X7R", 111.5, 111.0, 270, True),
            "CD": ("C5", "C0805_Hand", "100nF X7R", 110.5, 102.5, 0, True),
            "J": ("J1", "Header_1x04_P2mm", "A2 / RED", 110.5, 127.0, 90, False),
        },
        "IR": {
            "D": ("D2", "BPW34_THT", "BPW34 IR", 154.25, 116.0, 0, False),
            "U": ("U2", "SOT23_5_Hand", "OPA333AIDBVR", 151.0, 110.5, 0, True),
            "RF": ("R2", "R0805_Hand", "1M 1%", 151.0, 105.0, 180, True),
            "CF": ("C2", "C0805_Hand", "22pF C0G", 151.0, 107.5, 180, True),
            "RO": ("R4", "R0805_Hand", "100R", 155.5, 107.5, 180, True),
            "RT": ("R6", "R0805_Hand", "100k 1%", 161.5, 106.0, 90, True),
            "RB": ("R8", "R0805_Hand", "10k 1%", 161.5, 111.0, 90, True),
            "CV": ("C4", "C0805_Hand", "100nF X7R", 158.5, 111.0, 270, True),
            "CD": ("C6", "C0805_Hand", "100nF X7R", 159.5, 102.5, 180, True),
            "J": ("J2", "Header_1x04_P2mm", "A0 / IR", 153.5, 127.0, 90, False),
        },
    }
    for ch in ("RED", "IR"):
        for key, args in placements[ch].items():
            footprints[args[0]] = add(*args)
    footprints["J3"] = add("J3", "Header_1x04_P2.54mm", "ADS1115: RED/GND/IR/GND", 122.0, 127.0, 90, False)
    for index, (x, y) in enumerate(((104.5, 103.5), (165.5, 103.5), (104.5, 128.5), (165.5, 128.5)), 1):
        fp = add(f"H{index}", "MountingHole_M3", "M3 / 3.2mm NPTH", x, y)
        fp.Reference().SetVisible(False)
        fp.Value().SetVisible(False)
        footprints[f"H{index}"] = fp

    # Route short, high-impedance TIA loops entirely on B.Cu.  The two blocks
    # use the same routing grammar, reflected about x=135 mm: a straight local
    # feedback spine, a direct diode-to-input path, and an outer-edge supply
    # spine.  Ground is supplied by the channel-local B.Cu zones below.
    for ch, idx in (("RED", 1), ("IR", 2)):
        fp = placements[ch]
        d, u, rf, cf, ro, rt, rb, cv, cd, j = [footprints[fp[k][0]] for k in ("D", "U", "RF", "CF", "RO", "RT", "RB", "CV", "CD", "J")]
        d_k, u_inv, rf_sum, cf_sum = pad_xy(d, 1), pad_xy(u, 4), pad_xy(rf, 1), pad_xy(cf, 1)
        u_out, rf_fb, cf_fb, ro_in = pad_xy(u, 1), pad_xy(rf, 2), pad_xy(cf, 2), pad_xy(ro, 1)
        u_ref, rt_ref, rb_ref, cv_ref = pad_xy(u, 3), pad_xy(rt, 1), pad_xy(rb, 2), pad_xy(cv, 1)
        u_vdd, rt_vdd, cd_vdd, j_vdd = pad_xy(u, 5), pad_xy(rt, 2), pad_xy(cd, 1), pad_xy(j, 3)
        out_start, grove_out = pad_xy(ro, 2), pad_xy(j, 1)

        if ch == "RED":
            # Summing node: orthogonal escape from D1.K into U1.-, then a
            # vertical branch to the parallel feedback parts.
            route("SUM_RED", [d_k, (d_k[0], 115.4), (113.8, 115.4), (113.8, 112.8), (u_inv[0], 112.8), u_inv], p.B_Cu, 0.22)
            route("SUM_RED", [(113.8, 112.8), (113.8, 105.0), rf_sum], p.B_Cu, 0.22)
            route("SUM_RED", [(113.8, 107.5), cf_sum], p.B_Cu, 0.22)

            # Feedback/output node: straight through U1.OUT -> R3, with the
            # 1 Mohm/22 pF pair returning on a single vertical spine.
            route("FB_RED", [u_out, (ro_in[0], u_out[1]), ro_in], p.B_Cu, 0.22)
            route("FB_RED", [u_out, (121.2, u_out[1]), (121.2, 105.0), rf_fb], p.B_Cu, 0.22)
            route("FB_RED", [(121.2, 107.5), cf_fb], p.B_Cu, 0.22)

            route("VREF_RED", [rt_ref, (110.0, rt_ref[1]), (110.0, rb_ref[1]), rb_ref], p.B_Cu, 0.22)
            route("VREF_RED", [(110.0, cv_ref[1]), cv_ref], p.B_Cu, 0.22)
            via("VREF_RED", 112.5, 109.0)
            via("VREF_RED", 121.5, 112.8)
            route("VREF_RED", [cv_ref, (112.5, cv_ref[1]), (112.5, 109.0)], p.B_Cu, 0.22)
            route("VREF_RED", [(112.5, 109.0), (112.5, 111.7), (121.5, 111.7), (121.5, 112.8)], p.F_Cu, 0.22)
            route("VREF_RED", [(121.5, 112.8), (u_ref[0], 112.8), u_ref], p.B_Cu, 0.22)

            # Supply stays at the outside edge until it reaches the local
            # decoupler and op-amp; this keeps it away from the summing node.
            via("3V3_RED", 102.2, 125.5)
            route("3V3_RED", [j_vdd, (j_vdd[0], 130.0), (106.8, 130.0), (106.8, 125.5), (102.2, 125.5)], p.F_Cu, 0.4)
            route("3V3_RED", [(102.2, 125.5), (102.2, 106.0), (rt_vdd[0], 106.0), rt_vdd], p.B_Cu, 0.4)
            route("3V3_RED", [rt_vdd, (111.55, rt_vdd[1]), (111.55, cd_vdd[1]), cd_vdd], p.B_Cu, 0.35)
            via("3V3_RED", 112.5, 102.5)
            via("3V3_RED", 116.5, 108.5)
            route("3V3_RED", [cd_vdd, (112.5, cd_vdd[1]), (112.5, 102.5)], p.B_Cu, 0.35)
            route("3V3_RED", [(112.5, 102.5), (116.5, 102.5), (116.5, 108.5)], p.F_Cu, 0.35)
            route("3V3_RED", [(116.5, 108.5), (116.5, u_vdd[1]), u_vdd], p.B_Cu, 0.35)

            route("OUT_RED", [out_start, (126.0, out_start[1]), (126.0, 120.0), (110.5, 120.0), grove_out], p.B_Cu, 0.3)
        else:
            route("SUM_IR", [d_k, (d_k[0], 113.5), (149.65, 113.5), u_inv], p.B_Cu, 0.22)
            route("SUM_IR", [(149.65, 113.5), (147.5, 113.5), (147.5, 105.0), rf_sum], p.B_Cu, 0.22)
            route("SUM_IR", [(147.5, 107.5), cf_sum], p.B_Cu, 0.22)

            route("FB_IR", [u_out, (ro_in[0], u_out[1]), ro_in], p.B_Cu, 0.22)
            route("FB_IR", [u_out, (153.0, u_out[1]), (153.0, 105.0), rf_fb], p.B_Cu, 0.22)
            route("FB_IR", [(153.0, 107.5), cf_fb], p.B_Cu, 0.22)

            route("VREF_IR", [rt_ref, (160.0, rt_ref[1]), (160.0, rb_ref[1]), rb_ref], p.B_Cu, 0.22)
            route("VREF_IR", [(160.0, cv_ref[1]), cv_ref], p.B_Cu, 0.22)
            via("VREF_IR", 159.5, 106.5)
            via("VREF_IR", 153.5, 113.0)
            route("VREF_IR", [cv_ref, (159.5, cv_ref[1]), (159.5, 106.5)], p.B_Cu, 0.22)
            route("VREF_IR", [(159.5, 106.5), (159.5, 104.0), (153.5, 104.0), (153.5, 113.0)], p.F_Cu, 0.22)
            route("VREF_IR", [(153.5, 113.0), (u_ref[0], 113.0), u_ref], p.B_Cu, 0.22)

            via("3V3_IR", 167.8, 125.5)
            route("3V3_IR", [j_vdd, (j_vdd[0], 130.0), (163.2, 130.0), (163.2, 125.5), (167.8, 125.5)], p.F_Cu, 0.4)
            route("3V3_IR", [(167.8, 125.5), (167.8, 106.0), (rt_vdd[0], 106.0), rt_vdd], p.B_Cu, 0.4)
            route("3V3_IR", [rt_vdd, (158.45, rt_vdd[1]), (158.45, cd_vdd[1]), cd_vdd], p.B_Cu, 0.35)
            via("3V3_IR", 157.5, 102.5)
            via("3V3_IR", 148.5, 108.5)
            route("3V3_IR", [cd_vdd, (157.5, cd_vdd[1]), (157.5, 102.5)], p.B_Cu, 0.35)
            route("3V3_IR", [(157.5, 102.5), (157.5, 101.5), (146.5, 101.5), (146.5, 108.5), (148.5, 108.5)], p.F_Cu, 0.35)
            route("3V3_IR", [(148.5, 108.5), (148.5, u_vdd[1]), u_vdd], p.B_Cu, 0.35)

            # Give the small SOT-23 ground pad an explicit escape into the
            # channel plane; otherwise nearby signal clearances can starve one
            # of its thermal spokes.
            route("GND_IR", [pad_xy(u, 2), (155.5, pad_xy(u, 2)[1]), (155.5, 113.5)], p.B_Cu, 0.35)

            via("OUT_IR", 157.5, 107.5)
            route("OUT_IR", [out_start, (157.5, 107.5)], p.B_Cu, 0.3)
            route("OUT_IR", [(157.5, 107.5), (160.0, 107.5), (160.0, 120.0), (153.5, 120.0), grove_out], p.F_Cu, 0.3)

        # Separate channel-local bottom copper plane.  Ground is never joined
        # across the optical partition on this board.
        zone = p.ZONE(board)
        zone.SetLayer(p.B_Cu)
        zone.SetNet(nets[f"GND_{ch}"])
        zone.SetLocalClearance(mm(0.25))
        zone.SetPadConnection(p.ZONE_CONNECTION_THERMAL)
        zone.SetThermalReliefGap(mm(0.25))
        zone.SetThermalReliefSpokeWidth(mm(0.35))
        zone.SetMinThickness(mm(0.2))
        outline = zone.Outline()
        outline.NewOutline()
        left, right = (100.6, 133.0) if ch == "RED" else (137.0, 169.4)
        for x, y in ((left, 100.6), (right, 100.6), (right, 131.4), (left, 131.4)):
            outline.Append(int(mm(x)), int(mm(y)))
        board.Add(zone)

    # Output header: signal and matching return for each isolated channel.
    j1, j2, j3 = footprints["J1"], footprints["J2"], footprints["J3"]
    route("OUT_RED", [pad_xy(j1, 1), (pad_xy(j1, 1)[0], 124.0), (pad_xy(j3, 1)[0], 124.0), pad_xy(j3, 1)], p.F_Cu, 0.3)
    route("OUT_IR", [pad_xy(j2, 1), (pad_xy(j2, 1)[0], 122.5), (pad_xy(j3, 3)[0], 122.5), pad_xy(j3, 3)], p.F_Cu, 0.3)
    route("GND_IR", [pad_xy(j3, 4), (pad_xy(j3, 4)[0], 130.0), (137.2, 130.0)], p.B_Cu, 0.4)

    # Reference labels and mechanical keep-out marks.
    for ch, cx, jx in (("RED", 115.75, 110.5), ("IR", 154.25, 153.5)):
        silk(f"{ch} / " + ("A2" if ch == "RED" else "A0"), cx, 102.0, 1.15)
        silk("K", cx - 2.55, 113.0, 0.8)
        silk("A", cx + 2.55, 113.0, 0.8)
        silk("S NC V G", jx + 3, 130.5, 0.8)
        line((cx - 1, 116), (cx + 1, 116), p.Dwgs_User, 0.1)
        line((cx, 115), (cx, 117), p.Dwgs_User, 0.1)
    silk("R GR I GI", 125.81, 130.5, 0.8)
    silk("PPG BPW34 RX v1.1", 135, 102.0, 0.9)
    silk("3.3V ONLY", 135, 104.5, 0.8)
    silk("70 x 32 mm", 135, 107.0, 0.8)
    silk("BPW34 MARK = K", 135, 120.0, 0.8)
    silk("DATN: PPG-Simulator", 135, 101.8, 0.82, p.B_SilkS, True)
    silk("Nguyen Nhat Huy - Pham Thanh Vy", 135, 103.8, 0.8, p.B_SilkS, True)

    # Rear-side connector markings are placed pad-by-pad.  Because these are
    # mirrored B.SilkS items at the physical pad X coordinate, their apparent
    # left-to-right order remains correct when the finished PCB is flipped over.
    rear_connectors = {
        "J1": ("J1 A2 RED", ("R", "N", "V", "GR")),
        "J3": ("J3 ADS", ("R", "GR", "I", "GI")),
        "J2": ("J2 A0 IR", ("I", "N", "V", "GI")),
    }
    for ref, (title, labels) in rear_connectors.items():
        fp = footprints[ref]
        pad_positions = [pad_xy(fp, pin) for pin in range(1, 5)]
        silk(title, sum(x for x, _ in pad_positions) / 4, 125.3, 0.8, p.B_SilkS, True)
        for pin, label in enumerate(labels, 1):
            x, _ = pad_xy(fp, pin)
            silk(label, x, 130.0, 0.8, p.B_SilkS, True, 90)

    for ref, channel in (("D1", "RED"), ("D2", "IR")):
        fp = footprints[ref]
        x1, _ = pad_xy(fp, 1)
        x2, _ = pad_xy(fp, 2)
        silk("K", x1, 118.8, 0.8, p.B_SilkS, True)
        silk("A", x2, 118.8, 0.8, p.B_SilkS, True)
        silk(f"{ref} {channel}", (x1 + x2) / 2, 120.2, 0.8, p.B_SilkS, True)

    silk("R=OUT_RED  I=OUT_IR", 135, 108.0, 0.8, p.B_SilkS, True)
    silk("V=3V3  N=NC", 135, 110.0, 0.8, p.B_SilkS, True)
    silk("GR/GI=CHANNEL GND", 135, 112.0, 0.8, p.B_SilkS, True)

    # Keep reference designators horizontal and aligned.  Stock footprint
    # labels rotate with each passive and make an otherwise regular grid look
    # scattered when the board is viewed from the rear.
    reference_positions = {
        "R5": (106.4, 106.0), "R7": (106.4, 111.0), "C3": (111.5, 113.3),
        "C5": (110.5, 100.9), "R1": (119.0, 103.3), "C1": (123.0, 107.5),
        "U1": (119.0, 113.4), "R3": (128.0, 109.55),
        "R6": (163.6, 106.0), "R8": (163.6, 111.0), "C4": (158.5, 113.3),
        "C6": (159.5, 100.9), "R2": (151.0, 103.3), "C2": (147.0, 107.5),
        "U2": (151.0, 113.4), "R4": (155.5, 105.8),
    }
    for ref, position in reference_positions.items():
        label = footprints[ref].Reference()
        label.SetPosition(vec(*position))
        label.SetTextAngle(p.EDA_ANGLE(0, p.DEGREES_T))
        label.SetTextSize(vec(0.8, 0.8))
        label.SetTextThickness(mm(0.11))

    line((133.5, 100.5), (133.5, 131.5), p.Dwgs_User, 0.1)
    line((136.5, 100.5), (136.5, 131.5), p.Dwgs_User, 0.1)
    p.ZONE_FILLER(board).Fill(board.Zones())
    p.SaveBoard(str(HERE / f"{NAME}.kicad_pcb"), board)


def write_bom():
    rows = [
        ("D1,D2", "BPW34", "Vishay leaded top-view photodiode", "2", "Cathode-marked lead -> square K pad"),
        ("U1,U2", "OPA333AIDBVR", "SOT-23-5", "2", "MCP6001T-I/OT is a pin-compatible low-cost alternative"),
        ("R1,R2", "1M 1%", "0805", "2", "TIA feedback; reduce to 330k if output saturates"),
        ("C1,C2", "22pF C0G/NP0 50V", "0805", "2", "TIA stability capacitor"),
        ("R3,R4", "100R", "0805", "2", "ADC/cable output isolation"),
        ("R5,R6", "100k 1%", "0805", "2", "VREF divider top"),
        ("R7,R8", "10k 1%", "0805", "2", "VREF divider bottom"),
        ("C3,C4", "100nF X7R 25V", "0805", "2", "VREF filter"),
        ("C5,C6", "100nF X7R 25V", "0805", "2", "Op-amp supply bypass"),
        ("J1,J2", "1x4 male 2.00mm", "THT vertical", "2", "Grove A2 RED and A0 IR"),
        ("J3", "1x4 male 2.54mm", "THT vertical", "1", "OUT_RED,GND_RED,OUT_IR,GND_IR"),
        ("H1-H4", "M3 NPTH", "3.2mm drill", "4", "M3x4 into adapter pilot holes"),
    ]
    with (HERE / "BOM.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["References", "Value", "Package", "Qty", "Notes"])
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kicad-share", required=True, type=Path)
    parser.add_argument("--cli", required=True)
    args = parser.parse_args()
    (HERE / "reports").mkdir(exist_ok=True)
    project = {
        "meta": {"filename": NAME + ".kicad_pro", "version": 1},
        "board": {"design_settings": {"rules": {"min_clearance": 0.2, "min_track_width": 0.2, "min_through_hole_diameter": 0.3, "min_hole_clearance": 0.25, "min_copper_edge_clearance": 0.3}}},
        "net_settings": {"classes": [{"name": "Default", "clearance": 0.25, "track_width": 0.3, "via_diameter": 0.8, "via_drill": 0.4, "microvia_diameter": 0.3, "microvia_drill": 0.1, "diff_pair_width": 0.2, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25}]},
    }
    (HERE / f"{NAME}.kicad_pro").write_text(json.dumps(project, indent=2) + "\n")
    write_schematic()
    write_pcb(args.kicad_share, args.cli)
    write_bom()


if __name__ == "__main__":
    main()
