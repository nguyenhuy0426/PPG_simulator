# Hồ sơ hàn dán (SMT) — panel PPG 70 × 80 mm

Gửi cho xưởng hàn dán: `PPG_panel_BOM_SMT.xlsx` (hoặc hai file CSV) cùng
Gerber trong `../fabrication/`.

| File | Nội dung |
|---|---|
| `PPG_panel_BOM_SMT.xlsx` | BOM hàn dán, CPL, vị trí DNP, linh kiện khách tự hàn, ghi chú cho xưởng |
| `PPG_panel_BOM_SMT.csv` | BOM hàn dán (11 mã, 38 linh kiện / bộ) |
| `PPG_panel_CPL_SMT.csv` | Toạ độ đặt linh kiện, cùng gốc với Gerber; có thêm toạ độ theo từng board |
| `make_assembly.py`, `panel_parts.json` | Script sinh lại các file trên từ `../ppg_panel.kicad_pcb` |

Một bộ là một panel gồm ba board: OPT101 RX, BPW34 RX và LED/IR driver v2.0.
Xưởng hàn **38 linh kiện SMD trên hai mặt** (TOP 15, BOTTOM 23); driver v2.0
thêm TX_R11–R14 (100 Ω 1% 0805, mặt TOP) — khác TX_R4/R9 (100 Ω 1206).
Không lắp TX_C2 và TX_C4 (DNP); stencil TOP vẫn có lỗ paste tại hai vị trí này.
TX_JP1–JP4 là jumper hàn 3 pad, không có linh kiện, không có lỗ paste: **giữ hở**.

Khách tự hàn các linh kiện xuyên lỗ: OPT101P, BPW34 và các header/socket
(kể cả TX_J8/TX_J9, header 1×4 bước 2,00 mm cho I²C).
LM358P/đế DIP-8 (TX_U1) và 2N4401 (TX_Q1/Q2) cũng là linh kiện xuyên lỗ,
không nằm trong BOM hàn dán.

Nguồn dữ liệu: `../ppg_panel.kicad_pcb` (driver v2.0). Toạ độ khớp
`kicad-cli pcb export pos` (KiCad 10.0.6); 34 dòng CPL cũ không đổi so với bản
trước, thêm 4 dòng TX_R11–R14. DRC trên panel cho 0 lỗi và 0 pad chưa nối.
Mã linh kiện chỉ là gợi ý; dùng mã tương đương có cùng thông số. Các kết quả
này chưa phải đo kiểm trên board đã lắp.

Sinh lại: chạy `make_assembly.py --export` bằng Python có pcbnew (KiCad 10),
rồi `make_assembly.py` bằng Python có openpyxl.
