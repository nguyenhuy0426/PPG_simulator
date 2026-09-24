# Tra chân PCB driver v1.3

Số chân dưới đây đọc trực tiếp từ PCB đã đi dây. Hai hình trong wiring_guide.png
đều nhìn từ mặt linh kiện; mặt đồng B.Cu được nhìn xuyên board, không lật ảnh.
Tên net giống nhau nghĩa là nối điện với nhau. Khác lớp chỉ nối tại pad xuyên lỗ.
GND là vùng đồng mặt dưới, được ẩn trong hình để dễ nhìn đường tín hiệu.

Nét đứt xám nối hai pad R/C chỉ biểu diễn thân linh kiện, không phải đường đồng.

| Linh kiện | Giá trị | Chân → net |
|---|---|---|
| C2 | DNP loop comp | 1 → AMP_IR, 2 → SENSE_IR |
| C4 | DNP loop comp | 1 → AMP_RED, 2 → SENSE_RED |
| C5 | 100nF X7R 50V | 1 → 5V, 2 → GND |
| C7 | 10uF 16V | 1 → 5V, 2 → GND |
| J1 | MCP4725 IR 0x60 | 1 → DAC_IR, 2 → GND, 3 → SCL, 4 → SDA, 5 → 3V3, 6 → GND |
| J2 | PI I2C INPUT / IR OUT | 1 → DAC_IR, 2 → GND, 3 → SCL, 4 → SDA, 5 → 3V3, 6 → GND |
| J3 | MCP4725 RED 0x61 | 1 → DAC_RED, 2 → GND, 3 → SCL, 4 → SDA, 5 → 3V3, 6 → GND |
| J5 | IR LED A / K | 1 → 5V, 2 → LED_K_IR |
| J6 | RED LED A / K | 1 → 5V, 2 → LED_K_RED |
| J7 | 5V INPUT / GND | 1 → 5V, 2 → GND |
| Q1 | 2N4401 / E-B-C | 1 → SENSE_IR, 2 → BASE_IR, 3 → LED_K_IR |
| Q2 | 2N4401 / E-B-C | 1 → SENSE_RED, 2 → BASE_RED, 3 → LED_K_RED |
| R1 | 10k 1% | 1 → DAC_IR, 2 → CMD_IR |
| R2 | 10k 1% | 1 → CMD_IR, 2 → GND |
| R3 | 1k | 1 → AMP_IR, 2 → BASE_IR |
| R4 | 82R 1% 0.25W | 1 → SENSE_IR, 2 → GND |
| R6 | 10k 1% | 1 → DAC_RED, 2 → CMD_RED |
| R7 | 10k 1% | 1 → CMD_RED, 2 → GND |
| R8 | 1k | 1 → AMP_RED, 2 → BASE_RED |
| R9 | 100R 1% 0.25W | 1 → SENSE_RED, 2 → GND |
| U1 | LM358P / DIP8 socket | 1 → AMP_IR, 2 → SENSE_IR, 3 → CMD_IR, 4 → GND, 5 → CMD_RED, 6 → SENSE_RED, 7 → AMP_RED, 8 → 5V |
