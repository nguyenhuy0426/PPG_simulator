# Bộ PCB PPG — bản thu gọn và panel V-cut

**Gói gửi nhà in: `PPG_3boards_VCUT_panel.zip`.** Giải nén và đọc `SEND_TO_FAB.md` trước khi sản xuất.

Panel 70 × 80 mm chứa OPT101 70 × 20 mm, BPW34 70 × 20 mm và driver 70 × 40 mm. Hai đường V-score toàn chiều ngang ở 20/40 mm tính từ cạnh trên. Đồng cách tâm đường cắt ít nhất 1,5 mm mỗi phía; ba thiết kế không nối điện với nhau. Báo nhà in đây là **3 thiết kế khác nhau trên một panel** và xác nhận quy trình V-score.

- `ppg_panel/`: PCB panel, Gerber/drill, bản vẽ V-cut, kết quả kiểm tra và báo cáo điện.
- `opt101_receiver_kicad/opt101_receiver/`, `bpw34_receiver/`, `led_ir_driver/`: schematic/PCB nguồn và gá mới.
- Ba file ZIP board lẻ giữ cùng phiên bản mới nhất để xem/chỉnh hoặc in riêng; không trộn Gerber của chúng vào đơn hàng panel.

Đã kiểm tra ERC/DRC và parity ba nguồn; panel đối chiếu net/pad/track và lỗ/V-cut. Kết quả CAD không thay cho đo điện, nhiễu, ổn định vòng driver và thử lắp module thực. Xem `ppg_panel/ELECTRICAL_REVIEW.md`.
