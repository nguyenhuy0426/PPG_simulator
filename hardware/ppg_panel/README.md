# Panel V-cut PPG — 70 × 80 mm

Mở `ppg_panel.kicad_pro` / `ppg_panel.kicad_pcb` bằng KiCad 10.
Đây là **panel gia công gồm ba thiết kế khác nhau**, mỗi thiết kế một bản:

| Vị trí từ cạnh trên | Board sau tách | Kích thước |
|---|---|---|
| Y = 0–20 mm | OPT101 receiver v1.5 | 70 × 20 mm |
| Y = 20–40 mm | BPW34 receiver v1.4 | 70 × 20 mm |
| Y = 40–80 mm | LED/IR driver v1.9 | 70 × 40 mm |

Hai đường V-cut ở **Y = 20 và 40 mm**, chạy thẳng hết chiều ngang 70 mm.
Tọa độ trong file KiCad: góc trên trái (50,50); các đường cắt Y=70 và 90.
Không có khe phay giữa board: V-cut dùng chung đường biên, khoảng hở cơ khí
trước khi bẻ bằng 0. Sau khi tách là ba PCB độc lập. Toàn bộ đồng, pad, via
và vùng đồng cách tâm đường cắt ít nhất **0,6 mm mỗi phía**; không có đường
điện xuyên qua đường cắt. Các net và reference trong panel được đặt tiền tố
OPT/BPW/TX để không nối nhầm GND hoặc nguồn giữa các board.

**Chỉ dẫn nhà in:** FR-4 dày 1,6 mm, 2 lớp đồng 1 oz, soldermask hai mặt,
silkscreen trắng hai mặt. `Edge_Cuts` là duy nhất đường bao phay ngoài.
File `ppg_panel-User_Comments.gbr` chỉ chứa hai **tâm đường V-score hai mặt**;
không coi là lớp đồng, không phay thành hai khe xuyên. Bản vẽ
`reports/vcut_drawing.pdf` giải thích vị trí và kích thước. Nhà in chọn độ
sâu V-score theo quy trình FR-4 1,6 mm và xác nhận dung sai/khoảng hở của họ.
Tách panel trước khi hàn/cắm IC, module và photodiode; làm sạch phần ba via
ở mép bẻ nếu cần. Không cấp điện cho cả panel như một board hệ thống.

Diện tích PCB giảm **75,6 → 56 cm² (25,93%)**. Đây là giảm diện tích thực,
không phải bảo đảm giảm giá tương ứng: cần báo đúng **3 designs / panel**,
vì nhà in có thể tính phí ghép thiết kế hoặc V-cut. Không cần thanh biên cho
bộ PCB trần này; nếu nhà in yêu cầu thanh biên thì diện tích báo giá tăng.

## Kiểm tra

- Cả ba source: ERC/DRC và đối chiếu schematic–PCB.
- Panel: DRC, 0 kết nối thiếu; kiểm tra độc lập net, pad, drill, vị trí và
  từng đoạn đồng so với source, khoảng hở lỗ khoan và V-cut.
- `reports/panel_audit.json` chứa bề rộng đường theo từng net và khoảng cách
  tới từng lỗ; `reports/manifest.json` lưu SHA-256 của ba PCB nguồn.
- `ELECTRICAL_REVIEW.md` giải thích đường nguồn, RC và những giới hạn điện
  chưa thể chứng minh bằng CAD. DRC sạch không chứng minh mạch đã chạy thật.

Schematic vẫn ở ba project riêng. Không cập nhật panel từ một schematic
trống và không sửa điện trực tiếp trong panel. Sau khi sửa source, chạy
`build_panel.py`, DRC refill, `verify_panel.py`, rồi xuất lại Gerber/drill.
Scripts dùng Python có `pcbnew` của KiCad 10.

## Gá in 3D mới

Hai receiver dùng hai biến thể thanh U trong `docs/system_3d/out/print_bambu_180/`:
`14_ga_chu_U_OPT101_70x20.stl`, `15_ga_chu_U_BPW34_70x20.stl`.
Driver dùng `16_ga_driver_70x40.stl`. Xem mechanical/README.md của từng project.
Trục quang danh nghĩa và khoảng cách hai kênh 38,5 mm được giữ nguyên.
