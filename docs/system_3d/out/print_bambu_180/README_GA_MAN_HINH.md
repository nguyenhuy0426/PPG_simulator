# Gá màn hình và hộp Pi bắt trực tiếp buồng tối — 2026-11-05

Phương án hiện tại: buồng tối đặt trên hộp Pi, bắt trực tiếp bằng bốn vít M3.
Không dùng khung U rời. Mốc trước khi thêm tai: commit `0dead178`.

## File để in

- `than_hop_pi4.stl`: hộp Pi mới, đã có hai tai trước liền thân và hai tai sau có sẵn.
- `ga_do_man_hinh.stl`: gá đã gia cường chân, giữ nguyên từ commit trên.
- `01_than_hop_toi.stl`: buồng tối, không thay đổi.
- `khung_ghep_buong_den_pi4.stl`: phương án khung U cũ; **không in/không lắp cho phương án này**.

In đúng tỉ lệ 100%, đặt các chi tiết trên những bàn in riêng. Hộp Pi mới có kích
thước bao 123 × 104,293 × 70 mm; gá 168 × 126 × 74 mm, đều nằm trong khổ 180 mm.
Bề ngang thân Pi vẫn 120 mm, thân buồng tối vẫn 150 mm; không cần nới cả hộp.

## Hai tai mới

Mỗi tai 12 × 14 × 4 mm, mặt trên cùng cao độ Z=70 mm với miệng hộp. Mỗi tai có
hai gân tam giác dày 2 mm hai bên; khoảng trống giữa gân 8 mm để đặt ê-cu/long đen.
Hai lỗ trước Ø3,7 mm có tâm (6,85) và (114,85). Hai lỗ sau có sẵn giữ nguyên
ở (6,−6) và (114,−6), đường kính khoảng 4,2 mm. Bước tâm bốn lỗ là 108 × 91 mm,
khớp bốn lỗ Ø3,5 mm của buồng tối. Phần thêm khoảng 1,50 cm³ vật liệu hình học
đặc; ít hơn phương án khung U riêng khoảng 11,29 cm³, chưa tính infill/support.

Các cửa cổng, khoang trong, rãnh đáy và phần gá phía sau không bị cắt sửa. Hai tai
mới chỉ thêm ở hai góc trên phía trước, có gân nối xuống thành hộp.

## Lắp ráp

- Đặt buồng tối trực tiếp trên miệng Pi. Mô hình lắp giữ Pi/gá tại tọa độ gốc,
  buồng tối dịch (−33,−12,70) mm từ STL in riêng. Thấp hơn phương án khung U 4 mm.
- Hai vít sau đi qua tai buồng tối → tai Pi → mặt tựa phẳng trên gá màn hình.
- Hai vít trước đi qua tai buồng tối → tai Pi mới. Đặt ê-cu dưới tai, giữa hai gân.
- Dùng vít xuyên M3, long đen đường kính ngoài tối đa 7 mm và ê-cu,
  không siết tạo ren trực tiếp vào nhựa.
  Chiều dày kẹp sau khoảng 14 mm, trước 8 mm. Có thể bắt đầu kiểm tra với M3×20
  phía sau và M3×16 phía trước; chọn lại theo chiều dày đầu vít, long đen và ê-cu
  thực tế. Luồn thử cả bốn vít bằng tay trước khi siết, tránh ép cong tai nhựa.

## Kiểm tra

Nguồn tái tạo: `../../add_pi_mounting_tabs.py`. Bản Pi trước khi sửa được lưu ở
`../../assets/than_hop_pi4_before_front_tabs_20261105.stl` và trong commit `0dead178`.
Script `repair_display_stand.py` và thư mục `../stand_review/` mô tả phương án
khung U trước đó, không phải hướng dẫn lắp trực tiếp hiện tại.

Kết quả mới: `../direct_mount_review/geometry_checks.json`, hình xem
`../direct_mount_review/preview.png`, mô hình ghép `../direct_mount_review/assembly.glb`.

Đã kiểm tra STL mới là một khối kín, không mất thể tích hộp cũ, không thêm vật
liệu vào khoang trong hoặc vùng cửa cổng phía trước; hai lỗ mới là lỗ kín xuyên tai.
Cả ba cặp gá–Pi–buồng không có chồng lấn đáng kể (ngưỡng 0,001 mm³). Thân vít M3
thông qua bốn vị trí. Vùng bao Ø7,4 × 4 mm trên đầu vít và dưới vị trí ê-cu không
vướng chi tiết; đây không phải mô hình một bộ vít hoặc dụng cụ cụ thể.
Diện tích tựa Pi–buồng khoảng 1.565 mm²; mỗi tai có khoảng 99–102 mm² mặt tựa
quanh lỗ, nên mô hình không chỉ trùng tâm vít mà còn có mặt tiếp xúc để kẹp.

Chưa chạy slicer, in thử, xác nhận dung sai lắp thực tế hoặc thử tải PETG. Tai có
nhịp cầu giữa hai gân 8 mm; cần xem preview support/bridge trong slicer, cùng các
vùng overhang vốn có ở gá và hộp Pi. Chưa xác nhận tải làm việc an toàn 1 kg hoặc
khối lượng buồng tối cho phép. Thử tải giả có dây giữ trước khi lắp màn hình thật.

## Cập nhật khớp sau

Đã bỏ khớp ôm hai bên trên gá và gân xiên ngoài dưới tai sau hộp Pi.
Mặt trên tai gá phẳng ở Z=66, dày 6 mm, tựa mặt dưới tai Pi tại Z=66.
Giữ nguyên tâm vít, hai tai trước và gân của hai tai trước.
Tái tạo: chạy `flatten_rear_joint.py` rồi `add_pi_mounting_tabs.py`.
Hình `flat_joint.png` và `assembly.glb` trong `../direct_mount_review/` là bản cập nhật.
Hình `preview.png` cũ minh họa bản trước khi làm phẳng khớp.
Bỏ gân sau làm giảm tăng cứng tại tai; chưa thử lực siết hay tải PETG thực tế.
