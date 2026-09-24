# LED / IR driver — thiết kế đang triển khai

Pinout đã được người dùng xác nhận bằng ảnh: từ trên xuống
OUT / GND / SCL / SDA / VCC / GND. Một header đực J2 nhận bus/nguồn Pi;
hai socket module dùng chung GND, 3,3 V, SCL và SDA.

## Phần đã xác định

- Hai MCP4725 dạng module, cắm hai socket cái 1×6 bước 2,54 mm.
- Một header đực J2 1×6 cho dây Pi. J4 đã bỏ ở v1.3.
- LM358P dùng socket DIP-8, khoảng cách hai hàng 7,62 mm.
- Q1/Q2 chọn 2N4401 TO-92 theo datasheet onsemi, chân 1 E, 2 B, 3 C.
  Không cắm C1815 vào cùng footprint: thứ tự E/C/B khác nhau.
- MCP4725 dùng nguồn 3,3 V và bus I²C 3,3 V; LM358 và anode LED dùng 5 V.
- IR địa chỉ 0x60, Red 0x61, cấu hình địa chỉ trên module.
- Mỗi DAC qua cầu chia 10 kΩ / 10 kΩ 1% đến ngõ vào không đảo LM358.
- IR: LM358 chân 1 OUT, 2 feedback, 3 command; Red: 7 OUT, 6 feedback,
  5 command. LM358 chân 4 GND, chân 8 +5 V.
- Điện trở base 1 kΩ; sense IR 82 Ω 1%, Red 100 Ω 1%, công suất 0,25 W.
- Dòng emitter xấp xỉ VDAC/(2 Rsense): tại 3,28 V là 20,00 mA IR và
  16,40 mA Red; tại 3,30 V là 20,12 mA và 16,50 mA. Dòng LED collector
  nhỏ hơn dòng emitter bởi dòng base; không coi các số này là dòng đã đo.
- Tụ bypass LM358 C5 100 nF; đầu nguồn 5 V có C7 10 µF.
- Chỉ giữ hai vị trí bù vòng C2/C4 (DNP). Bỏ C1/C3, C6, R5/R10 để
  giảm linh kiện/vị trí dự phòng chưa có yêu cầu đo. Xem COMPONENT_RATIONALE.md.
- Khổ cơ khí tham chiếu từ mô hình driver hiện có: 70 × 55 mm,
  tâm bốn lỗ cách mép 4 mm. Đây là board driver, khác board RX 70 × 32 mm.
- B.Silkscreen: `DATN: PPG-Simulator` và
  `Nguyen Nhat Huy - Pham Thanh Vy`.

## Module tham chiếu

Ảnh `docs/system_3d/assets/mcp4725_raw.jpg` thể hiện hàng chân
GND / VCC / SDA / SCL / GND / OUT. Không suy ra rằng mọi module MCP4725
đều cùng thứ tự. Ảnh người dùng cung cấp đã xác nhận thứ tự cho bản PCB này.
Mô hình cũ mô tả kích thước module là giả định, chưa đủ xác nhận cơ khí.

## Chọn transistor

2N4401 onsemi có giới hạn dòng collector 600 mA và VCEO 40 V;
C1815 Toshiba trong source có giới hạn 150 mA và 50 V. Cả hai dư khả năng
về dòng/áp cho ứng dụng này. Chọn 2N4401 cho bản mới để thống nhất BOM
và footprint; không coi dòng tối đa lớn hơn là bằng chứng chính xác hơn.
Độ chính xác vẫn phụ thuộc điện trở sense, DAC, LM358, nhiệt và dòng base.

Nguồn: https://www.onsemi.com/pdf/datasheet/2n4401-d.pdf;
`docs/ds_linhkien/2SC1815L-GR.PDF`;
`docs/hardware/PPG_PROTOTYPE_SCHEMATIC.md`.

Chưa xác nhận thực nghiệm: dòng LED, độ ổn định vòng điều khiển, trạng thái
LED khi DAC khởi động/nạp EEPROM, module thực và lắp vừa đế in.
