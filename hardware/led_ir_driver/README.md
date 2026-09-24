# DATN: PPG-Simulator — LED / IR driver v1.3

Mở `led_ir_driver.kicad_pro` bằng KiCad 10. Board hai lớp, **70 × 55 mm**,
FR4 1,6 mm; socket module và linh kiện xuyên lỗ để dễ hàn/thay thế.
Thư viện symbol, footprint, mô hình 3D đi kèm trong thư mục dự án.
Schematic v1.3 dùng dây nối trực tiếp cho từng kênh. Đọc
`COMPONENT_RATIONALE.md` để hiểu lựa chọn linh kiện và `PIN_MAP.md` để tra
chân nối; `reports/wiring_guide.png` thể hiện đường đồng hai lớp có màu.

Mặt sau PCB ghi tên tín hiệu cạnh từng pad của J1/J2/J3, J5/J6/J7, socket
LM358 và hai transistor. Nhãn chân không có tiền tố số; tên connector và
reference linh kiện vẫn được giữ để đối chiếu schematic.

Xem `CONNECTIVITY_REVIEW.md` để xem đường GND, bus chung và thay đổi một đầu cáp ở v1.3.

## Cắm module và dây

Thứ tự dưới đây đúng theo ảnh module người dùng xác nhận; đọc từ đầu OUT
ở trên xuống GND ở dưới khi nhìn mặt linh kiện. **Pad 1 PCB là OUT**;
pad vuông SCL trên chính module không phải dấu pin 1 của socket PCB.
Module nằm ngang, mặt linh kiện hướng lên; thân module mở rộng sang phải
của hàng socket như ảnh. Hàn hàng chân đực xuống mặt dưới module để cắm.

| Pad | J1 socket IR / J2 đầu cáp Pi | J3 socket Red |
|---|---|---|
| 1 | OUT IR | OUT Red |
| 2 | GND | GND |
| 3 | SCL | SCL |
| 4 | SDA | SDA |
| 5 | 3,3 V | 3,3 V |
| 6 | GND | GND |

J1–J2 nối **1:1 đủ sáu chân**. J3 dùng chung GND, 3,3 V, SCL và SDA
với J1/J2; OUT Red chỉ đi từ J3 vào mạch Red, không nối OUT IR.
J2 là header đực duy nhất để đưa I²C/3,3 V từ Pi vào board.
**Bẹ I²C bốn lõi vào chân 3–6: SCL, SDA, 3V3, GND; không vào 1–4.**
Không còn J4 và không cần bẹ dây thứ hai.
Pin OUT là ngõ ra DAC để đo/lấy tín hiệu, không nối vào ngõ ra khác.

Hai chân GND của mỗi module (pin 2 và pin 6) nối vào vùng đồng GND mặt dưới.
Vùng này cũng nối J2.2/J2.6, LM358 pin 4, đầu dưới các điện trở sense,
cực âm C5/C7 và J7.2. Vì vậy nguồn 5 V tại J7 phải chung GND với Pi.

Đặt jumper địa chỉ trên module: **IR = 0x60, Red = 0x61** theo cấu hình source.
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
để giữ điện áp emitter bằng điện áp command. R4 = 82 Ω cho IR, R9 = 100 Ω
cho Red, metal-film 1%, 1/4 W, bước chân 7,62 mm.

`I_emitter ≈ V_DAC / (2 × R_sense)`.
Tại nguồn DAC 3,28 V và gần full-scale: khoảng 20,00 mA IR / 16,40 mA Red.
Nguồn 3,30 V cho khoảng 20,12 mA / 16,50 mA. Dòng LED collector nhỏ hơn bởi
dòng base; đây là tính toán danh nghĩa, chưa gồm sai số và chưa đo thực.

C5 là tụ gốm đĩa **100 nF X7R 50 V**, không phân cực, pitch 2,50 mm,
thân ≤Ø5 mm. C7 là tụ điện phân 10 µF ≥16 V, Ø5 mm, pitch 2,00 mm,
chú ý cực + nối 5 V. C5 đặt sát nguồn U1; C7 gần đầu nguồn. Tụ hóa C7 là
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

Kích thước và bốn tâm lỗ lấy từ `docs/system_3d/build_system.py`:
board 70 × 55 mm, lỗ tại (4,4), (66,4), (4,51), (66,51) mm;
lỗ Ø3,2 mm cho vít M3. Khổ 70 × 32 mm trước đây thuộc board RX.
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
0 sai khác schematic/PCB; 152 kiểm tra hợp đồng chân, hình học và đi dây đạt**.
File khoan có 62 lỗ mạ (38 lỗ Ø0,8 mm, 24 lỗ Ø1,0 mm) và bốn lỗ
không mạ Ø3,2 mm. Gia công hai lớp đồng, FR4 1,6 mm, đồng 1 oz.

- `reports/erc.rpt`: kiểm tra schematic.
- `reports/drc.rpt`: DRC và parity schematic/PCB.
- `reports/pin_contract.json`: kiểm tra độc lập pinout, nguồn, hồi tiếp,
  header 1:1, footprint, DNP và kích thước.
- `fabrication/`: Gerber và drill. `../led_ir_driver_gerbers.zip`: gói nhà in.
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
