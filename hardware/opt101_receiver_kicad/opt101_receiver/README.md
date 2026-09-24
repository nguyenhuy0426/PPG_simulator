# PCB thu PPG — OPT101P ×2, 70 × 32 mm

Mở **`opt101_receiver.kicad_pro` bằng KiCad 10**, rồi mở schematic hoặc PCB.
Thiết kế đã đi dây hai lớp, có thư viện symbol, footprint và mô hình 3D cục bộ.
Ảnh `reports/pcb_top.png` hiển thị **socket trống**, chưa cắm IC OPT101P.
Mặt sau có silkscreen `DATN: PPG-Simulator` và
`Nguyen Nhat Huy - Pham Thanh Vy`; xem `reports/pcb_bottom.png`.
Mặt sau cũng ghi tên tín hiệu tại từng pad J1/J2/J3 và từng hàng chân của
hai socket OPT101. Các nhãn này không dùng số thứ tự chân; `R/I` là hai đầu
ra, `V` là 3,3 V, `GR/GI` là ground theo kênh, `FB` là hồi tiếp và `NC` để hở.

## Linh kiện và kết nối

| Ref | Linh kiện / quy cách | Số lượng |
|---|---|---:|
| U1, U2 | OPT101P dạng PDIP-8, cắm socket DIP-8 rộng 7,62 mm, bước chân 2,54 mm | 2 IC + 2 socket |
| C1, C2 | Tụ gốm đĩa xuyên lỗ **100 nF, 50 V, X7R**, mã thường in `104`; thân tối đa Ø5 mm, bước chân 2,50 mm | 2 |
| J1, J2 | Header đực thẳng 1×4, bước 2,00 mm | 2 |
| J3 | Header đực thẳng 1×2, bước 2,54 mm | 1 |
| H1–H4 | Lỗ không mạ Ø3,2 mm; dùng vít M3×4 với khung mới | 4 |

Socket chỉ nhận **PDIP có chân xuyên lỗ**. OPT101 dạng SOP chân cong J không
cắm trực tiếp được. Đối chiếu package thực trước khi tháo IC khỏi module tím.
Rãnh socket và dấu pin 1 của IC hướng về cạnh trên có chữ RED/A2, IR/A0.

U1 là **Red → A2**, U2 là **IR → A0**. Với từng IC:

- Chân 1 → nguồn 3,3 V từ Grove; tụ 100 nF nối nguồn với GND ngay cạnh socket.
- Chân 3 và 8 → GND.
- Chân 4 nối trực tiếp chân 5 bằng đường đồng để dùng hồi tiếp 1 MΩ trong IC.
- Chân 2, 6, 7 để hở có chủ ý; không gắn điện trở 1 MΩ ngoài.

**J1/J2**, đọc theo số pad, từ pad vuông sang phải khi nhìn mặt linh kiện:

| Chân | J1 → socket A2 trên HAT | J2 → socket A0 trên HAT |
|---|---|---|
| 1 — SIG | OUT_RED | OUT_IR |
| 2 — NC | Không nối | Không nối |
| 3 — 3V3 | Nguồn 3,3 V | Nguồn 3,3 V |
| 4 — GND | GND | GND |

Pinout theo chuẩn Grove analog: pin 1 tín hiệu chính, pin 2 tín hiệu phụ,
pin 3 nguồn, pin 4 GND. Đây là **header trần bước 2 mm**, không phải socket
Grove có khóa. Kiểm tra thứ tự dây đến HAT trước khi cắm; không suy ra chiều
cắm chỉ từ màu dây. Chân phụ A1/A3 không được nối vào mạch.

C1/C2 là tụ bypass nguồn, **không phân cực**. Điện áp mạch chỉ 3,3 V nhưng
chọn loại 50 V vì đây là quy cách tụ gốm đĩa `104` rất phổ biến và vẫn nằm
trong footprint Ø5 mm. Loại 25 V X7R cùng kích thước cũng dùng được về điện;
không dùng tụ điện phân thay thế vì footprint và mục đích khử nhiễu khác nhau.

Mỗi kênh có đường nguồn và vùng GND riêng trên PCB; hai GND chung tại HAT.
Cắm cả hai cáp Grove để cấp nguồn đủ hai kênh. Không cấp 5 V vào board.

**J3 cho ADS1115**:

| Chân | Tín hiệu | Cách nối dự kiến |
|---|---|---|
| 1 — pad vuông, RED | OUT_RED, cùng net U1.5 và J1.1 | ADS1115 AIN0 |
| 2 — IR | OUT_IR, cùng net U2.5 và J2.1 | ADS1115 AIN1 |

J3 là ngõ lấy tín hiệu song song, không có buffer, không có nguồn hoặc GND.
ADS1115 cần được cấp nguồn riêng phù hợp và **nối GND về cùng GND HAT/Pi**.
Việc cấp nguồn OPT101 vẫn qua J1/J2. Hai đầu ra không phải một cặp vi sai:
đọc từng kênh so với GND. Cấu hình ADC, I²C và phần mềm ADS1115 chưa thuộc
thiết kế này. Nên dùng dây tín hiệu ngắn, đi sát dây GND; tải của ADC/cáp và
việc đọc đồng thời với Grove chưa được thử trên phần cứng.

## Kích thước và khớp mô hình 3D

Board **70 × 32 × 1,6 mm**, hai lớp đồng. Tọa độ dưới đây tính từ góc trên
trái board khi nhìn mặt linh kiện:

| Vị trí | X (mm) | Y (mm) |
|---|---:|---:|
| Tâm package/socket U1 Red | 15,75 | 16,00 |
| Tâm package/socket U2 IR | 54,25 | 16,00 |
| H1/H2 | 4,50 / 65,50 | 3,50 |
| H3/H4 | 4,50 / 65,50 | 28,50 |
| J1 pin 1 / 2 / 3 / 4 | 13,00 / 15,00 / 17,00 / 19,00 | 27,00 |
| J3 pin 1 / 2 | 26,00 / 28,54 | 27,00 |
| J2 pin 1 / 2 / 3 / 4 | 51,00 / 53,00 / 55,00 / 57,00 | 27,00 |

Ba header đã được xoay ngang và dời xuống hàng Y = 27 mm, gần cạnh dưới
Y = 32 mm. Cách bố trí này chừa hai bên socket cho vách ngăn và vùng quang,
đồng thời khung mới đã hạ các cửa phía sau để tránh chân hàn/header.

PCB revision **v1.2** dùng các đoạn đồng ngang/dọc 90° trên cả hai lớp.
Đường nguồn hai kênh được bố trí đối xứng và kết thúc trước vùng hai lỗ bắt
vít phía dưới. Mỗi lỗ M3 có khoảng cấm đồng cục bộ 1,0 mm tính từ mép lỗ;
kiểm tra độc lập cũng đo khoảng cách từ mọi track đến từng lỗ để ngăn đường
đồng đi vào vùng khoan khi tái sinh thiết kế.

Giữ đúng khoảng cách hai làn **38,50 mm**, Y thế giới = 32 mm, Z = ±19,25 mm
từ `docs/system_3d/build_system.py`. Giữ mặt trước PCB tại X thế giới = 137,5 mm.
Tâm package được dùng làm tâm quang danh nghĩa; datasheet không cho dung sai
tọa độ photodiode so với hàng chân, nên vẫn phải kiểm tra căn quang trên IC thật.

### Kiểm tra đường ánh sáng và khẩu độ

Kiểm tra boolean dùng trực tiếp STL thân hộp, nắp, các tấm khẩu độ và khung PCB
mới đạt **20/20 phép thử hình học**. Ở vị trí danh nghĩa, trục của LED Red và
IR đều đi qua tâm lỗ khẩu độ tại X = 114,2 mm rồi đến tâm vùng nhạy của OPT101
tương ứng. Tia thẳng từ LED này hướng tới cảm biến kia cắt vách ngăn đặc giữa
hai buồng, nên không có đường nhìn thẳng xuyên kênh.

- Tấm `blank` chặn tia trục của cả hai kênh.
- Lỗ Ø2, Ø5 và Ø16 đều cho tia trục đi qua.
- Vùng nhạy OPT101 là 2,29 × 2,29 mm. Khi chiếu ngược các góc vùng nhạy lên
  mặt khẩu độ, bán kính góc lớn nhất là khoảng 0,99 mm cho Red và 1,40 mm cho
  IR. Vì vậy Ø2 chỉ vừa đủ cho Red và cắt các góc vùng nhạy IR; **Ø5 hoặc Ø16
  phủ toàn bộ vùng nhạy danh nghĩa của cả hai kênh**.
- Bán kính chùm tại mức nửa cường độ trong mô hình nguồn lớn hơn các lỗ khẩu
  độ, nên khẩu độ chủ động giới hạn lượng sáng. Kiểm tra này xác nhận đường
  nhìn và độ phủ hình học, không dự đoán công suất quang hoặc biên độ tín hiệu.

Kết luận phụ thuộc vào tâm package danh nghĩa và khoảng X cửa sổ cảm biến
126,5–132,0 mm lấy từ bao socket + IC. Sai số tâm die, chiều cao socket thật,
độ trong của nhựa in, phản xạ mặt trong và khe lắp chưa được mô phỏng. Sau khi
in cần thử lần lượt với tấm `blank` và Ø5: `blank` phải cho mức tối gần như nhau
khi LED bật/tắt, còn Ø5 phải tạo đáp ứng rõ chỉ ở đúng kênh.

**Thay khung board 5×7 cũ bằng `mechanical/frame_70x32_print.stl`.**
File này đã đặt mặt lưng xuống bàn in, kích thước 73,4 × 56,8 × 4 mm, đơn vị mm,
scale 100%. Không in file `*_assembly.stl` nếu không tự chọn lại tư thế.
Không cần sửa hoặc in lại thân hộp/nắp. Khung có hốc board 70,5 × 32,5 mm,
giữ vị trí ngoài của khung cũ; hai cửa phía sau chừa chỗ chân hàn và dây.

Dùng **4 vít M3×4** qua PCB vào lỗ mồi Ø2,6 mm trên khung, tạo ren nhẹ,
không siết quá mức. Chiều ăn ren danh nghĩa chỉ 2,4 mm, lực giữ thực cần thử.
**Không dùng đai ốc hoặc vít nhô sau khung ở hai vị trí dưới**: bệ cửa cáp
của thân hộp chiếm vùng này. Cắt chân linh kiện nhô sau PCB không quá 2 mm.
Lắp cả board và khung từ phía trên khi tháo nắp; giữ dây tránh vách ngăn.
Bịt khe quanh PCB bằng băng keo đen/keo đục quang sau khi thử lắp để chống
rò sáng giữa hai buồng. FR4 và soldermask tự chúng chưa được kiểm chứng độ đục quang.

### Thay đổi mốc khoảng cách quang

Mô hình cũ đặt cửa sổ module tại X = 120 mm nhờ module tím và trụ đỡ.
Cắm IC trực tiếp lên socket của PCB **không giữ nguyên mốc 120 mm**.
Gọi `h` là khoảng cách đo vuông góc từ mặt linh kiện PCB đến cửa sổ quang
của IC đã cắm hết vào socket:

```
X_cửa_sổ_mới = 137,5 - h
d_thực = d_theo_thang_cũ + 17,5 - h
```

Ví dụ **chỉ để minh họa**, nếu đo h = 8,3 mm thì d thực tăng 9,2 mm.
Không dùng ví dụ này như kích thước bảo đảm của socket. Mã mô hình cũ và
thang khoảng cách cũ chưa được đổi; phải đo lại h và hiệu chuẩn khoảng cách.
Không đưa board ra trước để cố giữ X=120 vì board liền sẽ đụng vách ngăn giữa.

## Kiểm tra và giới hạn

Kiểm tra bằng **KiCad 10.0.6**: ERC 0 lỗi/0 cảnh báo; DRC 0 vi phạm,
0 pad chưa nối, 0 lỗi parity; 156 kiểm tra hợp đồng chân, kích thước,
hình học đường đồng và khoảng cách tới lỗ khoan đạt.
Kiểm tra cơ khí: 392/392 đạt với bao linh kiện đã nêu; khung là một khối kín.
Kiểm tra đường quang danh nghĩa: 20/20 đạt.

- `reports/erc.rpt`: ERC schematic.
- `reports/drc.rpt`: DRC, vùng đồng đã đổ, kiểm tra parity với schematic.
- `reports/pin_contract.json`: kiểm tra độc lập chân điện, bước header/socket,
  kích thước board và khoảng cách hai làn.
- `mechanical/fit_report.json`: kiểm tra boolean với **STL thân/nắp đã xuất
  trong source**, gồm đường đưa cụm từ trên xuống theo bước 2 mm.
- `mechanical/optical_report.json`: kết quả định lượng đường tia, độ che của
  từng khẩu độ và chặn tia chéo giữa hai kênh.
- `mechanical/optical_alignment.png`: hình diễn giải vị trí LED, khẩu độ và
  khoảng cửa sổ OPT101 theo trục X.

Kiểm tra cơ khí dùng bao linh kiện: socket + IC cao tối đa 11 mm, header
cao tối đa 12 mm, tụ cao tối đa 7 mm phía trước PCB. Chọn linh kiện trong
các bao này. Đầu cáp mềm chưa được mô hình hóa. Kiểm tra CAD không thay thế
thử lắp bản in, kiểm tra rò sáng, đo điện hoặc hiệu chuẩn quang thực tế.

Các kết quả phần cứng chưa thực hiện: nguồn thật, cắm socket, mức tín hiệu,
nhiễu, bão hòa, Grove ADC và ADS1115. ERC/DRC sạch không phải chứng minh
đã đo được tín hiệu PPG trên mạch thật.

## File gia công

`fabrication/` chứa Gerber hai lớp đồng, soldermask hai mặt, silkscreen và
Edge.Cuts, kèm Excellon tách PTH/NPTH. Có **30 lỗ mạ** (28 lỗ Ø0,8 mm,
2 lỗ Ø1,0 mm) và **4 lỗ không mạ Ø3,2 mm**. Chọn FR4 dày 1,6 mm,
đồng 1 oz, 70 × 32 mm; không yêu cầu trở kháng kiểm soát.
File này đã xuất nhưng **chưa được gửi đặt sản xuất**. Kiểm tra package IC,
socket, đầu cáp và bản in khung thật trước khi chốt gia công.

## Tái sinh

Không cần chạy script để mở hoặc chỉnh file trong KiCad. `generate_design.py`
**ghi đè** thiết kế đã sinh; chỉ chạy lại nếu muốn tái tạo từ mã tham số.

```bash
python-with-pcbnew generate_design.py --kicad-share /path/to/share/kicad --cli /path/to/kicad-cli
kicad-cli sch erc opt101_receiver.kicad_sch -o reports/erc.rpt
kicad-cli pcb drc opt101_receiver.kicad_pcb --refill-zones --save-board --schematic-parity -o reports/drc.rpt
python-with-pcbnew verify_design.py
# Từ gốc repository:
.cad_venv/bin/python hardware/opt101_receiver/mechanical/build_adapter.py
.cad_venv/bin/python hardware/opt101_receiver/mechanical/optical_check.py
```

Nguồn kỹ thuật:

- [TI OPT101 datasheet, pinout và hồi tiếp](https://www.ti.com/lit/ds/symlink/opt101.pdf), trang 3, 13 và 23.
- [Seeed Grove System](https://wiki.seeedstudio.com/Grove_System/), pinout Grove analog.
- [Grove Base HAT for Raspberry Pi](https://wiki.seeedstudio.com/Grove_Base_Hat_for_Raspberry_Pi/), analog 3,3 V.
- Sơ đồ gốc: `docs/hardware/PPG_PROTOTYPE_SCHEMATIC.md`, phần RX.

Footprint và mô hình 3D được sao chép từ thư viện KiCad 10, đổi tên thư viện
thành PPG và dùng đường dẫn tương đối để dự án có thể chuyển máy.
Thư viện KiCad dùng CC-BY-SA 4.0 với ngoại lệ sử dụng trong thiết kế điện tử:
[KiCad Library License](https://www.kicad.org/libraries/license/).

## Schematic v1.1 — rà soát lại

Hai kênh được vẽ bằng dây nối trực tiếp từ Grove qua nguồn/bypass tới OPT101,
strap 4–5 và nhánh OUT tới cả Grove lẫn J3. Không thay vị trí PCB hoặc hợp đồng
chân. Xem `reports/schematic.pdf` và `reports/schematic.png`. Giao cắt không
có dấu chấm không nối điện. H4 được đặt ngoài khung tên sơ đồ.
