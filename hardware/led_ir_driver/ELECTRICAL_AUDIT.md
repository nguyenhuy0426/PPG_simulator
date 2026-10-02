# Kiểm tra điện LED/IR driver v1.6 — 2026-09-29

## Kết luận và phạm vi

Không phát hiện lỗi nối điện trong schematic/netlist và PCB hiện tại. Hai
GND trên mỗi module được nối chung có chủ đích; OUT không nối tắt xuống GND.
Các phần tử trong vòng điều khiển dòng có đúng pinout và chiều hồi tiếp âm.
Kiểm tra CAD đạt; chưa kiểm tra board lắp thật, địa chỉ chip thật, dao động,
quá độ bật nguồn hoặc kích thước cơ khí của hai module mua thực tế.

V1.6 giữ nguyên 17 tập chân/net và 92 đoạn đồng so với bản v1.5 trên đĩa
trước rà soát. Sửa schematic để đường bus không xuyên thân connector; nhãn
giống nhau vẫn là cùng một net điện. Thêm ADDR=GND / ADDR=VCC lên PCB và
sửa tài liệu/bộ file xuất. Không thay đổi giá trị linh kiện hoặc pitch.

## GND cạnh OUT có phải một tín hiệu khác?

Không. Module có một chân OUT và hai chân GND để tiện đưa nguồn/bus và
lấy tín hiệu analog bằng hai nhóm dây. Cả hai GND cùng mốc 0 V; điện áp
OUT được đo so với mốc này. Trên carrier, pin 2 và 6 của J1/J3 cùng về
vùng đồng B.Cu, chung với J2.2/J2.6, J4.2, J7.2 và LM358.4.

| Net | Toàn bộ chân liên quan ở nhóm module/header |
|---|---|
| OUT IR | J1.1, J2.1, R1.1 |
| OUT RED | J3.1, J4.1, R6.1 |
| GND | J1.2/6, J2.2/6, J3.2/6, J4.2; nối về GND nguồn và analog |
| SCL | J1.3, J2.3, J3.3 |
| SDA | J1.4, J2.4, J3.4 |
| 3V3 | J1.5, J2.5, J3.5 |

Nối GND–GND không gây chập nguồn. Nối OUT–GND, VCC–GND hoặc hai OUT với
nhau mới sai. Hai kênh dùng chung nguồn/bus nhưng có DAC_OUT, command,
base, sense và cathode LED riêng biệt.

## Địa chỉ I²C và cấu hình module

- Với phiên bản MCP4725A0, A0/ADDR thấp cho địa chỉ 7-bit 0x60, cao cho
  0x61. IR chọn GND; RED chọn VCC=3,3 V trên jumper của chính module.
- Carrier không tiếp cận ADDR vì hàng sáu chân không có chân này. Chữ
  0x60/0x61 trên PCB chỉ là hướng dẫn lắp, không tự đổi địa chỉ chip.
- Nếu có cầu hàn trực tiếp ADDR–GND, gỡ cầu đó trước khi hàn ADDR–VCC.
  Không hàn nối cả ba pad. Điện trở kéo xuống ADDR 10 kΩ, nếu có, không
  đồng nghĩa với một cầu hàn ngắn mạch. Giữ hai chân GND luôn về GND.
- Hai module cùng địa chỉ thường chỉ xuất hiện tại một ô khi quét và cùng
  nhận lệnh ghi. Việc trùng địa chỉ không tự gây cháy mạch, nhưng không thể
  điều khiển hai kênh độc lập. GND chung không quyết định địa chỉ.
- A2/A1 của MCP4725 được cấu hình tại nhà máy. Nếu module mua dùng biến thể
  khác, quét riêng từng module để xác nhận thay vì suy ra từ màu PCB.
- Chỉ cấp 3,3 V cho module và bus Pi. Nguồn J7=5 V cấp LM358/LED; hai rail
  nguồn không nối chung. Một cáp bốn lõi vào J2.3–6 cấp bus cho cả hai DAC.

Module trong ảnh có các điện trở ghi 472 (4,7 kΩ); cần đối chiếu mạch thật
trước khi sửa jumper. GPIO2/3 của Pi đã có pull-up cố định. Các pull-up
trên hai module và HAT mắc song song; carrier không lắp thêm điện trở kéo
lên. Ví dụ giả định Pi có 1,8 kΩ và hai module đều 4,7 kΩ: tổng khoảng
1,02 kΩ. Nếu còn một nhánh 4,7 kΩ khác thì còn 0,84 kΩ, cần khoảng
3,46 mA để giữ mức thấp 0,4 V ở rail 3,3 V, vượt điều kiện 3 mA trong
datasheet MCP4725. Đây là ví dụ tính tải, chưa phải phép đo HAT của bạn.
Khi lắp, kiểm tra tổng pull-up và dạng xung; ngắt bớt pull-up trên module
nếu cần, giữ pull-up phù hợp về 3,3 V của Pi/HAT. Không tháo nhầm điện trở
ADDR. Không thể vô hiệu hóa pull-up nằm trên module chỉ bằng sửa carrier.

## Đối chiếu linh kiện và dòng điện

| Khối | Kết nối được kiểm tra | Vai trò |
|---|---|---|
| U1 nguồn | 8→5 V; 4→GND | Đúng LM358 DIP-8 |
| U1A IR | 3→CMD_IR; 2→R4.1/Q1.E; 1→R3 | Hồi tiếp âm kênh IR |
| U1B RED | 5→CMD_RED; 6→R9.1/Q2.E; 7→R8 | Hồi tiếp âm kênh RED |
| R1/R2, R6/R7 | 10 kΩ/10 kΩ, 1% | Chia OUT DAC xuống một nửa |
| R3/R8 | 1 kΩ từ OUT op-amp tới base | Tách tải base và hạn chế dòng kích |
| Q1/Q2 | onsemi 2N4401: 1=E, 2=B, 3=C | E tới sense; C tới cathode LED |
| R4/R9 | 100 Ω/100 Ω, 1%, 0,25 W; đầu dưới→GND | Đặt dòng emitter |
| J5/J6 | 1→5 V/anode; 2→collector/cathode | Không nối cathode trực tiếp GND |
| C5 | 100 nF X7R 50 V, không phân cực, 5 V–GND | Bypass gần chân 8 U1 |
| C7 | 10 µF 16 V; +→5 V, −→GND | Lọc/dự trữ nguồn đầu vào |
| C2/C4 | OUT op-amp→sense, DNP | Không lắp khi chưa đo vòng điều khiển |

Ở OUT DAC xấp xỉ 3,3 V, command xấp xỉ 1,65 V. Dòng emitter danh nghĩa
IR=16,50 mA, RED=16,50 mA; dòng LED collector thấp hơn bởi dòng base.
R4 tiêu tán khoảng 27,2 mW, R9 khoảng 27,2 mW, dưới định mức 250 mW.
Tải DAC của mỗi cầu chia khoảng 20 kΩ, tương ứng 0,165 mA full-scale.

Command 0–1,65 V nằm trong vùng common-mode LM358 dùng nguồn 5 V.
Với Vf RED=2,2 V, transistor còn khoảng 5−2,2−1,65=1,15 V VCE.
Với Vf IR=1,65 V, còn khoảng 1,70 V. Đây là tính toán DC danh nghĩa;
độ lợi transistor, offset, biên độ ra LM358 và nguồn thực ảnh hưởng dòng.
Datasheet LED trong source: YSL-R341R3D-D2 RED khuyến nghị 16–18 mA,
giới hạn DC 20 mA ở 25°C; SIR234 IR giới hạn DC 100 mA ở 25°C. Các mức
danh nghĩa đã chọn phù hợp với các linh kiện này, không tự áp dụng cho
bất kỳ LED khác. C1815 không thay trực tiếp vì thứ tự chân khác.

Không có chứng minh thực nghiệm về ổn định vòng, dòng bằng 0 tuyệt đối
hoặc overshoot. MCP4725 tải EEPROM khi bật nguồn; LED có thể sáng trước
khi phần mềm ghi 0. Mạch không có khóa tắt LED độc lập. C2/C4 để trống;
chọn bù vòng cần đo oscilloscope, không đoán giá trị tụ rồi gọi là đã ổn định.

## Kết quả kiểm tra và đưa vào sử dụng

- KiCad 10.0.6 ERC: 0 vi phạm.
- DRC: 0 vi phạm, 0 kết nối thiếu, 0 sai khác schematic/PCB.
- 244 kiểm tra độc lập về tập chân/net, giá trị linh kiện, pitch, cực tụ,
  nhãn, chiều chân transistor và hình học đạt; xem `reports/pin_contract.json`.
- 57 lỗ PTH và 4 lỗ NPTH; PCB 70×48 mm, hai lớp, FR4 1,6 mm.
- Gerber/drill, sơ đồ PDF, ảnh và ZIP được xuất từ bản v1.6.

File CAD đủ để gia công board thử. Trước khi cấp nguồn: kiểm tra chiều
module/IC, chân transistor thực mua, cực C7, pinout cáp và jumper ADDR.
Lắp thử cơ khí trên bản in 1:1 do chưa có số đo chính xác module/cáp.
Khi chạy lần đầu, kiểm tra từng địa chỉ riêng, rồi cả hai module; đặt DAC=0
trước khi tăng dần và đo điện áp trên R4/R9, dao động và quá độ. DRC sạch
không thay thế các phép đo này. Dùng bộ ZIP riêng LED driver v1.6 để in.

## Nguồn đối chiếu

- [Microchip MCP4725](https://ww1.microchip.com/downloads/aemDocuments/documents/MSLD/ProductDocuments/DataSheets/MCP4725-Data-Sheet-20002039E.pdf): VSS, A0, địa chỉ, tải DAC, I²C, EEPROM.
- [SparkFun MCP4725 breakout](https://learn.sparkfun.com/tutorials/mcp4725-digital-to-analog-converter-hookup-guide/board-overview-): GND cạnh OUT và jumper địa chỉ/pull-up; dùng làm tham chiếu loại breakout, không chứng nhận module clone.
- [TI LM358](https://www.ti.com/lit/ds/symlink/lm358.pdf): pinout, common-mode, biên độ ra, bypass.
- [onsemi 2N4401](https://www.onsemi.com/pdf/datasheet/2n4401-d.pdf): E/B/C, giới hạn linh kiện.
- [Raspberry Pi GPIO](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html): GPIO2/3 có pull-up cố định.
- `docs/ds_linhkien/red_led_3.3mm_datasheet.pdf` trang 1; `IR_led_3.3mm_datasheet.pdf` trang 2–3.

Ảnh `docs/ds_linhkien/MCP4725_schematic.png` là board Adafruit khác loại;
không dùng thứ tự header trên ảnh đó thay pinout sáu chân người dùng đã xác nhận.
