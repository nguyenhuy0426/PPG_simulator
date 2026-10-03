# OPT101 A0: kiểm tra mạch và kế hoạch đo sin

## Trạng thái thực nghiệm

Ngày 2026-10-01: SSH 10.42.0.193 timeout; Ethernet enx00e04c6807fc không có địa chỉ và carrier=0. SSH Wi-Fi 192.168.16.101 báo No route to host. Chưa chạy calibration, chưa có CSV hoặc kết quả sin mới. Không dùng dữ liệu mô phỏng thay phép đo vật lý.

## Kiểm tra thiết kế trong repository

Đã đọc opt101_receiver.kicad_pcb, README và xem ảnh render PCB trong hardware/opt101_receiver_kicad/opt101_receiver. Đây là kiểm tra thiết kế, không phải kiểm tra board đã lắp.

- U2 là IR/A0, nguồn /3V3_IR; chân 3 và 8 nối /GND_IR.
- Chân 4 và 5 cùng net /OUT_IR: dùng hồi tiếp 1 MΩ nội. Chân 2 để hở có chủ ý. Không cần điện trở 1 MΩ ngoài.
- C2 100 nF nối nguồn và GND. Đây là bypass nguồn, không phải lọc tín hiệu OUT.
- OUT nối trực tiếp J2.1 và J3.2, không có điện trở cách ly, tụ lọc đầu ra hoặc buffer.
- J3 là ngõ lấy tín hiệu song song: thêm dây/ADC có thể tăng tải, không phải ngõ ra cách ly.
- Hai kênh có nguồn/GND riêng trên board, chung tại HAT. Đường về nguồn của driver LED vẫn có thể gây nhiễu ngoài PCB.

Chưa chạy lại DRC/ERC; kết quả kiểm tra kết nối không chứng minh miễn nhiễu, độ tuyến tính hoặc chất lượng hàn thực tế.

## CJMCU-101 trong hình người dùng

Đính chính sau khi xem ảnh mặt sau ở bước 2: nhãn header là **1M**, không phải IN. Điện trở ngoài nối 1M–OUT. Nếu đo thông mạch xác nhận 1M tới chân 4 và OUT tới chân 5 của IC, điện trở ngoài nối tiếp hồi tiếp nội, tổng danh nghĩa 2 MΩ; thay điện trở ngoài bằng jumper 4–5 sẽ dùng hồi tiếp nội 1 MΩ. Không chỉ tháo điện trở rồi để hở. Cầu ba pad mặt sau cần đo xác nhận có nối GND, -V và COM hay không; chức năng nối mass độc lập với chọn hồi tiếp. Chưa có ảnh/đo thông mạch module thật của người dùng để xác nhận biến thể PCB.

Hình sử dụng Arduino Nano 5 V. Grove Base Hat hiện tại yêu cầu tín hiệu không vượt 3,3 V. Nguồn module đang dùng chưa được người dùng xác nhận. RC không giảm điện áp DC và không phải bộ chuyển mức.

## Thử nghiệm cần chạy khi Pi kết nối lại

1. Xác nhận nguồn OPT101, hồi tiếp, GND chung và giới hạn dòng LED/driver. Dừng tác vụ phát khác trước khi chạy bench.
2. Ghi nền LED tắt, sau đó nền khi che kín OPT101; mỗi trạng thái 10 s. Ghi A0 raw và timestamp, không lọc trước khi lưu.
3. Phát sin 1 Hz ở mức thấp trong giới hạn driver đã xác minh, tăng từng bước vừa đủ để thấy đáp ứng. Không tự dùng toàn thang DAC. Đo OUT/DAC bằng oscilloscope nếu có; lệnh DAC không chứng minh điện áp thực.
4. Giữ nguyên hình học và công suất, lần lượt 1, 2, 5, 10 Hz, mỗi mức 10 s; dừng về 0 trong finally. Ghi lệnh DAC, raw A0, lỗi I2C và thống kê timing.
5. Fit A0 = DC + a*sin(2*pi*f*t) + b*cos(2*pi*f*t), báo biên độ, pha, RMS phần dư, méo hài và tỷ lệ nằm sát rail. Kiểm tra cả plateau dưới rail ADC vì OPT101 có thể bão hòa trước ADC.
6. Lặp lại sau khi che sáng, rút ngắn dây, rồi thêm RC; chỉ đổi một yếu tố mỗi lần. Không gọi tỷ số sin/phần dư là SNR thuần khi phần dư chứa méo.

Lưu ý calibration hiện tại dùng start_calibration(frequency_hz, amplitude_mv), chạy cả hai DAC. Amplitude trong giao diện được ghi là 0-to-peak, không được diễn giải thành ±amplitude quanh DC. Muốn cô lập xuyên kênh cần bench điều khiển riêng IR và RED.

## Điều chỉnh đề xuất để thử

Ưu tiên che ánh sáng ngoài, cố định LED–sensor, GND chung và dây OUT/GND ngắn. Bổ sung 100 nF tại nguồn nếu module chưa có; có thể thêm 4,7–10 µF gần module.

Mạng thử ở đầu vào ADC: OUT -- 4,7 kΩ -- A0; 1 µF từ A0 xuống GND. fc = 1/(2*pi*R*C) ≈ 33,9 Hz. Đây là giá trị khởi đầu cần đo lại, không phải thiết kế đã được xác nhận trên HAT. Biên độ lý tưởng ở 10 Hz còn khoảng 95,9%, pha khoảng -16,5 độ. Lọc một cực không đủ loại mạnh 50/100 Hz; không sửa được clipping hoặc thiếu ánh sáng. Không mắc tụ 1 µF trực tiếp vào OUT.

Nếu bão hòa do quá sáng, giảm ánh sáng/công suất hoặc điều chỉnh mạng hồi tiếp đúng topology; điện trở OUT–GND không thay thế thao tác này. Chưa thay đổi PCB hay Gerber trước khi xác định nguyên nhân bằng phép đo.

## Nguồn

- TI OPT101 datasheet, sections 8.3.2–8.3.5, 9.1, 10–11: https://www.ti.com/lit/ds/symlink/opt101.pdf
- Grove Base Hat, giới hạn 3,3 V: https://wiki.seeedstudio.com/Grove_Base_Hat_for_Raspberry_Pi/
- Hình và hướng dẫn người dùng đang theo: https://srituhobby.com/cjmcu-101-opt101-analog-light-sensor-with-arduino/
