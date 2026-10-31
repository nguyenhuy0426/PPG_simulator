#!/usr/bin/env python3
"""SMT assembly package (BOM + CPL) for the three-board PPG panel.

KiCad Python:      make_assembly.py --export   -> panel_parts.json (from ../ppg_panel.kicad_pcb)
Python + openpyxl: make_assembly.py            -> BOM/CPL CSV + XLSX for the assembly house
Add --driver to either step for the LED/IR driver board alone
(../../led_ir_driver/led_ir_driver.kicad_pcb -> ../../led_ir_driver/assembly/).

Part numbers are suggestions; any part with the same specification is acceptable.
"""
import csv
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRIVER = '--driver' in sys.argv
if DRIVER:
    # Standalone driver board: same part lines, refs carry no TX_ prefix on the PCB.
    OUT = HERE.parent.parent / 'led_ir_driver' / 'assembly'
    PCB = HERE.parent.parent / 'led_ir_driver' / 'led_ir_driver.kicad_pcb'
    PARTS_JSON = OUT / 'driver_parts.json'
    STEM = 'PPG_LED_IR_driver'
else:
    OUT = HERE
    PCB = HERE.parent / 'ppg_panel.kicad_pcb'
    PARTS_JSON = HERE / 'panel_parts.json'
    STEM = 'PPG_panel'


QTY = 'SL / 1 board' if DRIVER else 'SL / 1 bộ panel'


def disp(ref):
    return ref[3:] if DRIVER else ref


def export():
    import pcbnew as p
    board = p.LoadBoard(str(PCB))
    OUT.mkdir(exist_ok=True)
    parts = []
    for fp in board.GetFootprints():
        pos = fp.GetPosition()
        parts.append({
            'ref': ('TX_' if DRIVER else '') + fp.GetReference(), 'value': fp.GetValue(), 'footprint': str(fp.GetFPID().GetLibItemName()),
            'side': 'bottom' if fp.GetLayer() == p.B_Cu else 'top',
            # Same convention as `kicad-cli pcb export pos`: Gerber coordinates, Y up.
            'x': round(p.ToMM(pos.x), 6), 'y': round(-p.ToMM(pos.y), 6), 'rot': round(fp.GetOrientationDegrees(), 6),
            'dnp': bool(fp.GetAttributes() & p.FP_DNP),
            'pads': sorted({pad.GetAttribute() == p.PAD_ATTRIB_SMD and 'smd' or
                            pad.GetAttribute() == p.PAD_ATTRIB_NPTH and 'npth' or 'tht' for pad in fp.Pads()}),
            'paste': any(pad.IsOnLayer(p.F_Paste) or pad.IsOnLayer(p.B_Paste) for pad in fp.Pads()),
        })
    PARTS_JSON.write_text(json.dumps(sorted(parts, key=lambda d: d['ref']), indent=1) + '\n')
    print(len(parts), 'footprints ->', PARTS_JSON.name)


# Board name, left edge X and bottom edge Y (Gerber coordinates, Y up) for local coordinates.
BOARD = {'OPT': ('OPT101 RX 70x20', 50.0, 70.0), 'BPW': ('BPW34 RX 70x20', 50.0, 90.0), 'TX': ('LED/IR driver 70x40', 50.0, 130.0)}
if DRIVER:
    BOARD = {'TX': ('LED/IR driver 70x40', 100.0, 140.0)}
SIDE_VN = {'top': 'TOP (mặt trên)', 'bottom': 'BOTTOM (mặt dưới)'}

# One line per distinct part to buy and place. Refs are checked against the PCB.
LINES = [
    dict(refs='BPW_C1 BPW_C2', value='22pF', spec='Tụ gốm MLCC C0G/NP0, 50V, ±5%', pkg='0805 (2012 metric)',
         mpn='Murata GRM2165C1H220JA01D / Yageo CC0805JRNPO9BN220',
         note='BẮT BUỘC C0G/NP0 (tụ ổn định TIA). Không thay bằng X7R/Y5V.'),
    dict(refs='OPT_C1 OPT_C2 BPW_C3 BPW_C4 BPW_C5 BPW_C6 TX_C5', value='100nF', spec='Tụ gốm MLCC X7R, 50V, ±10%',
         pkg='0805 (2012 metric)', mpn='Samsung CL21B104KBCNNNC',
         note='Bypass/lọc VREF. X7R ≥25V đều dùng được; dùng 1 mã cho cả 7 vị trí.',
         note_tx='Bypass nguồn LM358 (TX_C5). X7R ≥25V đều dùng được.'),
    dict(refs='OPT_C3 OPT_C4 BPW_C7 BPW_C8', value='1uF', spec='Tụ gốm MLCC X7R, 16V, ±10%', pkg='0805 (2012 metric)',
         mpn='Samsung CL21B105KOFNNNE',
         note='Lọc RC ngõ ra. Dùng cùng 1 mã cho cả 4 vị trí (cân bằng kênh RED/IR).'),
    dict(refs='TX_C7', value='10uF', spec='Tụ hóa nhôm dán (SMD), 16V trở lên, CÓ PHÂN CỰC', pkg='SMD Ø5 x 5.4 mm (case C)',
         mpn='Tương đương bất kỳ: 10uF ≥16V, Ø5x5.4 mm',
         note='PHÂN CỰC: cực + vào pad có dấu "+" (net 5V), vạch âm trên thân tụ về phía GND. Mặt dưới board driver.'),
    dict(refs='BPW_R1 BPW_R2', value='1M', spec='Điện trở dán 1%, 1/8W', pkg='0805 (2012 metric)',
         mpn='Yageo RC0805FR-071ML', note='Điện trở hồi tiếp TIA 1MΩ — vệ sinh sạch flux quanh vị trí này.'),
    dict(refs='BPW_R5 BPW_R6', value='100k', spec='Điện trở dán 1%, 1/8W', pkg='0805 (2012 metric)',
         mpn='Yageo RC0805FR-07100KL', note=''),
    dict(refs='BPW_R7 BPW_R8 TX_R1 TX_R2 TX_R6 TX_R7', value='10k', spec='Điện trở dán 1%, 1/8W', pkg='0805 (2012 metric)',
         mpn='Yageo RC0805FR-0710KL', note='Cầu chia: phải là loại 1%.'),
    dict(refs='OPT_R1 OPT_R2 BPW_R3 BPW_R4 TX_R3 TX_R8', value='1k', spec='Điện trở dán 1%, 1/8W', pkg='0805 (2012 metric)',
         mpn='Yageo RC0805FR-071KL', note='TX_R3/TX_R8 thiết kế ghi "1k" (không yêu cầu 1%); gộp chung 1% để bớt 1 mã.'),
    dict(refs='TX_R4 TX_R9', value='100Ω', spec='Điện trở dán 1%, 0.25W (1/4W)', pkg='1206 (3216 metric)',
         mpn='Yageo RC1206FR-07100RL', note='Điện trở sense dòng LED — đúng cỡ 1206, ≥0.25W, 1%.'),
    dict(refs='TX_R11 TX_R12 TX_R13 TX_R14', value='100Ω', spec='Điện trở dán 1%, 1/8W', pkg='0805 (2012 metric)',
         mpn='Yageo RC0805FR-07100RL',
         note='Nối tiếp SCL/SDA từng module MCP4725 (driver v2.0). Cỡ 0805 — khác TX_R4/R9 cỡ 1206.'),
    dict(refs='BPW_U1 BPW_U2', value='OPA333AIDBVR', spec='Op-amp CMOS zero-drift, 1.8–5.5V (TI)', pkg='SOT-23-5 (DBV)',
         mpn='TI OPA333AIDBVR (thay thế cùng chân: Microchip MCP6001T-I/OT)',
         note='CÓ HƯỚNG: chân 1 trùng dấu tam giác trên silkscreen mặt dưới. Không dùng LM358.'),
]
DNP = ['TX_C2', 'TX_C4']
JUMPERS = ['TX_JP1', 'TX_JP2', 'TX_JP3', 'TX_JP4']
if DRIVER:
    LINES = [dict(L, refs=' '.join(r for r in L['refs'].split() if r.startswith('TX_')), note=L.get('note_tx', L['note']).replace('TX_', ''))
             for L in LINES]
    LINES = [L for L in LINES if L['refs']]


def sortkey(r):
    m = re.match(r'([A-Z]+)_([A-Z]+)(\d+)', r)
    return (['OPT', 'BPW', 'TX'].index(m.group(1)), m.group(2), int(m.group(3)))


def build():
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter

    fps = {d['ref']: d for d in json.loads(PARTS_JSON.read_text())}

    def side(r):
        return fps[r]['side']

    def board(r):
        return r.split('_')[0]

    # ---- consistency checks against the PCB ----------------------------------------------
    smd_refs = {r for r, f in fps.items() if 'smd' in f['pads']}
    placed = [r for L in LINES for r in L['refs'].split()]
    assert len(placed) == len(set(placed)), 'duplicate ref in LINES'
    assert set(placed) | set(DNP) | set(JUMPERS) == smd_refs, (set(placed) | set(DNP) | set(JUMPERS)) ^ smd_refs
    for r in DNP:
        assert fps[r]['dnp'], r
    for r in JUMPERS:
        assert fps[r]['footprint'] == 'SJ3' and fps[r]['pads'] == ['smd'], r
    for L in LINES:
        for r in L['refs'].split():
            f = fps[r]
            assert f['pads'] == ['smd'] and not f['dnp'], r
            want = L['value'].replace('Ω', 'R')
            assert f['value'].split()[0].replace('Ω', 'R').lower().startswith(want.lower()), (r, f['value'], L['value'])
    package = {'1206': 'RSense', 'SOT-23-5': 'SOT23_5_Hand', 'SMD Ø5': 'CP'}
    for L in LINES:
        for r in L['refs'].split():
            expect = next((v for k, v in package.items() if L['pkg'].startswith(k)), None)
            if expect:
                assert fps[r]['footprint'] == expect, (r, fps[r]['footprint'])
            else:
                assert fps[r]['footprint'] in ('C0805_Hand', 'R0805_Hand', 'C', 'R'), (r, fps[r]['footprint'])

    # ---- BOM rows ------------------------------------------------------------------------
    bom_rows = []
    for i, L in enumerate(LINES, 1):
        refs = sorted(L['refs'].split(), key=sortkey)
        top = [r for r in refs if side(r) == 'top']
        bot = [r for r in refs if side(r) == 'bottom']
        bom_rows.append(OrderedDict([
            ('STT', i), ('Giá trị', L['value']), ('Mô tả / thông số', L['spec']), ('Kiểu chân (package)', L['pkg']),
            (QTY, len(refs)), ('Mặt TOP', len(top)), ('Mặt BOTTOM', len(bot)),
            ('Vị trí (Designator)', ', '.join(map(disp, refs))),
            ('Mã gợi ý (hoặc tương đương cùng thông số)', L['mpn']), ('Ghi chú', L['note']),
        ]))
    total = sum(r[QTY] for r in bom_rows)
    n_top = sum(r['Mặt TOP'] for r in bom_rows)
    n_bot = sum(r['Mặt BOTTOM'] for r in bom_rows)
    assert (total, n_top, n_bot) == ((14, 13, 1) if DRIVER else (38, 15, 23)), (total, n_top, n_bot)

    # ---- CPL rows (Gerber coordinates, same origin as the Gerber files) -------------------
    pkg_of = {r: L['pkg'].split(' (')[0] for L in LINES for r in L['refs'].split()}
    cpl_rows = []
    for r in sorted(placed, key=sortkey):
        f = fps[r]
        name, left_x, bottom_y = BOARD[board(r)]
        cpl_rows.append(OrderedDict([
            ('Designator', disp(r)), ('Val', f['value']), ('Package', pkg_of[r]), ('KiCad footprint', f['footprint']),
            ('Mid X', f'{f["x"]:.3f}'), ('Mid Y', f'{f["y"]:.3f}'), ('Rotation', f'{f["rot"]:.0f}'),
            ('Layer', 'Top' if f['side'] == 'top' else 'Bottom'),
            ('Board', name), ('Local X (mm)', f'{f["x"] - left_x:.3f}'), ('Local Y (mm)', f'{bottom_y + f["y"]:.3f}'),
        ]))

    # ---- parts NOT for the assembly house ------------------------------------------------
    self_rows = []

    def add_self(refs, item, pkg, note):
        refs = sorted((r for r in refs if not DRIVER or r.startswith('TX_')), key=sortkey)
        if not refs:
            return
        for r in refs:
            assert r in fps and 'smd' not in fps[r]['pads'], r
        self_rows.append(OrderedDict([('Vị trí', ', '.join(map(disp, refs))), ('SL', len(refs)), ('Linh kiện', item),
                                      ('Kiểu chân', pkg), ('Ai hàn', 'Khách tự hàn'), ('Ghi chú', note)]))
    add_self(['OPT_U1', 'OPT_U2'], 'OPT101P (PDIP-8) [+ đế DIP-8 7,62 mm nếu dùng]', 'THT DIP-8',
             'Footprint là đế DIP-8. Rãnh/pin 1 hướng lên cạnh có chữ RED/A2, IR/A0. Hàn thẳng IC (không đế) sẽ đổi độ cao quang so với gá.')
    add_self(['BPW_D1', 'BPW_D2'], 'Photodiode Vishay BPW34', 'THT 2 chân', 'Chân cathode (có dấu) vào pad vuông K; mặt TOP.')
    add_self(['OPT_J1', 'OPT_J2', 'BPW_J1', 'BPW_J2'], 'Header đực 1x4, bước 2,00 mm', 'THT',
             'Grove A2/A0 (header trần, không phải socket Grove).')
    add_self(['TX_J8', 'TX_J9'], 'Header đực 1x4, bước 2,00 mm (cổng I²C)', 'THT',
             'J8 = I²C module IR, J9 = I²C module RED. Thứ tự Grove: SCL, SDA, 3V3, GND (pin 1 = pad vuông = SCL).')
    add_self(['OPT_J3'], 'Header đực 1x2, bước 2,54 mm', 'THT', 'ADS1115 OUT_RED/OUT_IR.')
    add_self(['BPW_J3'], 'Header đực 1x4, bước 2,54 mm', 'THT', 'RED/GND/IR/GND.')
    add_self(['TX_J1', 'TX_J3'], 'Header CÁI (socket) 1x6, bước 2,54 mm', 'THT', 'Cắm module MCP4725 (0x60 IR, 0x61 RED).')
    add_self(['TX_J2', 'TX_J4', 'TX_J5', 'TX_J6', 'TX_J7'], 'Header đực 1x2, bước 2,54 mm', 'THT',
             'J2 = OUT IR/GND, J4 = OUT RED/GND, J7 = 5V/GND, J5/J6 = LED.')
    add_self(['TX_U1'], 'Đế DIP-8 7,62 mm + LM358P (PDIP-8)', 'THT DIP-8',
             'Linh kiện xuyên lỗ, không phải hàn dán. Rãnh pin 1 hướng lên trên board.')
    add_self(['TX_Q1', 'TX_Q2'], 'Transistor NPN 2N4401 (onsemi), E-B-C', 'THT TO-92',
             'Không thay C1815 (khác thứ tự chân). Mặt phẳng theo silkscreen, pad vuông = E.')
    for r in ['TX_H1', 'TX_H2', 'TX_H3', 'TX_H4']:
        assert fps[r]['pads'] == ['npth']
    covered = {('TX_' if DRIVER else '') + r for row in self_rows for r in row['Vị trí'].split(', ')}
    tht_refs = {r for r, f in fps.items() if r not in smd_refs and not r.startswith('TX_H')}
    assert covered == tht_refs, covered ^ tht_refs

    noplace_rows = [OrderedDict([('Vị trí', disp(r)), ('Board', BOARD[board(r)][0]), ('Mặt', SIDE_VN[side(r)]), ('Footprint', '0805'),
                                 ('Yêu cầu', 'DNP — KHÔNG đặt linh kiện. Che lỗ stencil TOP tại vị trí này (file F_Paste vẫn có lỗ paste).')])
                    for r in DNP]
    for r in JUMPERS:
        assert not fps[r]['paste'], r
        noplace_rows.append(OrderedDict([('Vị trí', disp(r)), ('Board', BOARD[board(r)][0]), ('Mặt', SIDE_VN[side(r)]),
                                         ('Footprint', 'Jumper hàn 3 pad'),
                                         ('Yêu cầu', 'Chỉ là pad đồng, không có linh kiện, không có lỗ paste. GIỮ HỞ — không hàn nối; khách tự chọn 100R/BYP sau.')]))

    notes = [
        ('Đơn vị', '1 bộ = 1 panel 70 x 80 mm chứa 3 board khác nhau (OPT101 RX, BPW34 RX, LED/IR driver v2.0). Số lượng mua = SL/bộ x số bộ + hao hụt của xưởng.'),
        ('Phạm vi xưởng', f'Chỉ hàn dán {total} linh kiện SMD / bộ, {len(LINES)} mã linh kiện. KHÔNG hàn các linh kiện xuyên lỗ ở sheet "Khach tu han", KHÔNG đặt 2 vị trí DNP và KHÔNG hàn nối 4 jumper JP1–JP4.'),
        ('Hai mặt', f'Có SMD ở cả HAI mặt: TOP {n_top} linh kiện, BOTTOM {n_bot} linh kiện. Cần stencil cho cả 2 mặt (ppg_panel-F_Paste.gbr, ppg_panel-B_Paste.gbr).'),
        ('Tệp sản xuất', 'Gerber/drill gửi kèm: ppg_panel-*.gbr và ppg_panel-*.drl. Lớp paste cho stencil: ppg_panel-F_Paste.gbr (TOP), ppg_panel-B_Paste.gbr (BOTTOM). Ảnh tham chiếu: pcb_top.png, pcb_bottom.png.'),
        ('Toạ độ', 'Mid X/Mid Y cùng gốc với file Gerber (đơn vị mm, Y âm theo KiCad). Local X/Y: tính từ góc dưới-trái của từng board sau khi tách, nhìn từ mặt TOP.'),
        ('Góc xoay', 'Rotation theo quy ước KiCad 10. Linh kiện mặt BOTTOM: xưởng kiểm tra lại hướng theo dấu chân 1/cực trên silkscreen trước khi chạy.'),
        ('Phân cực', 'TX_C7 tụ hóa: cực + vào pad có dấu "+" (net 5V). BPW_U1/U2 OPA333: chân 1 tại dấu tam giác. Các tụ gốm/điện trở không phân cực.'),
        ('Hai loại 100Ω', 'TX_R4/R9 = 100Ω 1206 0,25W (sense dòng LED). TX_R11–R14 = 100Ω 0805 (nối tiếp I²C). Không đổi chỗ hai cỡ.'),
        ('Tụ 22pF', 'BPW_C1/C2 bắt buộc C0G/NP0.'),
        ('Vệ sinh flux', 'Rửa sạch flux mặt BOTTOM board BPW34 bằng IPA (kể cả flux no-clean): nút SUM trở kháng 1 MΩ, cặn flux gây dòng rò làm sai tín hiệu.'),
        ('Tách panel', 'Thiết kế khuyến nghị tách panel TRƯỚC khi hàn. Nếu xưởng hàn nguyên panel rồi mới tách: dùng dao/máy cắt V-cut, không bẻ tay. Tụ gốm gần đường cắt nhất là BPW_C5/C6 (tâm cách đường V-cut 3,1 mm, nằm song song đường cắt).'),
        ('Kiểm tra', 'Kết quả CAD: DRC 0 lỗi, 0 pad chưa nối; giá trị footprint khớp schematic nguồn. Chưa có đo kiểm trên board đã lắp.'),
    ]
    if DRIVER:
        notes = [
            ('Đơn vị', '1 bộ = 1 board LED/IR driver v2.0, 70 x 40 mm (board lẻ, không panel). Số lượng mua = SL/bộ x số board + hao hụt của xưởng.'),
            ('Phạm vi xưởng', f'Chỉ hàn dán {total} linh kiện SMD / board, {len(LINES)} mã linh kiện. KHÔNG hàn các linh kiện xuyên lỗ ở sheet "Khach tu han", KHÔNG đặt C2/C4 (DNP) và KHÔNG hàn nối 4 jumper JP1–JP4.'),
            ('Hai mặt', f'TOP {n_top} linh kiện, BOTTOM {n_bot} linh kiện (chỉ tụ hóa C7). Stencil: led_ir_driver-F_Paste.gbr (TOP), led_ir_driver-B_Paste.gbr (BOTTOM); C7 có thể hàn tay thay cho stencil mặt dưới.'),
            ('Tệp sản xuất', 'Gerber/drill: led_ir_driver-*.gbr và led_ir_driver-*.drl. Ảnh tham chiếu: pcb_top.png, pcb_bottom.png.'),
            ('Toạ độ', 'Mid X/Mid Y cùng gốc với file Gerber (đơn vị mm, Y âm theo KiCad). Local X/Y: tính từ góc dưới-trái của board, nhìn từ mặt TOP.'),
            ('Góc xoay', 'Rotation theo quy ước KiCad 10. Linh kiện mặt BOTTOM: xưởng kiểm tra lại hướng theo dấu cực trên silkscreen trước khi chạy.'),
            ('Phân cực', 'C7 tụ hóa: cực + vào pad có dấu "+" (net 5V). Các tụ gốm/điện trở không phân cực.'),
            ('Hai loại 100Ω', 'R4/R9 = 100Ω 1206 0,25W (sense dòng LED). R11–R14 = 100Ω 0805 (nối tiếp I²C). Không đổi chỗ hai cỡ.'),
            ('Kiểm tra', 'Kết quả CAD: DRC 0 lỗi, 0 pad chưa nối; giá trị footprint khớp schematic. Chưa có đo kiểm trên board đã lắp.'),
        ]

    # ---- write CSV -----------------------------------------------------------------------
    def write_csv(path, rows):
        with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    write_csv(OUT / f'{STEM}_BOM_SMT.csv', bom_rows)
    write_csv(OUT / f'{STEM}_CPL_SMT.csv', cpl_rows)

    # ---- write XLSX ----------------------------------------------------------------------
    wb = Workbook()
    thin = Side(style='thin', color='999999')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill('solid', fgColor='DDEBF7')

    def sheet(ws, title, rows, widths, title_line=None):
        ws.title = title
        r0 = 1
        if title_line:
            ws.cell(1, 1, title_line).font = Font(bold=True, size=12)
            r0 = 3
        keys = list(rows[0].keys())
        for c, k in enumerate(keys, 1):
            cell = ws.cell(r0, c, k)
            cell.font = Font(bold=True)
            cell.fill = head_fill
            cell.border = border
            cell.alignment = Alignment(wrap_text=True, vertical='center')
        for i, row in enumerate(rows, r0 + 1):
            for c, k in enumerate(keys, 1):
                v = row[k]
                if isinstance(v, str) and re.fullmatch(r'-?\d+\.\d+', v):
                    v = float(v)
                cell = ws.cell(i, c, v)
                cell.border = border
                cell.alignment = Alignment(wrap_text=True, vertical='top')
        for c, wdt in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(c)].width = wdt
        ws.freeze_panes = ws.cell(r0 + 1, 1)
        return r0 + len(rows)

    def print_setup(ws):
        ws.page_setup.orientation = 'landscape'
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True

    # Total-quantity column driven by an editable panel-count cell (E2).
    qcol = 'SL tổng (= SL/bộ × số bộ)'
    xl_rows = []
    for row in bom_rows:
        new = OrderedDict()
        for k, v in row.items():
            new[k] = v
            if k == QTY:
                new[qcol] = 0
        xl_rows.append(new)
    ws = wb.active
    last = sheet(ws, 'BOM han dan SMT', xl_rows, [5, 13, 34, 20, 9, 12, 8, 10, 40, 38, 48],
                 'PPG LED/IR driver v2.0, board 70x40 — BOM linh kiện HÀN DÁN cho xưởng' if DRIVER else
                 'PPG panel 70x80 (OPT101 RX + BPW34 RX + LED/IR driver v2.0) — BOM linh kiện HÀN DÁN cho xưởng')
    ws.cell(2, 1, 'Số board cần hàn:' if DRIVER else 'Số bộ (panel) cần hàn:').font = Font(bold=True)
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=4)
    ws.cell(2, 1).alignment = Alignment(horizontal='right')
    cnt = ws.cell(2, 5, 1)
    cnt.font = Font(bold=True)
    cnt.border = border
    cnt.fill = PatternFill('solid', fgColor='FFF2CC')
    ws.cell(2, 6, '← sửa ô vàng; cột SL tổng tự tính').font = Font(italic=True, color='666666')
    for i in range(4, last + 1):
        ws.cell(i, 6, f'=E{i}*$E$2').border = border
    ws.cell(last + 1, 4, 'TỔNG').font = Font(bold=True)
    for c, v in ((5, f'=SUM(E4:E{last})'), (6, f'=SUM(F4:F{last})'), (7, f'=SUM(G4:G{last})'), (8, f'=SUM(H4:H{last})')):
        ws.cell(last + 1, c, v).font = Font(bold=True)
    ws.print_title_rows = '3:3'
    sheet(wb.create_sheet(), 'Vi tri CPL', cpl_rows, [11, 22, 18, 14, 10, 10, 9, 8, 22, 12, 12])
    sheet(wb.create_sheet(), 'KHONG dat linh kien', noplace_rows, [10, 22, 18, 16, 80])
    sheet(wb.create_sheet(), 'Khach tu han', self_rows, [32, 5, 44, 12, 14, 70],
          'KHÔNG giao xưởng hàn dán — khách tự hàn sau (linh kiện xuyên lỗ)')
    sheet(wb.create_sheet(), 'Ghi chu cho xuong', [OrderedDict([('Mục', a), ('Nội dung', b)]) for a, b in notes], [16, 120])
    for w in wb.worksheets:
        print_setup(w)
    wb.save(OUT / f'{STEM}_BOM_SMT.xlsx')
    print('SMD placements', total, 'top', n_top, 'bottom', n_bot, 'part codes', len(LINES))


if __name__ == '__main__':
    export() if '--export' in sys.argv else build()
