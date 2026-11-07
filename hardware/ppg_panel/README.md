# Panel V-cut PPG — 2 board, 70 × 60 mm

Mở ppg_panel.kicad_pro / ppg_panel.kicad_pcb bằng KiCad10. Panel chỉ giữ:

| Vị trí từ mép trên | Board sau tách | Kích thước |
|---|---|---|
| Y=0–20mm | OPT101 hai kênh | 70×20mm |
| Y=20–60mm | LED/IR driver | 70×40mm |

Một đường V-score hai mặt ởY=20mm, chạy hết70mm. Góc trên trái KiCad(50,50), score tuyệt đốiY=70mm, mép dướiY=110mm. Edge_Cuts chỉ là khung ngoài70×60mm. User_Comments chỉ chứa tâm V-score, không phay đường này thành khe xuyên. Hai board độc lập điện, tiền tố OPT/TX, không nối qua score.

Đồng/pad/via/zone cách tâm score≥1,5mm mỗi phía, bao R/C≥2mm theo verify_panel.py. Tách panel trần trước khi hàn bằng dụng cụ phù hợp. Nhà in: FR4 1,6mm, hai lớp đồng1oz, mask/silk hai mặt, **2 designs / panel, 1 copy mỗi design**. Cần xác nhận khả năng, chiều sâu/web và dung sai V-score với nhà in. Diện tích42cm², giảm25% so với panel ba board70×80mm; không bảo đảm giảm giá tương ứng.

## Kiểm tra và phiên bản

Panel sao chép đúng hai PCB đã đi dây hiện tại, không chạy lại generator board lẻ hoặc đổi mạch điện. reports/manifest.json ghi SHA256 source. Source DRC/parity và panel DRC đã chạy lại; kết quả ở reports/drc.rpt và reports/panel_audit.json. Kiểm tra độc lập footprint/pad/net/drill/track/via, outline, score và khoảng hở.

PCB driver nguồn hiện có J1–J7, chưa có J8 của tài liệu/generator v2.0 đang chỉnh. Không dùng hợp đồng chân dự kiến J8 để đấu board này. R4/R9/SENSE đã đối chiếu PCB. PCB OPT101 ghi RED/A2, app Pi dùng RED/A4 và IR/A0: phải khớp dây và kênh đọc thực tế. Xem [hướng dẫn đo](../MEASUREMENT_GUIDE.md).

## File dùng

- fabrication/: Gerber mới, PTH/NPTH, drill map.
- reports/vcut_drawing.pdf: bản vẽ70×60mm, chỉ dẫn V-score.
- ../PPG_2boards_VCUT_panel.zip: gói sản xuất mới.
- ../archive/ppg_panel_3boards_before_20261106.zip: bản lưu trước sửa.

BPW34 đã được loại khỏi panel và thư viện/model của panel mới. Project board lẻ/gói ba board cũ là tư liệu lịch sử, không thuộc cấu hình này. Chưa gửi đặt sản xuất.

Tái sinh: Python KiCad10 chạy build_panel.py, DRC refill/save, verify_panel.py, draw_panel.py, rồi export Gerber/drill. Không cập nhật panel từ schematic trống. DRC/3D không chứng minh mạch đã chạy hoặc đường quang đã hiệu chuẩn.
