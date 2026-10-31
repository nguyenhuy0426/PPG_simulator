# Tra chân PCB driver v2.0

Số chân dưới đây đọc trực tiếp từ PCB đã đi dây. Hai hình trong wiring_guide.png
đều nhìn từ mặt linh kiện; mặt đồng B.Cu được nhìn xuyên board, không lật ảnh.
Tên net giống nhau nghĩa là nối điện với nhau. Khác lớp nối qua lỗ mạ của đầu nối/socket hoặc via.
GND là vùng đồng hai mặt, được ẩn trong hình để dễ nhìn đường tín hiệu.
GNDI2C_IR/GNDI2C_RED không có đồng nối với GND trên PCB; chỉ thông với GND qua bên trong module MCP4725 khi cắm.
JP1–JP4 để hở khi xuất xưởng: hàn 2–3 = qua 100 Ω, hàn 2–1 = bỏ qua điện trở.

Nét đứt xám nối hai pad R/C chỉ biểu diễn thân linh kiện, không phải đường đồng.

| Linh kiện | Giá trị | Chân → net |
|---|---|---|
| C2 | DNP loop comp | 1 → AMP_IR, 2 → SENSE_IR |
| C4 | DNP loop comp | 1 → AMP_RED, 2 → SENSE_RED |
| C5 | 100nF X7R 50V | 1 → 5V, 2 → GND |
| C7 | 10uF 16V | 1 → 5V, 2 → GND |
| J1 | MCP4725 IR 0x60 | 1 → DAC_IR, 2 → GND, 3 → SCL_IR, 4 → SDA_IR, 5 → 3V3_IR, 6 → GNDI2C_IR |
| J2 | IR DAC OUT / GND | 1 → DAC_IR, 2 → GND |
| J3 | MCP4725 RED 0x61 | 1 → DAC_RED, 2 → GND, 3 → SCL_RED, 4 → SDA_RED, 5 → 3V3_RED, 6 → GNDI2C_RED |
| J4 | RED DAC OUT / GND | 1 → DAC_RED, 2 → GND |
| J5 | IR LED A / K | 1 → 5V, 2 → LED_K_IR |
| J6 | RED LED A / K | 1 → 5V, 2 → LED_K_RED |
| J7 | 5V INPUT / GND | 1 → 5V, 2 → GND |
| J8 | I2C IR: SCL SDA 3V3 GND | 1 → SCL_H_IR, 2 → SDA_H_IR, 3 → 3V3_IR, 4 → GNDI2C_IR |
| J9 | I2C RED: SCL SDA 3V3 GND | 1 → SCL_H_RED, 2 → SDA_H_RED, 3 → 3V3_RED, 4 → GNDI2C_RED |
| JP1 | SCL IR 1-2 BYP / 2-3 100R | 1 → SCL_H_IR, 2 → SCL_IR, 3 → SCL_R_IR |
| JP2 | SDA IR 1-2 BYP / 2-3 100R | 1 → SDA_H_IR, 2 → SDA_IR, 3 → SDA_R_IR |
| JP3 | SCL RED 1-2 BYP / 2-3 100R | 1 → SCL_H_RED, 2 → SCL_RED, 3 → SCL_R_RED |
| JP4 | SDA RED 1-2 BYP / 2-3 100R | 1 → SDA_H_RED, 2 → SDA_RED, 3 → SDA_R_RED |
| Q1 | 2N4401 / E-B-C | 1 → SENSE_IR, 2 → BASE_IR, 3 → LED_K_IR |
| Q2 | 2N4401 / E-B-C | 1 → SENSE_RED, 2 → BASE_RED, 3 → LED_K_RED |
| R1 | 10k 1% | 1 → DAC_IR, 2 → CMD_IR |
| R11 | 100R 1% | 1 → SCL_H_IR, 2 → SCL_R_IR |
| R12 | 100R 1% | 1 → SDA_H_IR, 2 → SDA_R_IR |
| R13 | 100R 1% | 1 → SCL_H_RED, 2 → SCL_R_RED |
| R14 | 100R 1% | 1 → SDA_H_RED, 2 → SDA_R_RED |
| R2 | 10k 1% | 1 → CMD_IR, 2 → GND |
| R3 | 1k | 1 → AMP_IR, 2 → BASE_IR |
| R4 | 100R 1% 0.25W | 1 → SENSE_IR, 2 → GND |
| R6 | 10k 1% | 1 → DAC_RED, 2 → CMD_RED |
| R7 | 10k 1% | 1 → CMD_RED, 2 → GND |
| R8 | 1k | 1 → AMP_RED, 2 → BASE_RED |
| R9 | 100R 1% 0.25W | 1 → SENSE_RED, 2 → GND |
| U1 | LM358P / DIP8 socket | 1 → AMP_IR, 2 → SENSE_IR, 3 → CMD_IR, 4 → GND, 5 → CMD_RED, 6 → SENSE_RED, 7 → AMP_RED, 8 → 5V |
