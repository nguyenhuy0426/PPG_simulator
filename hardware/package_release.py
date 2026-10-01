#!/usr/bin/env python3
"""Package the current checked CAD and manufacturing files; omit editor caches."""
from pathlib import Path
import hashlib
import json
import zipfile

HERE = Path(__file__).resolve().parent
SOURCES = [
    (HERE / "opt101_receiver_kicad/opt101_receiver", "PPG_OPT101_receiver.zip"),
    (HERE / "bpw34_receiver", "PPG_BPW34_receiver.zip"),
    (HERE / "led_ir_driver", "PPG_LED_IR_driver.zip"),
]

def files(folder):
    for p in sorted(folder.rglob("*")):
        if not p.is_file(): continue
        if any(x in {"__pycache__", ".history", ".git"} or x.endswith("-backups") for x in p.parts): continue
        if p.name.startswith(("~", ".~")) or p.suffix in {".pyc", ".kicad_prl", ".lck", ".bak", ".tmp"}: continue
        yield p

def write_zip(path, entries):
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()}
    entries["SHA256SUMS.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(entries.items()): z.writestr(name, data)
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        for name, expected in manifest.items(): assert hashlib.sha256(z.read(name)).hexdigest() == expected
    print(f"{path.name}: {len(entries)} files, {path.stat().st_size:,} bytes; CRC/SHA-256 verified")

def main():
    for folder, name in SOURCES:
        write_zip(HERE/name, {str(p.relative_to(folder.parent)): p.read_bytes() for p in files(folder)})
    entries = {}
    for folder in [HERE/"ppg_panel"] + [d for d, _ in SOURCES]:
        for p in files(folder):
            # Only the panel Gerbers are manufacturing inputs in the combined ZIP.
            if folder.name != "ppg_panel" and "fabrication" in p.relative_to(folder).parts: continue
            entries[str(Path("hardware")/p.relative_to(HERE))] = p.read_bytes()
    entries["SEND_TO_FAB.md"] = """# PPG: manufacture ONE 70 x 110 mm V-score panel

Manufacturing input: **hardware/ppg_panel/fabrication/** only.
Read **hardware/ppg_panel/reports/vcut_drawing.pdf** and **hardware/ppg_panel/README.md**.
2 copper layers, FR-4 1.6 mm, 1 oz, mask and white silkscreen on both sides.
Three DIFFERENT designs, one copy each: OPT101 70x30, BPW34 70x30, LED/IR 70x50 mm.
Two full-width V-score lines at Y=30/60 mm from the top edge; score both sides.
The User_Comments Gerber is a V-score guide, NOT copper and NOT a milling slot.
Edge_Cuts is only the outer rectangle. Copper clearance to score centre >=0.60 mm each side.
Factory to confirm score depth/tolerances and price for a three-design panel.
Depanel before assembly. Source projects and mechanical STLs are reference material, not extra PCB quantities.

Gói này chỉ có một bộ Gerber sản xuất: panel trong hardware/ppg_panel/fabrication/.
Không sản xuất thêm các PCB lẻ từ thư mục source. File *_print.stl là gá in 3D, không thuộc gia công PCB.
Schematic/BOM, báo cáo kiểm tra và giới hạn thử nghiệm nằm trong các project và ELECTRICAL_REVIEW.md.
Thiết kế đã kiểm tra CAD; chưa đo kiểm analog trên PCB thực.
""".encode()
    write_zip(HERE/"PPG_3boards_VCUT_panel.zip", entries)

if __name__ == "__main__": main()
