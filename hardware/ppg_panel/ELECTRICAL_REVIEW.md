# Rà soát ba board — 2026-10-01

Không phát hiện lỗi chập nguồn, đảo net hoặc đứt mạch trong CAD đã kiểm tra.
Cả bản đầu vào và bản sửa đều được chạy ERC/DRC; bản cuối được kiểm tra
schematic–PCB và tập chân/net độc lập. Đây là thiết kế để làm mẫu thử;
chưa có phép đo điện/dao động/nhiễu trên ba PCB này đã lắp thực tế.

## Đường nguồn và lỗ khoan

| Board | Đường nguồn thực | Tải dự kiến | Đánh giá |
|---|---|---|---|
| OPT101 | 0,50 mm tuyến chính; 0,35 mm nhánh ngắn vào IC/tụ | IC khoảng 0,12–0,22 mA điển hình mỗi kênh, cộng tải OUT | Dư cho tải thiết kế |
| BPW34 | 0,40 mm tuyến chính; 0,35 mm nhánh | OPA333 khoảng 17 µA điển hình, cầu chia 30 µA, cộng tải OUT | Dư cho tải thiết kế |
| LED/IR driver | 5 V: 0,60–0,80 mm; 3,3 V: 0,60 mm; cathode/emitter dòng LED: 0,60 mm | Hai LED khoảng 16,5 mA/kênh, cộng LM358 | Dư cho tải thiết kế |

Tính kiểm tra sụt áp với đồng danh nghĩa 35 µm, điện trở suất 1,724×10⁻⁸ Ωm:
đoạn rộng 0,60 mm dài 100 mm có R≈0,082 Ω, sụt khoảng 4,1 mV ở 50 mA.
Đoạn 0,35 mm cùng chiều dài có R≈0,141 Ω, sụt 0,141 mV ở 1 mA.
Đây là mô hình DC có ghi giả thiết, không phải chứng chỉ dòng tối đa theo IPC.
Các nhánh hồi tiếp 0,22/0,35 mm mang dòng tín hiệu rất nhỏ; không cần làm
rộng chúng như nhánh công suất. GND có vùng đồng và các thermal spokes.
Không tăng dòng LED hàng trăm mA chỉ dựa trên kết quả bề rộng này.

Khoảng hở nhỏ nhất từ **mép track/via đến mép lỗ M3**:
OPT101 2,422 mm; BPW34 0,700 mm; driver 3,882 mm. Không có track bị khoan
cắt đứt. DRC cũng kiểm tra pad và vùng đồng với lỗ NPTH. Các đường trên
`Dwgs.User` ở giữa receiver là chỉ dẫn vách quang, không phải khe khoét
`Edge.Cuts`. Mỗi board có bốn lỗ NPTH; panel có 12 lỗ M3.

## Tín hiệu thu và mạng lọc mới

Mỗi kênh nay là `OUT tầng khuếch đại → R 1kΩ → OUT tới Grove/ADS`, với
tụ **1µF X7R, không phân cực, ≥16 V, 0805** từ OUT sau điện trở về GND
của chính kênh. OPT101 thêm R1/R2, C3/C4. BPW34 đổi R3/R4 từ 100 Ω lên
1 kΩ và thêm C7/C8. C1/C2 100 nF của OPT101 vẫn là bypass nguồn;
C1/C2 22 pF C0G của BPW34 vẫn nằm song song điện trở hồi tiếp 1 MΩ.
Không nhầm tụ ổn định TIA với tụ lọc OUT; không mắc trực tiếp 1 µF vào
đầu ra IC trước điện trở cách ly.

Với tải ADC đủ lớn: fc=1/(2πRC)=159,15 Hz, hằng số thời gian 1 ms.
Biên độ tương đối ở 10/20/50/100/1000 Hz lần lượt khoảng
99,80% / 99,22% / 95,40% / 84,67% / 15,72%; pha ở 20 Hz khoảng −7,16°.
Lựa chọn này giữ phần lớn thành phần PPG đến 20 Hz, đồng thời giảm nhiễu
cao tần và tách tải cáp/ADC khỏi vòng hồi tiếp. Đây là giá trị thử có cơ sở,
chưa phải tối ưu SNR đã đo. Không đủ để khử mạnh 50 Hz hoặc làm bộ chống
alias hoàn chỉnh cho mọi tốc độ lấy mẫu. Nếu cần băng thông khác phải tính
lại theo dạng sóng và tốc độ ADC thực, không tự tăng tụ cho “sạch hơn”.

Tụ X7R có sai số và suy giảm điện dung theo điện áp DC: dùng cùng mã linh
kiện cho hai kênh, kiểm tra đường cong nhà sản xuất, đo/hiệu chuẩn biên độ
và pha nếu cần so sánh RED/IR chính xác. Tụ 16/25/50 V phù hợp điện áp,
miễn đúng footprint và điện dung hiệu dụng. Có thể để trống tụ OUT để A/B
test; vẫn giữ điện trở 1 kΩ. Nếu ADC ở xa, đặt lọc phù hợp ngay đầu ADC
và đi dây OUT sát dây GND. Hai ADC đọc song song tạo tải chung, chưa đo thực.

## Giới hạn cần biết trước khi dùng

1. **OPT101 không rail-to-rail.** Với VS=3,3 V, bảng thông số cho đầu ra cao
   khoảng VS−1,15 V điển hình và VS−1,3 V ở giới hạn được nêu, tức khoảng
   2,15/2,0 V theo điều kiện datasheet. Có thể clipping trước khi ADC chạm
   3,3 V. Giảm ánh sáng/dòng LED hoặc đổi gain đúng topology; RC không sửa
   được clipping. Chân 4–5 vẫn nối trực tiếp, dùng 1 MΩ nội; chân 2/6/7 để hở.
2. **BPW34:** cathode vào ngõ đảo OPA333; anode về GND. VREF≈0,30 V;
   VOUT≈0,30 V+Iphotodiode×1 MΩ. Dòng quang cỡ vài µA đã có thể làm bão hòa.
   Hồi tiếp âm và pin SOT-23-5 đã đối chiếu. 22 pF giúp bù điện dung diode;
   độ ổn định thực, leakage bề mặt và nhiễu cần đo. Giữ sạch flux quanh SUM.
3. **Driver:** LM358.8=5 V, .4=GND; 2N4401 theo onsemi là E-B-C, không
   thay C1815 trực tiếp. R4/R9=100 Ω, cầu chia DAC 1/2 cho dòng emitter
   tối đa danh nghĩa 16,5 mA, công suất sense≈27,2 mW <250 mW.
   Dòng LED thấp hơn một chút do dòng base. C2/C4 vẫn DNP: phải đo vòng
   điều khiển trước khi chọn tụ bù. Chưa chứng minh không overshoot/dao động.
4. Hai GND trên MCP4725 cùng mốc 0 V: nối chúng là đúng, không phải ngắn
   OUT hoặc VCC. Hai OUT DAC tách riêng. IR/RED cần địa chỉ 0x60/0x61 trên
   jumper thật của module. Carrier không tự đặt địa chỉ. Kiểm tra tổng
   pull-up I²C của Pi/HAT/hai module; không thêm pull-up trên carrier.
5. MCP4725 nạp EEPROM khi bật nguồn, driver chưa có khóa tắt LED độc lập.
   LED có thể sáng trước lệnh DAC=0. Nguồn 5 V driver và Pi cần chung GND,
   nhưng không cho dòng hồi LED đi xuyên dây GND board thu.
6. J3 OPT101 vẫn chỉ có RED/IR: ADS1115 **phải có dây GND chung với HAT/Pi**;
   cắm riêng hai dây OUT vào một ADC không có GND chung là sai. J3 BPW34
   có RED/GND_RED/IR/GND_IR. Không nối song song hai tín hiệu RED và IR.

Ba PCB đã thu gọn còn 70×30, 70×30, 70×48 mm. Tiết kiệm 7,7 cm² (9,24%) so với ba board trước khi thu gọn.
Giữ chiều dài 70 mm, khoảng cách trục 38,5 mm, socket DIP/module, các header
và đầu nối/socket THT của driver. Đây là mức thu gọn thận trọng, không tuyên bố
là diện tích nhỏ nhất tuyệt đối. Giảm mạnh hơn cần đổi bố trí/module hoặc
linh kiện SMD và kiểm chứng lại cơ khí; kích thước thật module MCP4725 chưa
được cung cấp. Receiver hiện dùng chung thanh chữ U không bắt vít; dùng băng keo đục quang giữ board và bịt khe trên/vách giữa phía sau. Adapter driver giữ nguyên; chưa thử in/lắp.

## Nguồn kỹ thuật

- [TI OPT101](https://www.ti.com/lit/ds/symlink/opt101.pdf): hồi tiếp, biên độ OUT, bypass và tải điện dung.
- [TI OPA333](https://www.ti.com/lit/ds/symlink/opa333.pdf), [Vishay BPW34](https://www.vishay.com/docs/81521/bpw34.pdf): pinout, dòng tĩnh và đặc tính diode.
- [TI ADS1115](https://www.ti.com/lit/ds/symlink/ads1115.pdf): tải đầu vào và lọc RC; dải PGA không cho phép quá áp nguồn.
- [TI LM358](https://www.ti.com/lit/ds/symlink/lm358.pdf), [onsemi 2N4401](https://www.onsemi.com/pdf/datasheet/2n4401-d.pdf).
- [Microchip MCP4725](https://ww1.microchip.com/downloads/aemDocuments/documents/MSLD/ProductDocuments/DataSheets/MCP4725-Data-Sheet-20002039E.pdf).
- [JLCPCB panelization](https://jlcpcb.com/help/article/pcb-panelization): V-cut thẳng hết panel, zero-gap, phí nhiều thiết kế.
