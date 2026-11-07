# PPG Cyberdock V2 — giữ hộp Pi hiện tại, dùng M4

File giao: **out/PPG_Cyberdock_M4.3mf**. Một file chứa cả cụm, gồm **37 đối tượng có tên riêng**, tháo/tách được. Màn hình mua sẵn chỉ xuất trong ảnh và GLB tham chiếu, không nằm trong danh sách chi tiết in. Đây là file mô hình 3MF theo milimét, chưa phải project đã chia bàn/slice của Bambu Studio. Khi in cần tách đối tượng, chọn hướng và arrange trên nhiều bàn; không in cả cụm đang lắp thành một khối.

## Dáng máy và bố trí

- Dựng CAD mới theo các nét của ảnh Cyberdock: thân ngang bo góc, nóc hạ về sau, nẹp xám, vòng răng và núm đỏ ba cánh, quai chữ U. Không sao chép hay thu phóng lưới điện thoại từ MakerWorld.
- Vỏ chính rộng **230**, cao **130**, sâu **245 mm**; tính nẹp trước và cửa sau sâu **251,5 mm**. Cả quai/núm/chân khoảng **298 × 175 × 260 mm** (rộng × cao × sâu), chưa tính ốc và đệm cao su.
- Màn hình có khung nhôm **178 × 105 mm** theo thông tin người dùng. Chiều dày đang giả định **20 mm**; cửa nhìn **170 × 97 mm** chưa được đo trên màn hình thật. Bốn kẹp tì lên khung nhôm, cần đệm mềm mỏng và siết vừa tay.
- Buồng tối phía trước, hộp Pi phía sau trên cùng khay. Cách bố trí trước–sau giữ mặt máy thấp hơn phương án chồng hai hộp; phần thân vì thế sâu hơn mẫu dành cho điện thoại.
- Hình dáng và kích thước hộp Pi được giữ lại. Bản sao trong cụm đã đổi lỗ gá sang M4, giữ tai trước đã thiết kế ở lượt trước. Không sửa file nguồn `out/print_bambu_180/than_hop_pi4.stl` ở bước dựng V2.
- Buồng tối bỏ thanh trượt hành trình, chân LED cố định giữ vị trí quang danh định cũ (đỏ 25 / IR 85 mm). Lỗ thanh trượt được bịt. Gân nắp cũ có khe hở 0,01 mm với mặt nắp: bản V2 nối liền gân vào nắp. Chưa xác nhận lại hiệu chuẩn hoặc độ kín sáng thực tế.
- Cửa sau gồm hai nửa, mỗi nửa bắt hai M4; tháo cả hai nửa rồi tháo hai ốc giữ khay để rút trọn khay ra. Gân và tai ốc không chặn đường rút các chụp luồn dây buồng tối.

## Số chi tiết

| Nhóm | Số lượng |
|---|---:|
| Bốn mảnh thân vỏ | 4 |
| Hai nửa viền màn hình | 2 |
| Kẹp khung nhôm màn hình | 4 |
| Nẹp trang trí | 6 |
| Hai nửa cửa sau | 2 |
| Hai nửa khay | 2 |
| Hai nửa quai kèm chân trước, hai chân nối dài phía sau | 4 |
| Hai spacer, hai vòng răng, hai núm | 6 |
| Thân buồng tối, nắp, bốn chụp dây, hộp Pi | 7 |
| **Tổng đối tượng in trong 3MF** | **37** |

Nếu đã có một số chi tiết phù hợp thì không cần in lại các chi tiết đó. Nắp và thân buồng tối trong V2 đã có chỉnh sửa như trên. Các linh kiện điện tử, khẩu độ và gá PCB riêng của hệ thống hiện tại chưa được mô hình hóa đầy đủ trong cụm này.

## Gá module và ốc

Các tọa độ sau ở hệ lắp ráp gốc, trước phép tịnh tiến chung `[35,10,25]` của 3MF; X ngang, Y từ trước ra sau, Z lên trên. Tâm bốn lỗ buồng tối là **X 61/169; Y 40/131**, đúng bước **108 × 91 mm**. Bốn lỗ đáy hộp Pi là **X 69/161; Y 171/205**, đúng bước **92 × 34 mm**. Hai module bắt độc lập vào khay; không ép hai mẫu lỗ khác nhau chồng lên nhau. Mặt đặt hai module Z=18 mm.

Tất cả mối ghép kết cấu mới dùng **M4**, lỗ thông Ø4,5 mm, hốc đai ốc AF7,4 mm. Lỗ LED, lỗ quang và các lỗ giao tiếp linh kiện không phải lỗ vít M4. Khe lắp ghép danh định 0,25–1 mm tùy vị trí; cần kiểm tra với máy in PETG thực tế.

Chiều dài dưới đây theo hình học với long đen M4 Ø ngoài 9, dày 0,8 mm, đai ốc thường AF7 dày 3,2 mm. Cần đối chiếu bộ ốc thật; không dùng chiều dài vượt vào màn hình, PCB hoặc dây.

| Mối ghép | Số ốc | Loại / chiều dài dự kiến |
|---|---:|---|
| Nẹp–viền–thân trước | 4 | M4×20, đầu trụ lục giác chìm, long đen; đai ốc nạp từ mép nẹp |
| Kẹp màn hình | 4 | M4×20, long đen; đai ốc nạp ngang ở viền trước |
| Cửa sau | 4 | M4×16, long đen; đai ốc trong tai thân |
| Ghép thân dưới: hai mối ngang, hai mối trước–sau | 4 | **M4×10** + một long đen dưới đầu; không tăng chiều dài vì đầu ren nằm dưới đường trượt khay |
| Ghép nóc: một mối ngang, hai mối trước–sau | 3 | M4×12 + long đen, đai ốc nạp từ trong |
| Ghép hai nửa khay | 2 | M4×12 + long đen, đầu ở dưới khay |
| Buồng tối vào khay / hộp Pi vào khay | 4 + 4 | M4×20, long đen hai phía và đai ốc; đầu trụ nằm dưới khay |
| Hai ốc giữ khay, thao tác qua cửa sau | 2 | M4×16 + long đen |
| Nối ngang quai | 2 | M4×16, long đen và đai ốc rời |
| Nối dài chân phía sau | 4 | M4×16 **đầu chỏm cao tối đa 2,2 mm**, luồn từ dưới; long đen và đai ốc ở trên |
| Trục hai bên thân–quai | 2 | **M4×40 đầu lục giác ngoài AF7** giữ trong hốc thân; đai ốc M4 đặt trong núm |
| **Tổng** | **39** | Các chiều dài khác nhau nhưng cùng đường kính ren M4 |

Hai trục cần vòng ma sát mềm dày khoảng 1 mm, Ø ngoài 32 / lỗ 4,5 mm giữa quai và spacer. Vòng răng là chi tiết ép/trang trí, không phải cơ cấu khóa răng. Chân cần đệm cao su cao **ít nhất 5 mm** để chừa ốc/đai ốc phía dưới; đệm là vật tư mua thêm. Chỉ kiểm tra hình học khi nghiêng −6°, −3°, 0°, +3°, +6°; không xem đây là khớp xoay tự do hay tải trọng đã chứng nhận. Tổng khối lượng và trọng tâm thực tế chưa đo.

Lắp cụm màn hình/nẹp, nạp sẵn các đai ốc và ốc trục trước khi đóng các mảnh thân. Sau đó lắp module vào khay, nối khay và thử rút không dây trước; chỉ cố định dây sau khi kiểm tra đủ độ chùng cho bảo trì. Cửa sau và khay dùng ốc, không dùng bản lề/snap-fit dễ gãy.

## Tái tạo và kiểm tra

Dùng môi trường CadQuery hiện có `/home/huynn/.cache/ppg-cad312-venv/bin/python`:

```sh
rtk proxy /home/huynn/.cache/ppg-cad312-venv/bin/python docs/system_3d/cyberdock_v2/build.py
rtk proxy /home/huynn/.cache/ppg-cad312-venv/bin/python docs/system_3d/cyberdock_v2/verify.py
rtk proxy /home/huynn/.cache/ppg-cad312-venv/bin/python docs/system_3d/cyberdock_v2/render.py
```

V2 dùng các hàm hình học/xuất file và mô-đun quang cũ trong `../cyberdock_v1/build.py`, không dùng hình dáng vỏ V1. Các file STEP/STL rời trong `out/` phục vụ tái dựng và kiểm tra; file giao cho người dùng vẫn chỉ là 3MF nêu trên. Màu 3MF là gợi ý phân vật liệu, không phải cấu hình AMS.

`out/verification.json` ghi kết quả kiểm tra STEP, độ kín từng khối STL, phép xoay in không phản chiếu, giới hạn 180 mm, mở lại 3MF, giao thoa lắp ráp, các trục M4, khoảng trống đầu ốc/long đen, đường rút khay và góc nghiêng lấy mẫu. Ngưỡng giao thoa 0,02 mm³ chỉ dung sai tính lưới float32, không phải dung sai cơ khí.

Chưa slice/in thử, thử tải màn hình 800 g–1 kg, đo biến dạng/creep PETG, lực khóa khớp, độ ổn định khi chạm, tản nhiệt, kín sáng, hiệu chuẩn quang hoặc đo đủ PCB/cổng/dây. Hướng in và support phải kiểm tra trong slicer. Không coi mô hình này là bản đã xác nhận đủ điều kiện in lắp ngay khi chiều dày/cổng màn hình chưa được đo.
