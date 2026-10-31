# Hồ sơ hàn dán (SMT) — LED/IR driver v2.0, board lẻ 70 × 40 mm

Gửi cho xưởng hàn dán: `PPG_LED_IR_driver_BOM_SMT.xlsx` (hoặc hai file CSV)
cùng Gerber trong `../fabrication/`.

| File | Nội dung |
|---|---|
| `PPG_LED_IR_driver_BOM_SMT.xlsx` | BOM hàn dán, CPL, vị trí DNP/jumper, linh kiện khách tự hàn, ghi chú cho xưởng |
| `PPG_LED_IR_driver_BOM_SMT.csv` | BOM hàn dán (6 mã, 14 linh kiện / board) |
| `PPG_LED_IR_driver_CPL_SMT.csv` | Toạ độ đặt linh kiện, cùng gốc với Gerber; có thêm toạ độ tính từ góc dưới-trái board |
| `driver_parts.json` | Dữ liệu footprint xuất từ `../led_ir_driver.kicad_pcb` |

Xưởng hàn **14 linh kiện SMD**: TOP 13, BOTTOM 1 (tụ hóa C7). Không lắp C2/C4
(DNP); stencil TOP vẫn có lỗ paste tại hai vị trí này. JP1–JP4 là jumper hàn
3 pad, không có linh kiện, không có lỗ paste: **giữ hở**. Khách tự hàn các
header/socket, đế DIP-8 + LM358P và 2N4401.

Toạ độ CPL khớp `kicad-cli pcb export pos --smd-only` (KiCad 10.0.6), trừ C2/C4
là DNP. Mã linh kiện chỉ là gợi ý; dùng mã tương đương có cùng thông số. Chưa
đo kiểm trên board đã lắp.

Sinh lại: chạy `../../ppg_panel/assembly/make_assembly.py --driver --export`
bằng Python có pcbnew (KiCad 10), rồi `make_assembly.py --driver` bằng Python
có openpyxl.
