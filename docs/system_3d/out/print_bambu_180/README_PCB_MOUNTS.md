# Gá PCB thu gọn dạng H

- OPT101 70×20: in `14_ga_chu_U_OPT101_70x20.stl`.
- BPW34 70×20: in `15_ga_chu_U_BPW34_70x20.stl`.
- Driver 70×40: in `16_ga_driver_70x40.stl`.

In mỗi gá cần dùng một bản; chúng chưa nằm trong các plate gốc.
Hai receiver dùng gá H không bắt vít: hai trụ cạnh và thanh ngang đỡ mép dưới PCB;
vùng dưới thanh ngang rỗng để luồn dây header ở phía trước PCB. Rãnh trong hộp
rộng 4,3 mm; gá dày 3,8 mm, hở danh nghĩa 0,5 mm theo chiều dày và 0,5 mm
mỗi bên theo chiều dài PCB. Hai biến thể có bậc đỡ khác nhau, không đổi lẫn.
In thử một đoạn gá và lắp trượt vào hộp thật trước khi in cả bộ: sai số máy in,
co vật liệu và ba via chưa thể được xác nhận bằng mô hình CAD. Không ép mạnh
nếu kẹt; mài nhẹ cạnh trụ hoặc bù kích thước theo mẫu thử. Giữ mép bằng băng
keo cách điện đục quang và bịt khe/vách chia kênh để tránh lọt sáng.
Không dùng `13_khung_board_5x7.stl` cho PCB mới. Các plate gốc thuộc mô hình gốc,
không cần in lại toàn bộ để thay gá. Hướng dẫn/giới hạn trong mechanical/README.md
của từng project; chưa thử in/lắp thực.
