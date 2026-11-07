# DATN: PPG-Simulator — LED / IR driver v2.0

Mở `led_ir_driver.kicad_pro` bằng KiCad 10. Board hai lớp, **70 × 40 mm**,
FR4 1,6 mm; socket module, socket IC và header xuyên lỗ; toàn bộ điện trở và tụ điện là linh kiện dán.
Thư viện symbol, footprint, mô hình 3D đi kèm trong thư mục dự án.
Schematic v2.0 dùng hai harness DAC riêng: mỗi MCP4725 có một header I²C 4-pin
2,00 mm riêng và không có đường đồng chung giữa hai harness hoặc với mass
LED/LM358 trên carrier. Đọc `ELECTRICAL_AUDIT.md` để xem kết quả rà soát điện,
cấu hình ADDR và các điều kiện trước khi cấp nguồn. Đọc
`COMPONENT_RATIONALE.md` để hiểu lựa chọn linh kiện và `PIN_MAP.md` để tra
chân nối; `reports/wiring_guide.png` thể hiện đường đồng hai lớp có màu.

Mặt sau PCB ghi tên tín hiệu cạnh từng pad của J1/J2/J3/J4, J5/J6/J7, socket
LM358 và hai transistor. Nhãn chân không có tiền tố số; tên connector và
reference linh kiện vẫn được giữ để đối chiếu schematic.

Xem `CONNECTIVITY_REVIEW.md` để xem đường GND, bus chung và thay đổi một đầu cáp ở v1.3.

## Cắm module và dây

Thứ tự dưới đây đúng theo ảnh module người dùng xác nhận; đọc từ đầu OUT
ở trên xuống GND ở dưới khi nhìn mặt linh kiện. **Pad 1 PCB là OUT**;
pad vuông SCL trên chính module không phải dấu pin 1 của socket PCB.
Module nằm ngang, mặt linh kiện hướng lên; thân module mở rộng sang phải
của hàng socket như ảnh. Hàn hàng chân đực xuống mặt dưới module để cắm.

| Pad | J1 socket IR | J3 socket Red |
|---|---|---|
| 1 | OUT IR | OUT Red |
| 2 | GND_DAC_IR | GND_DAC_RED |
| 3 | SCL | SCL |
| 4 | SDA | SDA |
| 5 | 3,3 V | 3,3 V |
| 6 | GND_DAC_IR | GND_DAC_RED |

J2 là header đực IR 1×4 bước 2,00 mm, J8 là header đực RED 1×4 bước
2,00 mm. **Cả hai cùng thứ tự chân: SCL, SDA, 3V3, GND_DAC.** J2 chỉ nối
J1.3–6; J8 chỉ nối J3.3–6. Không có đường đồng chung SCL, SDA, 3V3 hoặc
GND_DAC giữa hai header trên carrier. J4 là header đực 1×2 bước 2,54 mm:
chân 1 = OUT_RED, chân 2 = GND_DAC_RED. OUT IR chỉ có tại J1.1.
Pin OUT là ngõ ra DAC để đo/lấy tín hiệu, không nối vào ngõ ra khác.

Hai chân GND của mỗi module (pin 2 và pin 6) chỉ nối về miền đồng
`GND_DAC_IR` hoặc `GND_DAC_RED` tương ứng và chân 4 của header Pi tương ứng.
Chúng **không** nối vào `GND` của LM358, LED, nguồn 5 V, C5/C7 hoặc J7 trên
PCB này.

> Cảnh báo kỹ thuật: tách đồng như trên không tạo cách ly galvanic và không
> tự khắc phục lỗi I²C. Hai cáp cắm cùng Raspberry Pi vẫn chung GND tại Pi;
> hơn nữa OUT của MCP4725 được LM358 tham chiếu theo GND LED/LM358. Không cấp
> nguồn hay đánh giá mạch là hoạt động cho đến khi đo xác nhận mốc OUT/GND và
> xử lý cách ly đúng kiến trúc (isolator I²C + nguồn cách ly + giao tiếp analog)
> nếu thật sự cần hai miền mass độc lập.

## Sau sự cố I²C: khoanh vùng trước khi cắm lại

Không cắm lại driver vào HAT trước khi HAT tự vượt qua các bước sau. Tắt Pi,
tháo toàn bộ thiết bị ngoài GPIO, kiểm tra bằng đồng hồ rằng không có chập
điện trở thấp bất thường giữa 3V3–GND, SDA–GND hoặc SCL–GND trên driver.
Sau đó boot Pi chỉ với HAT, xác nhận I²C đã bật rồi chạy `i2cdetect -y 1`.
HAT STM32 phải được tìm là `0x04`; bản MM32 là `0x08` — phải quét cả hai,
không chỉ `0x08`. Nếu cả hai vắng mặt khi driver đã tháo, đo tại chân Pi 3
(SDA) và 5 (SCL): hai line phải ở mức nhàn rỗi gần 3,3 V. Nếu một line thấp,
tắt nguồn và tháo HAT để phân biệt HAT kéo bus hay Pi/GPIO đã hỏng.

Chỉ khi HAT hoạt động lại, cắm **một** MCP4725 đã biết tốt với 3,3 V, GND,
SDA, SCL; xác nhận địa chỉ trước khi cắm MCP còn lại hoặc nguồn LED 5 V.
Không cấp 5 V vào 3V3/SDA/SCL; GPIO2/3 của Pi có pull-up 3,3 V sẵn. Ghi lại
điện áp và kết quả quét ở từng bước — việc thấy một địa chỉ không chứng minh
mạch dòng LED hay mass đã an toàn.

Đặt jumper địa chỉ trên module: **IR = 0x60, Red = 0x61** theo cấu hình source.
Với module MCP4725A0: IR đặt ADDR về GND, RED đặt ADDR về VCC (3,3 V).
Gỡ cầu hàn ADDR–GND nếu có trước khi nối ADDR–VCC; không nối tắt cả ba pad.
Hai chân GND của module vẫn giữ chung GND ở cả hai cấu hình địa chỉ.
Header sáu chân không đưa chân ADDR ra ngoài. Kiểm tra jumper và quét I²C
trước khi chạy; không để hai module cùng địa chỉ. Module đã có pull-up I²C,
board không thêm pull-up; cần kiểm tra tải pull-up khi dùng chung Grove HAT.

| Đầu nối | Pin 1 | Pin 2 |
|---|---|---|
| J5 LED IR | Anode LED, +5 V | Cathode LED, collector Q1 |
| J6 LED Red | Anode LED, +5 V | Cathode LED, collector Q2 |
| J7 nguồn | +5 V | GND |

J5/J6/J7 dùng header đực 1×2 bước 2,54 mm. LED nằm trên carrier trong hộp
quang, nối bằng dây. Cathode LED không nối trực tiếp xuống GND.
Nguồn 5 V chỉ cấp LM358 và LED; **không có 5 V ở header MCP4725**.
Driver và RX dùng dây nguồn/GND riêng về Pi/HAT; không nối tiếp đường hồi
dòng LED qua board OPT101/Grove ADC. Trước khi cấp nguồn, xác nhận cực LED
và chiều cắm IC/socket theo rãnh pin 1 ở phía trên board.

## Mạch điều khiển dòng

U1 là **LM358P PDIP-8** với socket rộng 7,62 mm. Q1/Q2 chọn **2N4401 TO-92**
theo datasheet onsemi: pad 1 emitter, pad 2 base, pad 3 collector.
Footprint rộng 2,54 mm mỗi chân, cần uốn chân theo lỗ; đối chiếu mặt phẳng
vỏ và datasheet linh kiện mua thực. **C1815 không thay trực tiếp** vì E–C–B.

Hai điện trở 10 kΩ 1% chia đôi điện áp DAC. LM358 điều khiển base qua 1 kΩ
để giữ điện áp emitter bằng điện áp command. R4 = 100 Ω cho IR, R9 = 100 Ω
cho Red, điện trở dán **1206, 1%, công suất danh định tối thiểu 0,25 W**.

`I_emitter ≈ V_DAC / (2 × R_sense)`.
Tại nguồn DAC 3,28 V và gần full-scale: khoảng 16,40 mA IR / 16,40 mA Red.
Nguồn 3,30 V cho khoảng 16,50 mA / 16,50 mA. Dòng LED collector nhỏ hơn bởi
dòng base; đây là tính toán danh nghĩa, chưa gồm sai số và chưa đo thực.

C5 là tụ gốm dán **0805, 100 nF X7R 50 V**, không phân cực.
C7 là tụ hóa dán **SMD 5×5,4 mm, 10 µF ≥16 V**; kiểm tra đúng kích thước
thân/chân của linh kiện mua, cực + nối 5 V và cực − nối GND. C5 đặt sát nguồn U1; C7 gần đầu nguồn. Tụ hóa C7 là
tụ phân cực; không phải hai loại linh kiện riêng cần lắp thêm.

Các vị trí **DNP — chưa lắp**:

- C2/C4: bù vòng từ OUT op-amp về ngõ đảo, chỉ chọn sau kiểm tra oscilloscope.

Đã bỏ C1/C3, R5/R10 (trước đây đều DNP) và tụ bypass đầu nguồn C6 khỏi
v1.3. Lắp mặc định **8 điện trở, C5 và C7**, không lắp C2/C4. Giữ tên
reference cũ để dễ đối chiếu, nên có số thứ tự khuyết trong BOM.

Không khẳng định vòng ổn định chỉ từ ERC/DRC. Kiểm tra dòng, dao động,
overshoot và sai lệch ở DAC thấp/cao trước khi dùng. MCP4725 nạp giá trị
EEPROM khi khởi động nên LED có thể sáng trước khi phần mềm đặt DAC về 0;
board này không có khóa tắt LED độc lập. Không ghi EEPROM trong luồng phát.

## Cơ khí và hình xem trước

Board mới 70 × 40 mm, lỗ tại (4,24), (66,24), (4,36), (66,36) mm, Ø3,2 mm. Dùng gá chuyển `mechanical/driver_70x40_adapter_print.stl` để lắp lên đế 70 × 55 mm cũ; xem `mechanical/README.md` về chiều lắp và vít.
Các đầu ra LED nằm sát cạnh hướng về hộp quang theo mô hình driver cũ.

Ảnh module xác nhận pinout nhưng không cho kích thước cơ khí chính xác.
Đường bao module trên Dwgs.User chỉ là vùng dự kiến; cần đo chiều rộng,
vị trí hàng chân và thử trên bản in 1:1 trước khi gia công. Chưa xác nhận
va chạm với linh kiện/đầu cáp thực hoặc độ co của đế in.

Ảnh 3D `reports/pcb_top.png` hiển thị socket rỗng, chưa gắn hai module và
LM358. Mặt sau có đúng tên đồ án và tác giả trong `reports/pcb_bottom.png`.
Schematic có bản SVG, PNG và PDF trong `reports/`. U1A/U1B/U1C trên schematic
lần lượt là hai kênh khuếch đại và chân nguồn của **cùng một IC U1**.

## Kiểm tra và file gia công

KiCad 10.0.6: **ERC 0 lỗi/0 cảnh báo; DRC 0 vi phạm; 0 kết nối còn thiếu;
0 sai khác schematic/PCB; 244 kiểm tra hợp đồng chân, giá trị, hình học và đi dây đạt**.
Số lượng/cỡ lỗ theo `reports/drill.rpt`; bốn lỗ bắt vít Ø3,2 mm.

- `reports/erc.rpt`: kiểm tra schematic.
- `reports/drc.rpt`: DRC và parity schematic/PCB.
- `reports/pin_contract.json`: kiểm tra độc lập pinout, nguồn, hồi tiếp,
  header 1:1, footprint, DNP và kích thước.
- `fabrication/`: Gerber và drill. `../PPG_LED_IR_driver.zip`: gói board lẻ. Panel ghép mới nằm trong `../PPG_2boards_VCUT_panel.zip`.
- `BOM.csv`: danh sách footprint trên board; mua thêm hai module MCP4725,
  một LM358P và hai socket cái 1×6, một socket DIP-8 theo BOM.

File đã xuất để kiểm tra; chưa gửi đặt sản xuất. Phần cứng và đặc tính
quang/điện chưa được đo. Không coi DRC sạch là chứng minh mạch hoạt động.

## Tái sinh

`generate_design.py` ghi đè schematic và PCB, **xóa chỉnh sửa thủ công**.
Không cần chạy script để mở/chỉnh dự án bằng KiCad. `schematic_connected.py`
vẽ schematic bằng dây nối; `route_board.py` đặt từng đoạn đồng đã chọn theo
chức năng, không sử dụng autorouter. Sau khi sinh cần refill zone và chạy
ERC/DRC/parity; `verify_design.py` kiểm tra độc lập các kết nối dự định.
`render_wiring.py --export` chạy bằng Python có pcbnew; sau đó chạy cùng
script không tham số bằng Python có matplotlib để xuất bản đồ đường dây.

Nguồn: sơ đồ `docs/hardware/PPG_PROTOTYPE_SCHEMATIC.md`,
[2N4401 onsemi](https://www.onsemi.com/pdf/datasheet/2n4401-d.pdf),
datasheet MCP4725 và LM358 trong `docs/ds_linhkien/`.
Footprint/model từ KiCad 10: CC-BY-SA 4.0 với ngoại lệ sử dụng trong thiết kế
điện tử, [KiCad Library License](https://www.kicad.org/libraries/license/).

## Header I²C revision v2.0

Mua **hai** header 1×4 2,00 mm: J2 cho IR và J8 cho RED; không dùng header
chia sẻ hoặc mắc song song hai module trên carrier. Socket cái J1/J3 vẫn bước
2,54 mm. Cáp mỗi header phải đi tới đúng module/harness Pi tương ứng và giữ
thứ tự SCL, SDA, 3V3, GND_DAC.

## Bố trí bản thu gọn hiện tại

PCB 70 × 40 mm. Lỗ PCB tại (4;24), (66;24), (4;36), (66;36) mm. C7 đặt mặt sau giữa các header, các tụ/trở còn lại dùng footprint SMD. Đường đồng ngang/dọc; nguồn 5 V rộng 0,60–0,80 mm. Tọa độ hiện tại trong PCB/fit_report.json thay cho bảng vị trí cũ.
