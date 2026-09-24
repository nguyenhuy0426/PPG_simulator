# Vì sao giữ các linh kiện này? — driver v1.3

## Tụ phân cực và tụ hóa có phải hai nhóm cần lắp riêng?

Không. Trong board này **C7 là một tụ hóa có phân cực**, không phải hai tụ
khác nhau. C5 là tụ gốm không phân cực. C2/C4 là vị trí tụ gốm dự phòng,
được đánh dấu DNP và không nằm trong số linh kiện cần lắp ban đầu.

| Linh kiện | Lắp ban đầu? | Vai trò và lý do chọn |
|---|---|---|
| C5, 100 nF X7R ≥25 V (BOM 50 V) | Có | Bypass nguồn LM358 tại chân 8–4, tạo đường trở kháng thấp cho nhiễu nhanh. Tụ gốm có đáp ứng cao tần tốt; đặt gần IC quan trọng hơn tăng điện dung tùy ý. |
| C7, 10 µF ≥16 V | Khuyến nghị có | Tụ dự trữ tại nguồn vào 5 V, giảm biến động do dây cấp nguồn và thay đổi tải. 10 µF là giá trị thiết kế khởi đầu, không phải giá trị tính chính xác cho mọi chiều dài dây. |
| C2/C4, chưa chọn giá trị | Không — DNP | Dự phòng bù vòng LM358–transistor nếu đo thấy rung/dao động. Không tự chọn tụ lớn vì có thể làm chậm, méo hoặc mất ổn định vòng. |

TI khuyến nghị bypass nguồn bằng tụ 0,1 µF đặt gần chân nguồn LM358.
C5 đáp ứng mục đích đó. C7 không thay thế C5; hai tụ xử lý các khoảng tần
số khác nhau. Xem [datasheet TI](https://www.ti.com/lit/ds/symlink/lm358.pdf),
mục Power Supply Recommendations và Layout.

Không bắt buộc dùng hóa học điện phân cho C7. Có thể dùng tụ gốm 10 µF
phù hợp, nhưng phải kiểm tra điện dung thực ở bias 5 V, kích thước và
footprint. Tụ hóa radial được chọn vì dễ hàn tay, dễ mua và gọn với footprint
Ø5 mm, pitch 2 mm. Cực + của C7 nối +5 V; cực − nối GND.
Nếu nguồn sát board và ổn định, có thể thử bỏ C7 sau khi đo; không khẳng định
bỏ tụ vẫn tốt khi chưa biết dây cấp nguồn/đáp ứng tải thực.

## Vì sao cần tám điện trở?

Mỗi kênh dùng bốn điện trở; hai kênh tổng cộng tám chiếc.

| Kênh IR / Red | Giá trị | Chức năng |
|---|---|---|
| R1 + R2 / R6 + R7 | Hai chiếc 10 kΩ, 1% | Chia điện áp DAC xuống một nửa: 0–3,3 V thành khoảng 0–1,65 V. |
| R3 / R8 | 1 kΩ | Giới hạn dòng nạp/base và tách ngõ ra LM358 khỏi tải điện dung của transistor. Không phải điện trở đặt dòng LED chính. |
| R4 / R9 | 82 Ω / 100 Ω, 1%, 0,25 W | Biến dòng emitter thành điện áp hồi tiếp để LM358 điều chỉnh dòng. |

**Không bỏ cầu chia rồi giữ nguyên phần còn lại.** LM358 dùng 5 V không phải
op-amp rail-to-rail. Đẩy command lên 3,3 V đòi hỏi emitter lên 3,3 V và ngõ ra
LM358 còn phải cao hơn bởi VBE và sụt áp điện trở base. Đồng thời LED đỏ cần
thêm điện áp thuận; ví dụ Vf = 2,2 V thì riêng LED + sense đã cần 5,5 V,
vượt nguồn 5 V ngay cả trước khi chừa VCE cho transistor. Chia đôi command
giữ khoảng điện áp vận hành phù hợp cho mạch hiện tại.

Hai điện trở 10 kΩ chỉ tải DAC khoảng 3,3/20.000 = 0,165 mA ở full-scale.
Tỷ số 1:1 tạo mức chia đôi; dung sai 1% giúp hạn chế sai số tỷ số, không
có nghĩa toàn mạch chính xác 1% vì còn DAC, offset LM358 và dòng base.

LM358 tăng/giảm dòng base đến khi:

```
V_sense ≈ V_command ≈ V_DAC / 2
I_emitter ≈ V_sense / R_sense
I_LED = I_collector = I_emitter − I_base
```

Ở VDAC ≈ 3,3 V:

- IR: 1,65 / 82 ≈ 20,12 mA; công suất R4 ≈ 1,65²/82 = 0,033 W.
- Red: 1,65 / 100 = 16,50 mA; công suất R9 ≈ 0,027 W.

Chọn điện trở 0,25 W vì công suất thấp hơn đáng kể định mức, dễ mua và dễ
hàn. Đây là tính toán DC danh nghĩa; dòng collector thực thấp hơn dòng
emitter và cần hiệu chuẩn. Không thêm điện trở nối tiếp LED chỉ để đặt dòng
vì R4/R9 cùng vòng hồi tiếp đang thực hiện việc đó.

## Những gì đã bỏ khỏi bản v1.0

- **R5/R10 (DNP base–emitter):** chưa có dữ liệu yêu cầu điện trở xả bổ sung,
  nên bỏ footprint để giảm rối. Hai điện trở này vốn không được lắp.
- **C1/C3 (DNP lọc command):** chưa có yêu cầu lọc xác định; tụ có thể làm
  thay đổi dạng sóng PPG. Bỏ footprint, giữ đường DAC qua cầu chia trực tiếp.
- **C6 (100 nF ở đầu nguồn):** bỏ tụ bypass thứ hai để đơn giản hóa; giữ C5
  ngay tại IC và C7 ở đầu nguồn. Chưa có phép đo cho thấy cần thêm C6.
- Giữ nguyên tên R1–R4/R6–R9, C2/C4/C5/C7 để đối chiếu bản cũ; số thứ tự
  bị khuyết là có chủ ý, không có linh kiện còn thiếu trong BOM.

Không có kết luận thực nghiệm rằng vòng đã ổn định. C2/C4 được để trống đến
khi kiểm tra bằng oscilloscope. Việc bỏ R_BE không giải quyết và cũng không
được coi là đã giải quyết vấn đề DAC nạp EEPROM khi khởi động: LED vẫn có
thể sáng trước khi phần mềm đặt DAC về 0; board không có khóa tắt độc lập.

## Cách đọc schematic mới

- Hai socket module dùng chung bus; một header đực J2 nhận cáp Pi ở phần trên.
- OUT DAC đi bằng dây liền xuống cầu chia rồi vào chân `+` của LM358.
- Ngõ ra LM358 qua 1 kΩ đến B; C nối cathode LED; E nối đầu trên R_sense.
- Dây từ đầu trên R_sense quay về chân `−` chính là hồi tiếp âm.
- U1A (IR), U1B (Red), U1C (nguồn) là **cùng một LM358 vật lý**.
- C2/C4 có dấu gạch đỏ và dòng DNP, tách riêng khỏi mạch lắp mặc định.
- Những tên nguồn/bus giống nhau (5V, GND, SDA, SCL, 3V3) vẫn là cùng net.
  Dùng nhãn cho nguồn chung giúp tránh kéo dây dài cắt ngang toàn tờ giấy.

## Cách đọc đường PCB mới

`reports/wiring_guide.png` cho thấy hai lớp đồng, **đều từ góc nhìn mặt trên**.
Số nằm trong pad là số chân; màu thể hiện nhóm chức năng. Vùng đồng GND
được ẩn trong hình này để dễ nhìn các đường còn lại. Xem `PIN_MAP.md` để tra
chính xác chân nào chung net; bảng này được xuất từ PCB đã đi dây.

- SCL/SDA/3V3 chạy thẳng ngang ở vùng module phía trên.
- Hai OUT DAC tách nhau; không có đường đồng nối OUT IR với OUT Red.
- Tín hiệu đi dây 0,35 mm; nguồn 3,3 V 0,6 mm; nhánh 5 V và dòng LED
  0,6–0,8 mm. Tăng bề rộng giúp giảm trở kháng và dễ gia công, không phải
  vì dòng 20 mA đòi hỏi bắt buộc đường rộng 0,8 mm.
- Từ đầu trên R4/R9 có nhánh hồi tiếp riêng về ngõ đảo LM358, không lấy
  tín hiệu từ đầu cathode hoặc từ GND. Nhánh emitter mang dòng LED riêng.
- B.Cu có vùng đồng GND làm đường hồi dòng; driver nối GND về nguồn Pi/HAT
  bằng dây riêng, không chạy nối tiếp qua board thu OPT101.
- Đường khác net có thể giao nhau trên ảnh khi chúng nằm ở **hai lớp khác
  nhau**; chỉ nối qua pad xuyên lỗ. ERC/DRC kiểm tra cả hai lớp.

V1.1 đi dây bằng các tuyến tường minh trong `route_board.py`, không dùng
autorouter. Hình thức gọn và DRC sạch chưa chứng minh nhiễu, dao động hay
dòng thực; các phép đo đó vẫn cần thực hiện trên board lắp thật.
