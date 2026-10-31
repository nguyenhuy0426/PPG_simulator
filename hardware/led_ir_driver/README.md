# DATN: PPG-Simulator — LED / IR driver v2.0

Mở `led_ir_driver.kicad_pro` bằng KiCad 10. Board hai lớp, **70 × 40 mm**,
FR4 1,6 mm; socket module, socket IC và header xuyên lỗ; toàn bộ điện trở và tụ điện là linh kiện dán.
Thư viện symbol, footprint, mô hình 3D đi kèm trong thư mục dự án.
Schematic v2.0 dùng dây nối trực tiếp cho từng kênh; mỗi module MCP4725 có
cổng I²C riêng (J8 cho IR, J9 cho RED) qua điện trở 100 Ω hoặc jumper bỏ qua. Đọc `ELECTRICAL_AUDIT.md` để xem kết quả
rà soát điện, cấu hình ADDR và các điều kiện trước khi cấp nguồn. Đọc
`COMPONENT_RATIONALE.md` để hiểu lựa chọn linh kiện và `PIN_MAP.md` để tra
chân nối; `reports/wiring_guide.png` thể hiện đường đồng hai lớp có màu.

Mặt sau PCB ghi tên tín hiệu cạnh từng pad của J1/J2/J3/J4, J5/J6/J7, J8/J9,
socket LM358 và hai transistor, cùng nhãn nhóm JP/R của từng kênh I²C. Nhãn chân không có tiền tố số; tên connector và
reference linh kiện vẫn được giữ để đối chiếu schematic.

Xem `CONNECTIVITY_REVIEW.md` để xem đường GND và việc tách I²C ở v2.0.

## Cắm module và dây

Thứ tự dưới đây đúng theo ảnh module người dùng xác nhận; đọc từ đầu OUT
ở trên xuống GND ở dưới khi nhìn mặt linh kiện. **Pad 1 PCB là OUT**;
pad vuông SCL trên chính module không phải dấu pin 1 của socket PCB.
Module nằm ngang, mặt linh kiện hướng lên; thân module mở rộng sang phải
của hàng socket như ảnh. Hàn hàng chân đực xuống mặt dưới module để cắm.

| Pad | J1 socket IR | J3 socket Red |
|---|---|---|
| 1 | OUT IR (`DAC_IR`) | OUT Red (`DAC_RED`) |
| 2 | GND board | GND board |
| 3 | SCL_IR → JP1.2 | SCL_RED → JP3.2 |
| 4 | SDA_IR → JP2.2 | SDA_RED → JP4.2 |
| 5 | 3V3_IR → J8.3 | 3V3_RED → J9.3 |
| 6 | GNDI2C_IR → J8.4 | GNDI2C_RED → J9.4 |

**Cổng I²C riêng từng module (v2.0).** J8 (IR) và J9 (RED) là header đực
1×4 bước 2,00 mm, thứ tự Grove: **pin 1 SCL, pin 2 SDA, pin 3 3V3, pin 4 GND**
(pad vuông là pin 1). J8 chỉ nối module IR (J1), J9 chỉ nối module RED (J3).
Trên PCB không còn bus SCL/SDA/3V3 chung giữa hai module: `3V3_IR` và
`3V3_RED` là hai net riêng; `GNDI2C_IR`/`GNDI2C_RED` không có đường đồng,
vùng đồng hay via nào nối về GND của board. Đã kiểm tra cả 16 chân J1.3–6,
J3.3–6, J8.1–4, J9.1–4: không chân nào thuộc net GND, không có đồng/vùng đồng
GND chạm vào chúng (vùng GND cách 0,30 mm). GND I²C chỉ lấy từ cổng Grove trên HAT.

**Lưu ý quan trọng:** pin 2 và pin 6 của mỗi module MCP4725 đã nối chung bên
trong module (một chip, một VSS). Khi cắm module, `GNDI2C_x` vẫn thông với GND
board qua module. Tách trên PCB chỉ để không có đường đồng GND chung trên board,
**không phải cách ly galvanic**. Nếu hai cổng Grove lấy từ cùng một HAT thì
SCL/SDA vẫn là cùng một bus I²C của Pi; vẫn cần địa chỉ 0x60/0x61 khác nhau.

J2 và J4 là header đực 1×2 bước 2,54 mm: chân 1 = OUT, chân 2 = GND
(J2 cho IR, J4 cho RED). Pin OUT là ngõ ra DAC để đo/lấy tín hiệu, không
nối vào ngõ ra khác.

GND board (pin 2 của hai socket, J2.2/J4.2, LM358 pin 4, đầu dưới các điện
trở sense, cực âm C5/C7 và J7.2) là vùng đồng hai mặt. Nguồn 5 V tại J7 phải
chung GND với Pi; đường chung đó đi qua dây GND của J7 và qua module.

### Jumper I²C — mặc định HỞ

Mỗi đường SCL/SDA có một điện trở 100 Ω 1% 0805 và một jumper hàn 3 pad:

| Kênh | Tín hiệu | R | JP | Pad 1 (BYP) | Pad 2 (giữa) | Pad 3 (100R) |
|---|---|---|---|---|---|---|
| IR | SCL | R11 | JP1 | SCL_H_IR (J8.1, R11.1) | SCL_IR → J1.3 | SCL_R_IR (R11.2) |
| IR | SDA | R12 | JP2 | SDA_H_IR (J8.2, R12.1) | SDA_IR → J1.4 | SDA_R_IR (R12.2) |
| RED | SCL | R13 | JP3 | SCL_H_RED (J9.1, R13.1) | SCL_RED → J3.3 | SCL_R_RED (R13.2) |
| RED | SDA | R14 | JP4 | SDA_H_RED (J9.2, R14.1) | SDA_RED → J3.4 | SDA_R_RED (R14.2) |

Hàn **pad 2–3** để đi qua 100 Ω; hàn **pad 2–1** (BYP) để bỏ qua điện trở.
Chỉ hàn một phía. **Board xuất xưởng để hở cả hai**: module không nhận SCL/SDA
cho đến khi hàn jumper. Silk mặt trên ghi tên tín hiệu phía trên điện trở,
`BYP` dưới pad 1 và `100R` dưới pad 3.

Mỗi cặp R/JP nằm giữa header 2,00 mm và socket của chính module đó (IR: giữa
J1 và J8, x = 13/21 mm; RED: giữa J3 và J9, x = 46/54 mm), R ở hàng trên
(y = 4,6 mm), JP ở hàng dưới (y = 7,6 mm); courtyard các cell cách nhau ≥ 0,75 mm.
**Vùng này nằm dưới thân module khi cắm**: rút module ra khỏi socket để hàn
hoặc đổi jumper. Jumper giữ hình pad bo tròn 1,0 × 1,5 mm của footprint KiCad
`SolderJumper-3_P1.3mm_Open_RoundedPad1.0x1.5mm`, chỉ dời pad 1/3 ra để **tâm
pad cách 2,0 mm** (`generate_design.py: widen_jumper`). Khe đồng giữa hai pad
khoảng 1,0 mm (0,95 mm tại góc bo); cần nhiều thiếc hơn hoặc một đoạn dây
ngắn để nối 2–3 hoặc 2–1.

Hai module vẫn có pull-up riêng; carrier không thêm pull-up. Với 100 Ω nối
tiếp, mức thấp phía bên kia điện trở tăng thêm I_pull-up × 100 Ω, ví dụ
1,8 mA → 0,18 V. Kiểm tra mức thấp thật bằng oscilloscope so với V_IL của
MCP4725/Pi khi đã biết tổng pull-up của Pi, HAT và hai module; nếu biên quá
hẹp thì dùng phía BYP.

Đặt jumper địa chỉ trên module: **IR = 0x60, Red = 0x61** theo cấu hình source.
Với module MCP4725A0: IR đặt ADDR về GND, RED đặt ADDR về VCC (3,3 V).
Gỡ cầu hàn ADDR–GND nếu có trước khi nối ADDR–VCC; không nối tắt cả ba pad.
Hai chân GND của module vẫn là cùng VSS ở cả hai cấu hình địa chỉ.
Header sáu chân không đưa chân ADDR ra ngoài. Kiểm tra jumper và quét I²C
trước khi chạy; không để hai module cùng địa chỉ trên cùng một bus.

| Đầu nối | Pin 1 | Pin 2 |
|---|---|---|
| J5 LED IR | Anode LED, +5 V | Cathode LED, collector Q1 |
| J6 LED Red | Anode LED, +5 V | Cathode LED, collector Q2 |
| J7 nguồn | +5 V | GND |

J5/J6/J7 dùng header đực 1×2 bước 2,54 mm. LED nằm trên carrier trong hộp
quang, nối bằng dây. Cathode LED không nối trực tiếp xuống GND.
Nguồn 5 V chỉ cấp LM358 và LED; **không có 5 V ở header MCP4725 hay J8/J9**.
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
v1.3. Lắp mặc định **12 điện trở (8 của mạch driver + R11–R14), C5 và C7**,
không lắp C2/C4; JP1–JP4 chỉ là pad đồng. Giữ tên
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

KiCad 10.0.6 (v2.0): **ERC 0 lỗi/0 cảnh báo; DRC 0 vi phạm (mọi mức); 0 kết nối
còn thiếu; 0 sai khác schematic/PCB; 507 kiểm tra trong `verify_design.py` đạt**,
gồm net từng chân J1/J3/J8/J9/JP/R, GNDI2C không chạm vùng GND, 3V3_IR ≠ 3V3_RED
và 5V cách mọi đồng I²C/3V3 mới ≥ 2 mm trên cùng lớp (đo được 2,22 mm).
Số lượng/cỡ lỗ theo `reports/drill.rpt`; bốn lỗ bắt vít Ø3,2 mm.

- `reports/erc.rpt`: kiểm tra schematic.
- `reports/drc.rpt`: DRC và parity schematic/PCB.
- `reports/pin_contract.json`: kiểm tra độc lập pinout, nguồn, hồi tiếp,
  header 1:1, footprint, DNP và kích thước.
- `fabrication/`: Gerber và drill. `../PPG_LED_IR_driver.zip`: gói board lẻ. Panel ghép mới nằm trong `../PPG_3boards_VCUT_panel.zip`.
- `BOM.csv`: danh sách footprint trên board; mua thêm hai module MCP4725,
  một LM358P và hai socket cái 1×6, một socket DIP-8 theo BOM. JP1–JP4 ghi
  `BRIDGE`: jumper hàn, không mua linh kiện.

File đã xuất để kiểm tra; chưa gửi đặt sản xuất. Phần cứng và đặc tính
quang/điện chưa được đo. Không coi DRC sạch là chứng minh mạch hoạt động.

## Tái sinh

`generate_design.py` ghi đè schematic và PCB, **xóa chỉnh sửa thủ công**.
Không cần chạy script để mở/chỉnh dự án bằng KiCad. `schematic_connected.py`
vẽ schematic bằng dây nối; `route_board.py` đặt từng đoạn đồng đã chọn theo
chức năng, không sử dụng autorouter. Sau khi sinh cần refill zone và chạy
ERC/DRC/parity; `verify_design.py` kiểm tra độc lập các kết nối dự định.
Đường đồng I²C v2.0 nằm trong `routing_paths.json` (toạ độ board thu gọn,
chỉ đoạn ngang/dọc/45°); via đổi lớp của chúng đặt trong `compact_layout.py`.
`render_wiring.py --export` chạy bằng Python có pcbnew; sau đó chạy cùng
script không tham số bằng Python có matplotlib để xuất bản đồ đường dây.

Nguồn: sơ đồ `docs/hardware/PPG_PROTOTYPE_SCHEMATIC.md`,
[2N4401 onsemi](https://www.onsemi.com/pdf/datasheet/2n4401-d.pdf),
datasheet MCP4725 và LM358 trong `docs/ds_linhkien/`.
Footprint/model từ KiCad 10: CC-BY-SA 4.0 với ngoại lệ sử dụng trong thiết kế
điện tử, [KiCad Library License](https://www.kicad.org/libraries/license/).

## Thay đổi v2.0 so với v1.9

- Bỏ nhóm I²C 2,00 mm của J2 và bus SCL/SDA/3V3 chung; J2 chỉ còn OUT_IR/GND.
- Thêm J8/J9 (I²C riêng từng module), R11–R14 (100 Ω 1% 0805) và JP1–JP4.
- J8 đặt đúng chỗ nhóm I²C cũ của J2 (x = 29 mm); J9 ở mép phải (x = 68,3 mm).
- Kích thước, lỗ M3, vị trí J1/J3/J4–J7 và mạch LM358/2N4401/sense giữ nguyên.

Một Grove Base Hat đã hỏng sau khi nối bản v1.9; kiểm tra hình học đồng v1.9
không tìm thấy chập giữa các net. v2.0 chỉ giảm rủi ro (không còn đường đồng
I²C/3V3/GND chung giữa hai module, có thể thêm 100 Ω nối tiếp), **không sửa
một lỗi đã xác định**. Chưa đo trên board v2.0 thật.

## Bố trí bản thu gọn hiện tại

PCB 70 × 40 mm. Lỗ PCB tại (4;24), (66;24), (4;36), (66;36) mm. C7 đặt mặt sau giữa các header, các tụ/trở còn lại dùng footprint SMD. Đường đồng ngang/dọc/45°; nguồn 5 V rộng 0,60–0,80 mm; 3V3_x 0,60 mm, GNDI2C_x 0,50 mm, SCL/SDA 0,35 mm.
Các cell R/JP không chồng lên đồng 5 V ở mặt đối diện: kể cả chiếu hai lớp,
5 V cách đồng I²C/3V3 mới ≥ 2,22 mm (pad J3.6 ↔ đồng 5 V gần U1). Tọa độ hiện tại trong PCB/fit_report.json thay cho bảng vị trí cũ.
