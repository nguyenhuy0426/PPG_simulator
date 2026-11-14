# Thiết kế PCB chính thức

Panel chính thức gồm hai PCB độc lập: [mạch thu OPT101 và LED/IR driver](ppg_panel/README.md), kích thước tổng 70 × 60 mm, một đường V-score. Mạch [BPW34](bpw34_receiver/README.md) vẫn được lưu riêng như phương án khác và không nằm trong panel.

Driver dùng một đầu I²C chung J2. Chân 3–6 lần lượt là SCL, SDA, 3,3 V, GND; hai module MCP4725 cần địa chỉ khác nhau. Xem [hướng dẫn driver](led_ir_driver/README.md) để đấu dây và kiểm tra trước khi cấp nguồn.

Các Gerber panel ba mạch và driver v2.0 trước đây không còn là bản hiện hành và đã được loại khỏi nhánh chính. Driver hiện tại khôi phục v1.9 và chưa áp dụng thay đổi quy tắc nhà mạch của v2.0. Trước khi sản xuất, xác nhận thông số với nhà mạch, chạy lại kiểm tra và xuất Gerber/drill từ nguồn hiện tại; CAD không thay thế thử nghiệm phần cứng.
