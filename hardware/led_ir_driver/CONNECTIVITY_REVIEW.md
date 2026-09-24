# Rà soát kết nối — driver v1.3

## Kết luận về đầu cáp Pi

MCP4725 (không phải MCP4275) là thiết bị I²C. Bản PCB có bốn net riêng
GND, 3V3, SCL, SDA; chỉ các chân cùng tên của hai module được nối chung.
Không có dây đồng nối bốn net này thành một. OUT IR và OUT RED tách biệt.

Thiết kế giữ đúng kiến trúc trong `docs/hardware/PPG_PROTOTYPE_SCHEMATIC.md`:
hai DAC chung bus Pi, IR 0x60, RED 0x61, cùng rail 3,3 V. Tài liệu nguồn
ghi người dùng đã đo 3,28 V; lần rà soát này không đo lại phần cứng.

| Cách đấu | Kết luận |
|---|---|
| Một bẹ I²C vào J2, hai module đã cắm | Đủ cấp nguồn và bus cho cả hai DAC |
| Hai nguồn 3,3 V độc lập, hoặc một đầu 5 V | Không phù hợp: PCB nối trực tiếp VCC, không có OR-ing/cách ly |
| Hai bộ điều khiển/bus riêng | Không thuộc cấu hình thiết kế; không nối trực tiếp như vậy |
| Nối OUT của hai module với nhau hoặc vào một ngõ ra chủ động khác | Không được; hai DAC có thể tranh chấp điện áp |

J4 đã được bỏ khỏi schematic, PCB, BOM và Gerber. Việc an toàn của dây thực
vẫn phụ thuộc đúng đầu cáp, đúng chiều và đúng điện áp.

## Ánh xạ cáp bốn lõi

J2 là header đực 1×6 bước 2,54 mm duy nhất và nối 1:1 với J1.
Dây I²C dùng nhóm **3–6**:

| Tín hiệu trên HAT/Pi | Chân trên J2 |
|---|---|
| SCL | 3 |
| SDA | 4 |
| 3,3 V | 5 |
| GND | 6 |

Chân 1 = OUT DAC, chân 2 = GND phụ. Không trượt bẹ bốn lõi lên chân 1–4.
Không suy ra thứ tự bằng màu dây; kiểm tra nhãn/tính thông mạch của cáp.
Đầu Grove bước 2,0 mm không cắm trực tiếp vào header bước 2,54 mm này;
cần đầu chuyển/dây tách chân phù hợp. Không nhầm số chân J2 với số
chân vật lý trên header 40 chân của Raspberry Pi.

## Các phần đã đối chiếu

- Module: OUT/GND/SCL/SDA/VCC/GND theo ảnh; không dùng pad vuông SCL
  của module làm dấu chân 1 PCB. Điện áp 5 V của LED không tới VCC DAC.
- LM358: 1/2/3 kênh IR, 7/6/5 kênh RED, nguồn 8=5 V và 4=GND.
  Hồi tiếp âm lấy tại emitter/đầu trên điện trở sense.
- 2N4401: pad 1=E, 2=B, 3=C; không thay C1815 cùng chiều chân.
- J5/J6: anode=5 V, cathode=collector; không đưa cathode thẳng xuống GND.
- Chia áp 10k/10k: command khoảng VDAC/2. Với VDAC=3,3 V,
  dòng emitter danh nghĩa IR=20,12 mA (82 Ω), RED=16,50 mA (100 Ω).
  Dòng collector LED thấp hơn một lượng bằng dòng base.
- Tại danh nghĩa trên, điện trở sense tiêu tán khoảng 33,2/27,2 mW,
  thấp hơn công suất linh kiện 250 mW. Đây không phải chứng nhận dòng
  LED tuyệt đối: dung sai nguồn/điện trở/op-amp, Vf và headroom vẫn tác động.
- C5=100 nF gốm bypass, C7=10 µF tụ hóa lọc nguồn; C2/C4 là DNP.
  Không tự lắp giá trị tụ bù khi chưa đo vòng điều khiển.
- Hai module có điện trở pull-up; không thêm pull-up lên PCB. Kiểm tra
  mức thấp/sườn xung khi lắp cùng HAT vì các pull-up mắc song song.
- OPT101: chân 4–5 nối để dùng 1 MΩ nội, 3/8 về GND, 1 về 3,3 V,
  2/6/7 để hở. J3 xuất RED/IR, ADS1115 phải có GND chung bên ngoài.

## Đường GND

Hai chân GND của J1 và J3 (pin 2, pin 6) đều đi vào vùng đồng GND mặt dưới.
Vùng đồng này nối tới J2.2/J2.6, U1.4, R2.2, R4.2, R7.2, R9.2,
C5.2, C7.2 và J7.2. Như vậy GND DAC, GND LM358, GND nguồn LED 5 V và
GND Pi là cùng một mốc điện áp. Dòng LED chạy về J7.2 qua vùng đồng;
không chạy qua board OPT101.

## Sửa ở v1.3

- Bỏ J4 và toàn bộ sáu lỗ/đường đồng/nhãn liên quan. Chỉ J2 nhận cáp Pi.
- J3 vẫn nhận 3,3 V, GND, SDA và SCL từ bus chung; J3.1 chỉ đi vào kênh Red.
- Schematic, PCB, BOM, pin map, Gerber và ảnh kiểm tra được sinh lại đồng bộ.

## Sửa đã giữ từ v1.2

- Vẽ bốn đường bus giữa hai cặp header ngay trên schematic; thêm chú thích
  dùng chung nguồn/bus và không nối chung OUT. Các nút nối có dấu chấm.
- Ghi tên từng chân bên J2, dấu ngoặc nhóm I²C 3–6, bảng chân mặt sau.
- Nhánh hồi tiếp RED đi riêng đến pad R9.1, không nhập vào đường dòng
  emitter trước pad. Nhánh C4 cũng về pad này trên lớp dưới.
- Bản đồ đồng phân biệt màu SDA/SCL và OUT IR/RED; GND pour được ẩn để
  nhìn đường tín hiệu. Đường nét đứt của linh kiện không phải dây đồng.
- Schematic OPT101 được vẽ lại thành hai mạch hoàn chỉnh có dây nguồn,
  bypass, hồi tiếp, Grove và ADS; giữ nguyên hợp đồng chân và bố trí quang.

Kiểm tra KiCad gồm ERC, DRC, kết nối chưa hoàn tất, đối chiếu schematic/PCB
và kiểm tra độc lập các tập chân/net. Chi tiết ở `reports/` của mỗi board.
Kết quả này không thay thế đo dòng, dao động, quá độ bật nguồn và thử lắp.
MCP4725 có thể nạp giá trị EEPROM khác 0 lúc khởi động; board chưa có
khóa tắt LED phần cứng. Không thể cam kết “không có sai sót” từ file CAD.

Nguồn đối chiếu:

- [Microchip MCP4725](https://ww1.microchip.com/downloads/en/DeviceDoc/MCP4725-Data-Sheet-20002039E.pdf)
- [TI LM358](https://www.ti.com/lit/ds/symlink/lm358.pdf)
- [TI OPT101](https://www.ti.com/lit/ds/symlink/opt101.pdf)
- [Seeed Grove Base Hat for Raspberry Pi](https://wiki.seeedstudio.com/Grove_Base_Hat_for_Raspberry_Pi/)
