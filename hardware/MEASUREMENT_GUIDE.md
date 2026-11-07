# Đo V_sense, dòng LED và đáp ứng OPT101

Áp dụng cho PCB đã đi dây hiện tại, hai board OPT101 và LED/IR driver. Các số dưới là **dự kiến tính toán**, chưa phải kết quả đo. Dùng đồng hồ số và oscilloscope hai kênh, probe×10 đã bù và cài đúng hệ số trên scope.

## 1. Nối que đo đúng điểm

Tắt nguồn trước khi kẹp probe hoặc thay dây. Mọi ground clip của scope thường nối chung và nối đất bảo vệ: chỉ kẹp vào GND mạch đã xác nhận. Không kẹp ground clip vào cathode LED, SENSE, ngõ ra DAC hoặc nguồn5V. Không bỏ dây tiếp địa scope. Xem [hướng dẫn Tektronix](https://www.tek.com/en/documents/primer/setting-and-using-oscilloscope).

| Đo | Đầu đỏ / tip probe | Đầu đen / ground clip |
|---|---|---|
| V_sense IR | R4 pad1, net SENSE_IR, cùng Q1 emitter và LM358 chân2 | R4 pad2, net GND |
| V_sense RED | R9 pad1, net SENSE_RED, cùng Q2 emitter và LM358 chân6 | R9 pad2, net GND |
| Điện áp DAC IR | J1 pad1 DAC_IR, hoặc R1 đầu DAC | GND mạch đã xác nhận |
| Điện áp DAC RED | J3 pad1 DAC_RED, hoặc R6 đầu DAC | GND mạch đã xác nhận |
| RX RED sau lọc | OPT101 board J1 pin1 OUT_RED | J1 pin4 GND_RED |
| RX IR sau lọc | OPT101 board J2 pin1 OUT_IR | J2 pin4 GND_IR |
| RX trước lọc | OPT101 U1 chân5(RED) / U2 chân5(IR) | GND của cùng kênh |

Đọc **số pad**, không đoán theo hướng trái/phải của ảnh hoặc màu dây. Mạch driver dùng R4/R9=100Ω. PCB driver thực tế có J1–J7, chưa có J8 của tài liệu/generator v2.0 dự kiến. Điểm đo trên đã đối chiếu trực tiếp PCB.

PCB OPT101 ghi RED/A2, nhưng app Pi hiện dùng IR/A0 và RED/A4, có thể tắt A4. Kiểm tra dây/kênh được bật trước khi dùng số ADC. Nếu A4 đang tắt, đo scope trực tiếp OUT_RED vẫn thực hiện được. Không thay đổi dây theo nhãn A2 mà không đổi cấu hình tương ứng.

## 2. Dòng từ điện trở sense

V_sense là điện áp hai đầu R4/R9, không phải điện áp thuận của LED.

`I_emitter = V_sense / R_sense`

Với100Ω: `I_emitter[mA] = 10 × V_sense[V]`. Dòng qua LED là dòng collector: `I_LED = I_emitter − I_base`, nên phép đo sense chỉ **xấp xỉ** dòng LED. Dùng R thực đo/sai số1% khi tính sai số. Đây là đo shunt thấp, xem [Tektronix về đo dòng qua sense resistor](https://www.tek.com/en/documents/application-note/making-accurate-current-measurements-power-supplies-oscilloscopes).

| V_DAC dự kiến | V_sense dự kiến≈V_DAC/2 | I_emitter dự kiến |
|---:|---:|---:|
| 0,2V | 0,1V | 1mA |
| 0,5V | 0,25V | 2,5mA |
| 1,0V | 0,5V | 5mA |
| 1,5V | 0,75V | 7,5mA |
| 2,0V | 1,0V | 10mA |

Chỉ tăng sau khi xác nhận đúng nguồn, cực LED và không bão hòa. Cầu chia10k/10k và vòng LM358 tạo quan hệ dự kiến trên khi còn đủ headroom. Không coi bảng này là kết quả dòng đã đo hoặc giới hạn an toàn của mọi LED.

Muốn dòng LED chính xác hơn: dùng current probe phù hợp hoặc tắt nguồn rồi chèn ampe kế **nối tiếp nhánh LED**. Ampe kế gây burden voltage và có thể làm đổi điểm làm việc. Tuyệt đối không đặt thangA/mA song song nguồn hoặc hai đầu điện trở.

## 3. Bài thử ngay trong app Pi

1. Đảm bảo DAC0x60/0x61 và Grove ADC0x08 đã nhận; khắc phục lỗi I²C trước khi kỳ vọng phát/thu. Lần kiểm tra trước Pi chưa thấy DAC0x60 và ADC0x08 báoEIO. Chưa xác nhận đã đấu lại.
2. Vào **Hiệu chuẩn & thu tín hiệu**, chọn **1Hz**, biên độ **1000mV**, rồi Bắt đầu. Trang này phát sine **trên cả hai DAC**, không phải bật từng LED độc lập.
3. Theo code: `V_DAC(t)=0,5×[1+sin(2πt)] V`. Do đó V_DAC chạy0–1V, V_sense dự kiến0–0,5V, I_emitter0–5mA; giá trị trung bình dự kiến2,5mA. Đồng hồ DC chủ yếu đọc trung bình, scope mới thấy min/max/dao động.
4. Đo CH1=V_DAC, CH2=V_sense. DC coupling, bắt đầu khoảng200ms/div, trigger cạnh lên CH1. Kiểm tra V_sense≈V_DAC/2, đáy gần0, không bẹt đỉnh hoặc nhảy thất thường. Ghi min/max/mean và sai lệch; không chỉ chụp màn hình app.
5. Zoom1–10µs/div để tìm rung cao tần trên V_sense nếu scope đủ băng thông. C2/C4 đangDNP; không tự chọn tụ bù từ ảnh sóng chậm. Tần số cập nhật DAC500Hz là một phép đo riêng, không phải tần số sine1Hz.
6. Dừng sine trước khi tháo probe, chuyển dây hoặc thay LED. App đưa DAC về0V khi dừng bình thường, nhưng MCP4725 có thể khôi phục giá trị EEPROM lúc bật nguồn: giữ nguồn LED tắt trong lúc đấu dây/khởi động.

## 4. Đáp ứng thu tĩnh và động

Giữ cố định khoảng cách, hướng LED, khẩu độ, nguồn và nắp hộp tối trong mọi lượt so sánh.

**Nền tối và tuyến tính.** Ghi OUT khi tắt LED và khi che quang. Sau đó tăng mức phát từ thấp lên theo bảng, đo đồng thời I_sense và V_OUT. Tính `ΔV_OUT = V_OUT_sáng − V_OUT_tối`, vẽΔV_OUT theo I_sense cho từng kênh. Đây là đáp ứng toàn đường LED–quang–OPT101, không phải công suất quang tuyệt đối. Khác bước sóng/khoảng cách sẽ đổi độ dốc.

**Biên độ và pha.** CH1=V_sense, CH2=OUT sau lọc cùng làn. Phát sine1,2,5,10Hz, giữ nguyên mức0–1000mV nếu chưa clipping. Ghi Vpp_in,Vpp_out, tần số thực vàΔt. `G(f)=Vpp_OUT/Vpp_sense` có đơn vịV/V của đường đo này, không phải gain quangA/W. Pha trễ theo quy ước `φ≈−360fΔt` độ. Với sine, độ trễ có thể mơ hồ theo chu kỳ; không suy ra trễ lệnh Android từ phép đo này.

**Bão hòa.** Theo [datasheet TI OPT101, mục6.5](https://www.ti.com/lit/ds/symlink/opt101.pdf), OUT cao không tới rail nguồn. Ở3,3V cần tránh vùng khoảng2V trở lên khi kiểm tra ban đầu, rồi xác định headroom thật trên mạch. Giảm ánh sáng/dòng nếu đỉnh bẹt. Không đợi ADC lên3,3V mới kết luận clipping.

**Bộ lọc OUT.** R=1kΩ,C=1µF cófc danh nghĩa159Hz, τ=1ms, thời gian lên10–90% của riêngRC≈2,2ms. Đây là tính toán, không phải rise time toàn hệ thống. App Calibration chỉ1–10Hz và model100Hz, vì vậy không dùng nó chứng minh băng thông159Hz hoặc14kHz của OPT101. Muốn đo bước/đáp ứng nhanh cần nguồn kích đã kiểm chứng và scope đủ tốc độ. Có thể so trước/sauRC bằng OUT chân5 và OUT header.

**Xuyên kênh.** Bài sine trong app bật cả hai LED. Muốn thử từng LED: dừng, tắt nguồn rồi ngắt đầu nối LED còn lại, hoặc chặn quang kín làn đó. Đo cả hai OUT với cùng điều kiện. Ghi biên độ kênh bị ảnh hưởng; phép thử chặn quang cần phân biệt rò quang với xuyên nhiễu nguồn/điện.

## 5. Bảng ghi tối thiểu

Ngày/board/LED/nguồn/khoảng cách/khẩu độ/probe; R_sense; V_DAC min/max; V_sense min/max/mean; I_emitter tính được; V_RX tối/min/max/Vpp; f; Δt/pha; clipping/ringing; sample rate thật và mất mẫu nếu dùng ADC. Lưu CSV scope hai kênh đồng thời. Waveform TX của app là lệnh điện áp, chưa phải điện áp hoặc dòng đo thật. Không suy SpO₂ lâm sàng từ bài thử này.
