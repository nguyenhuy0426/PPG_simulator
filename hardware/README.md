# Bộ PCB PPG — bản thu gọn và panel V-cut

**Gói gửi nhà in: `PPG_3boards_VCUT_panel.zip`.** Giải nén và đọc `SEND_TO_FAB.md` trước khi sản xuất.

Panel 70 × 80 mm chứa OPT101 70 × 20 mm, BPW34 70 × 20 mm và driver 70 × 40 mm. Hai đường V-score toàn chiều ngang ở 20/40 mm tính từ cạnh trên. Đồng cách tâm đường cắt ít nhất 1,5 mm mỗi phía; ba thiết kế không nối điện với nhau. Báo nhà in đây là **3 thiết kế khác nhau trên một panel** và xác nhận quy trình V-score.

- `ppg_panel/`: PCB panel, Gerber/drill, bản vẽ V-cut, kết quả kiểm tra và báo cáo điện.
- `opt101_receiver_kicad/opt101_receiver/`, `bpw34_receiver/`, `led_ir_driver/`: schematic/PCB nguồn và gá mới.
- Ba file ZIP board lẻ giữ cùng phiên bản mới nhất để xem/chỉnh hoặc in riêng; không trộn Gerber của chúng vào đơn hàng panel.

Driver hiện là **v2.0**: mỗi module MCP4725 có cổng I²C riêng (J8 IR, J9 RED) qua 100 Ω hoặc jumper bỏ qua, mặc định hở; xem `led_ir_driver/README.md`.

Đã kiểm tra ERC/DRC và parity ba nguồn; panel đối chiếu net/pad/track và lỗ/V-cut. Kết quả CAD không thay cho đo điện, nhiễu, ổn định vòng driver và thử lắp module thực. Xem `ppg_panel/ELECTRICAL_REVIEW.md`.

## Layout 45°

Ba board và panel đã vát góc rẽ dây 45°. Xem [đánh giá bố trí hai mặt và V-score](ppg_panel/LAYOUT_REVIEW.md).

## Gói chỉ cho driver, hồ sơ hàn dán và quy định nhà mạch

- `PPG_LED_IR_driver.zip` và `led_ir_driver/fabrication/`: Gerber riêng cho board driver 70 × 40 mm. Dùng khi chỉ in driver; không trộn với Gerber panel.
- `led_ir_driver/assembly/`: BOM hàn dán (14 linh kiện), CPL, danh sách DNP (C2, C4) và jumper JP1–JP4 để hở.
- Theo nhà mạch, driver hiện dùng vùng đồng GND cách đồng khác **0,50 mm** và pad xuyên lỗ lớn hơn lỗ khoan ít nhất 0,6 mm (J8/J9: pad 1,50 mm, lỗ 0,80 mm). **Panel `ppg_panel/` và `PPG_3boards_VCUT_panel.zip` chưa dựng lại theo quy định này**: bản driver trong panel vẫn là bản cũ (khe 0,30 mm, pad J8/J9 1,35 mm). Dựng lại panel trước khi đặt in panel.
- `renders_original/`: ảnh 3D hai mặt của driver bản gốc (trước v2.0) và OPT101, có chip và module MCP4725. `renders_v2.1/`: ảnh driver v2.x. Hình module và OPT101P là model gần đúng.
- Tài liệu tham khảo toàn dự án: `../docs/REFERENCES.md`.
