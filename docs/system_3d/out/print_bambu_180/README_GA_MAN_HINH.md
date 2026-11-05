# Gá màn hình PETG và liên kết buồng đen — 2026-11-05

## File để in

- `ga_do_man_hinh.stl`: gá đã sửa, 168 × 126 × 74 mm, in 1 chiếc.
- `khung_ghep_buong_den_pi4.stl`: khung U, 120 × 103 × 4 mm, in 1 chiếc, mặt rộng nằm trên bàn.
- `than_hop_pi4.stl` và `01_than_hop_toi.stl`: giữ nguyên từng byte.
- In đúng tỉ lệ 100%; hai chi tiết mới đều nằm trong khổ 180 mm, nhưng phải đặt thành hai bàn in riêng.

## Kết cấu và giới hạn chịu tải

Gá gốc vốn là một khối kín, không phải nhiều mảnh STL rời. Tuy nhiên chân thanh xiên
có bậc thụt, phần gân ngắn nhô ra và đáy gân cách mặt bàn 0,8 mm. Hai vai ngoài
của thanh không liên tục từ chân lên trên. Hình học này gây thay đổi tiết diện đột ngột;
đó là vị trí cần cải thiện khi màn hình nặng 800 g–1 kg.

Bản sửa thay hai cụm chân ngắn bằng biên dạng liền, rộng 19 mm, có chuyển tiếp lõm
R4 tại chân; tiếp đất ở Z=0 và nối liên tục lên phần gân trên. Không đổ đặc toàn bộ
khoảng trống giữa hai thanh. Các cữ giữ màn hình được giữ nguyên. Thể tích gá tăng
từ 41,93 lên 47,25 cm³, khoảng 12,7%; khung U riêng dùng thêm 12,79 cm³. Đây là
thể tích hình học đặc, không phải lượng nhựa slicer tính sau infill/support.

Hình học mới cải thiện đường truyền lực ở chân. Chưa có FEA, dữ liệu cơ tính của
cuộn PETG cụ thể, vị trí trọng tâm màn hình hay thử tải bản in, nên **chưa xác nhận
được tải làm việc an toàn 1 kg**. Hai tay nối ngang phía trên và tai hộp Pi vẫn là
các vị trí cần theo dõi; gia cường chân không chứng minh toàn bộ hệ thống không gãy.
Khối lượng buồng đen cũng chưa được cung cấp. Kiểm tra này không xác nhận độ bền
lâu dài, va đập, lực nhấn màn hình hay chống lật của toàn bộ thiết bị.

## Lắp buồng đen trên hộp Pi

Khung U tựa trên miệng hộp Pi, hai thanh dọc nằm trên thành hai bên. Khung nâng buồng
đen thêm 4 mm. Bốn tâm lỗ là (6, −6), (114, −6), (6, 85), (114, 85) mm trong hệ
tọa độ hộp Pi; bước lỗ 108 × 91 mm khớp trực tiếp bốn tai buồng đen.

- Hai vít sau đi chung qua tai buồng đen → khung U → tai hộp Pi → gá màn hình.
- Hai vít trước đi qua tai buồng đen → đầu thanh khung U, giữ bằng ê-cu phía dưới.
- Gá có thêm hai mặt đệm tích hợp cao tối đa 1 mm theo đúng mặt dưới tai Pi,
  lấp khoảng hở cũ để tránh kéo cong tai khi siết hai vít sau. Không cần spacer rời.
- Dùng vít xuyên M3, long đen và ê-cu; không dùng vít M4 dù lỗ tai Pi rộng hơn.
  Lỗ khung U Ø3,7, lỗ gá Ø3,7, lỗ Pi khoảng Ø4,2, lỗ buồng đen Ø3,5 mm.
- Tổng chiều dày kẹp danh nghĩa: sau khoảng 18 mm, trước 8 mm. Chọn vít có thêm
  chiều dài cho long đen và ê-cu thực tế; luồn thử bằng tay và siết vừa đủ tựa mặt.

Để xem mô hình ghép: `../stand_review/assembly.glb`. Hộp Pi và gá giữ tọa độ gốc;
khung U dịch Z=70; buồng đen dịch (−33, −12, 74) từ STL in riêng của nó.
Bốn rãnh dưới đáy hộp Pi có bước 92 × 34 mm không dùng cho liên kết này.

## Kiểm tra đã thực hiện

- Đọc lại hai STL mới sau xuất: mỗi file có đúng một khối kín, winding hợp lệ.
- Kiểm tra tiết diện gốc chân trước/sau; các cữ và hình học lắp phía trên cũ không bị mất.
- Kiểm tra cả 6 cặp trong cụm gá–Pi–khung–buồng: thể tích chồng lấn dưới 0,001 mm³,
  chỉ có sai số số học tại mặt gá/Pi tiếp xúc.
- Kiểm tra đường luồn thân vít M3 Ø3 xuyên bốn vị trí trong mô hình ghép.
- So SHA-256 xác nhận không sửa hộp Pi và buồng đen.
- Báo cáo số: `../stand_review/geometry_checks.json`; nguồn tái tạo:
  `../../repair_display_stand.py`; STL gá gốc nằm trong `../../assets/`.

Chưa chạy slicer, in thử hay đo dung sai lắp vật lý. Gá vẫn cần support dưới các
tay ngang phía trên khi in theo Z hiện tại; xem preview từng lớp để không có phần
bắt đầu giữa không trung. Điểm xuất phát đề xuất với nozzle 0,4 mm: PETG, lớp
0,2 mm, 5 vòng thành, 20–25% infill, brim nếu cần. Đây là đề xuất chưa được thử in
cho mẫu này. Ưu tiên đủ thành thay vì tăng infill toàn bộ; xem
[hướng dẫn về thành của Prusa](https://help.prusa3d.com/article/layers-and-perimeters_1748).

Trước khi đặt màn hình thật, dùng tải giả có dây giữ, tăng dần đến 1 kg rồi giữ
24 giờ và quan sát chân, tay ngang, tai vít. Dừng nếu có nứt, trượt, võng tăng dần
hoặc biến dạng còn lại sau tháo tải. Thử này chỉ là sàng lọc bản in, không phải
chứng nhận tuổi thọ.
