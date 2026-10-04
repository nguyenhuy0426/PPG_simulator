# Hồ sơ hàn dán (SMT) — panel PPG 70 × 80 mm

Gửi cho xưởng hàn dán: `PPG_panel_BOM_SMT.xlsx` (hoặc hai file CSV) cùng
Gerber trong `../fabrication/`.

| File | Nội dung |
|---|---|
| `PPG_panel_BOM_SMT.xlsx` | BOM hàn dán, CPL, vị trí DNP, linh kiện khách tự hàn, ghi chú cho xưởng |
| `PPG_panel_BOM_SMT.csv` | BOM hàn dán (10 mã, 34 linh kiện / bộ) |
| `PPG_panel_CPL_SMT.csv` | Toạ độ đặt linh kiện, cùng gốc với Gerber; có thêm toạ độ theo từng board |

Một bộ là một panel gồm ba board: OPT101 RX, BPW34 RX và LED/IR driver.
Xưởng hàn **34 linh kiện SMD trên hai mặt** (TOP 11, BOTTOM 23).
Không lắp TX_C2 và TX_C4 (DNP); stencil TOP vẫn có lỗ paste tại hai vị trí này.

Khách tự hàn các linh kiện xuyên lỗ: OPT101P, BPW34 và các header/socket.
LM358P/đế DIP-8 (TX_U1) và 2N4401 (TX_Q1/Q2) cũng là linh kiện xuyên lỗ,
không nằm trong BOM hàn dán.

Nguồn dữ liệu: `../ppg_panel.kicad_pcb` (SHA-256 3cd35bd9…, trùng bản trong
`PPG_3boards_VCUT_panel.zip`). Toạ độ được xuất bằng `kicad-cli pcb export pos`
(KiCad 10.0.6). DRC trên panel cho 0 lỗi và 0 pad chưa nối; giá trị
60/60 footprint khớp schematic của ba project nguồn. Mã linh kiện chỉ là
gợi ý; dùng mã tương đương có cùng thông số. Các kết quả này chưa phải
đo kiểm trên board đã lắp.
