# PPG Mac Desktop V1

Vỏ máy để bàn lấy dáng Macintosh trong ảnh người dùng: màu kem, khung màn hình lõm và vát vào trong, cằm có rãnh trang trí và khe gió ngang. Đã bỏ đế dày 14 mm cùng các lỗ/vít gá đế. Màn hình có khung nhôm **178 × 105 × 10 mm**. Vỏ ngoài rộng **220**, cao **170**, sâu **160,5 mm**, chưa tính đầu ốc và đệm chân. Bố trí buồng tối chồng trực tiếp trên hộp Pi hiện tại; giữ khay rút ra sau và cửa sau tháo bằng vít.

File gửi in nằm trong **GUI_IN_6_STL/** hoặc **GUI_IN_6_STL.zip**. Chỉ gửi sáu file **BAN_01.stl … BAN_06.stl** cùng hướng dẫn kèm theo. Có tổng cộng **21 chi tiết**:

| Nhóm | Số lượng |
|---|---:|
| Thân vỏ chia trái/phải và trước/sau | 4 |
| Mặt trước có khung màn hình và cằm trang trí | 2 |
| Kẹp khung nhôm màn hình | 4 |
| Cửa sau | 2 |
| Khay rút | 2 |
| Thân buồng tối, nắp, bốn chụp dây, hộp Pi M4 | 7 |
| **Tổng** | **21** |

Mỗi nhóm STL nằm trong 180 × 180 × 180 mm, đơn vị milimét, không scale. Các chi tiết vẫn là các khối rời trong mỗi STL. `DANH_SACH_CHI_TIET.json` cho biết tên từng chi tiết trên từng bàn. Một số chi tiết được đặt đứng để chia sáu bàn, vì vậy bên in phải kiểm tra support/brim trong slicer trước khi chạy PETG. Khoảng chừa mép mô hình danh định 4 mm; không coi đây là khoảng đã kiểm tra đủ cho mọi loại support/brim.

## Lắp ghép

Các mối ghép kết cấu dùng M4, lỗ thông Ø4,5 mm, hốc đai ốc AF7,4 mm. Mô hình kiểm tra với đai ốc M4 AF7 dày 3,2 mm và long đen Ø ngoài 9, dày 0,8 mm. Lỗ LED, khe cáp và lỗ quang giữ chức năng của chúng, không phải lỗ vít M4.

Tọa độ trong hệ lắp ráp gốc (X ngang, Y ra sau, Z lên):

- Đáy hộp Pi ở Z=19; đỉnh hộp ở Z=89; đáy buồng tối ở Z=89. Tâm bốn vít ghép buồng tối với Pi: X=56/164, Y=40/131, bước 108 × 91 mm.
- Bốn vít đáy Pi vào khay: X=64/156, Y=68/102, bước 92 × 34 mm.
- Màn hình ở X=21…199, Y=0,5…10,5, Z=48…153. Kẹp tì vào khung nhôm; không siết lên kính.
- Hai vít nối khay chuyển đến Y=35 và 136 để đầu ren không chạm đáy Pi. Không dùng vị trí nối Y=45/120 của khay Cyberdock V3 cho bản Mac.

Chiều dài dưới đây là theo hình học, cần đối chiếu đúng bộ ốc/long đen thực tế trước khi siết:

| Mối ghép | Số ốc | Chiều dài M4 dự kiến |
|---|---:|---|
| Mặt trước vào thân | 4 | 25 mm |
| Hai nửa mặt trước | 2 | 20 mm |
| Kẹp màn hình | 4 | 14 mm; hoặc 16 mm với thêm đệm 2 mm dưới đầu |
| Cửa sau vào thân | 4 | 16 mm |
| Ghép hai nửa cửa | 3 | 12 mm |
| Nối ngang thân tại nóc | 2 | 12 mm |
| Nối ngang thân tại đáy | 1 | 10 mm, đầu chỏm cao tối đa 2,2 mm |
| Nối trước–sau tại nóc | 2 | 12 mm |
| Nối trước–sau tại đáy | 2 | 10 mm, đầu chỏm cao tối đa 2,2 mm |
| Ghép hai nửa khay | 2 | 12 mm |
| Giữ khay vào thân | 2 | 16 mm |
| Hộp Pi vào khay | 4 | 20 mm |
| Buồng tối lên Pi | 4 | 16 mm |
| **Tổng** | **36** | Cùng đường kính ren M4 |

Dùng long đen dưới đầu vít; tại vít xuyên hộp Pi/buồng tối dùng cả long đen phía đai ốc. Dán bốn đệm cao su dày **ít nhất 5 mm** dưới đáy thân để chừa đầu vít M4 và bảo vệ bàn; đệm mua thêm, không có đế in 3D. Ba vít nối dưới đáy dùng đầu chỏm cao tối đa 2,2 mm với long đen dày 0,8 mm, tổng phần nhô 3 mm. Không thay vít dài hơn vào vị trí khay/màn hình khi chưa kiểm tra chiều sâu. Hốc đai ốc mặt trước, kẹp màn hình và các tai nối phải được nạp trước khi đóng vỏ; một số hốc không còn dễ tiếp cận sau khi lắp.

Lắp màn hình vào mặt trước, nạp sẵn đai ốc và ghép các mảnh thân; dán đệm cao su dưới đáy. Ghép Pi/buồng tối lên khay, kiểm tra đường dây trước khi đẩy khay vào. Khi bảo trì: tháo hai nửa cửa sau, tháo hai vít giữ khay, rồi rút cả cụm Pi–buồng tối về sau. Rãnh ngang và ô vuông trên cằm là chi tiết trang trí để dán nhãn, không phải ổ đĩa hay cổng điện tử.

## Nguồn dựng và kiểm tra

`build.py` dùng lại hàm hình học/xuất file và giao tiếp module quang/Pi trong `../cyberdock_v3/build.py`. Vỏ, mặt trước và vị trí nối khay được dựng riêng cho Mac; các bản Cyberdock được giữ lại. Kích thước buồng tối, vị trí quang danh định đỏ 25 / IR 85 mm và hình dáng hộp Pi được kế thừa từ bộ V3. Chi tiết sửa M4/bỏ thanh trượt của V3 có trong bảy chi tiết module của bộ này.

Chạy từ gốc dự án với môi trường CadQuery đã có:

```sh
rtk proxy /home/huynn/.cache/ppg-cad312-venv/bin/python docs/system_3d/mac_desktop_v1/build.py
rtk proxy /home/huynn/.cache/ppg-cad312-venv/bin/python docs/system_3d/mac_desktop_v1/pack.py
rtk proxy /home/huynn/.cache/ppg-cad312-venv/bin/python docs/system_3d/mac_desktop_v1/verify.py
rtk proxy /home/huynn/.cache/ppg-cad312-venv/bin/python docs/system_3d/mac_desktop_v1/render.py
```

`out/` chứa STEP/STL rời phục vụ dựng và kiểm tra, 3MF lắp ráp và ảnh xem trước. Không cần gửi thêm các STL trung gian ngoài thư mục GUI_IN_6_STL. 3MF có 21 chi tiết in; GLB/ảnh có thêm khối tham chiếu màn hình mua sẵn. STEP vỏ gồm 14 khối CAD gốc, các module kế thừa chỉ có dạng lưới.

`out/verification.json` ghi kiểm tra khối kín, BRep STEP, phép xoay in không phản chiếu, mở lại 3MF, giao thoa lắp ráp, đường đi ren M4, một số đầu vít/long đen/đai ốc, đường rút khay và sáu nhóm STL. Ngưỡng giao thoa 0,02 mm³ là dung sai tính lưới, không phải dung sai lắp ráp.

Chưa slice/in thử, thử tải màn hình 800 g–1 kg, đo creep PETG/độ ổn định/tản nhiệt hoặc kiểm tra đủ PCB, đầu nối và dây thật. Cửa hiển thị 170 × 97 mm vẫn cần đối chiếu vùng hiển thị thực tế. Độ kín sáng, khoảng quang danh định và hiệu chuẩn quang cần được xác nhận lại trên thiết bị lắp thật.
