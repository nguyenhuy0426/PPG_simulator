# Gá PCB thu: một thanh chữ U, không bắt vít

**Gá chữ U dùng chung OPT101/BPW34.** File `frame_70x30*_print.stl` trong thư mục này là hình học U mới; bản dùng để in nằm ở `docs/system_3d/out/print_bambu_180/14_ga_chu_U_RX_70x30.stl`.
OPT101 và BPW34 là hai phương án board thay thế nhau trong cùng vị trí hộp. In một gá cho mỗi hộp/board cần lắp, không cần in hai mẫu khác nhau.

- Bao ngoài 73,4 × 56,8 × 4 mm để khớp khe viền hiện có. Phần lớn là khoảng rỗng; gân tựa phía sau dày 2,4 mm, gờ ngoài tổng dày 4 mm.
- PCB 70 × 30 × 1,6 mm tựa lên bậc đáy và hai mép bên; không dùng ốc, đai ốc, trụ hoặc lỗ mồi.
- Khe hai bên rộng 70,5 mm, chừa 0,25 mm mỗi bên PCB danh nghĩa. Không phải khóa snap-fit; dùng vài miếng băng keo đen đục quang giữ mép board, tránh xê dịch khi cắm/rút dây.
- Giữ mặt cảm biến hướng về LED/khẩu độ; hàng header ở dưới. Tháo nắp, trượt gá xuống khe viền, đặt PCB lên bậc và tựa mặt sau vào gờ. Tâm cảm biến vẫn Y thế giới=32 mm, Z=±19,25 mm; mặt trước PCB X=137,5 mm.
- In nguyên tư thế STL, mm, scale 100%; mặt phẳng lưng đặt trên bàn. Hình học không cần support. Chân hàn phía sau PCB cắt không quá 2 mm.

## Bịt sáng khi dùng gá chữ U

Gá U không còn phần trên và dải giữa của khung kín cũ. Bịt khe phía trên PCB (khoảng 12,8 mm), khe quanh mép và các lỗ M3 bỏ trống bằng băng keo/vật liệu đục quang mỏng. Chừa đúng cửa sổ cảm biến; không dán lên vùng nhạy.

Phía sau PCB, nối kín vách giữa hai làn qua khe X=139,1..141,5 mm bằng một miếng vật liệu cách điện đục quang/băng keo gập tại giữa board (Z=0). Dán để chia hai khoang sau, không chỉ phủ một dải phẳng lên mặt board. Không cho keo hay vật liệu dẫn điện chạm pad/linh kiện. Việc này thay chức năng chắn sáng của dải giữa khung cũ, không phải chi tiết in bổ sung.

Gá và các bao linh kiện đã kiểm tra với STL thân/nắp/khẩu độ: OPT101 386/386, BPW34 310/310; đường quang danh nghĩa 20/20 mỗi loại. Không mô phỏng phản xạ hoặc độ đục vật liệu. Sau lắp dùng khẩu độ blank để kiểm tra rò sáng, rồi Ø5 để kiểm tra đúng kênh; CAD không chứng minh kín sáng thực tế.

Thể tích nhựa đặc hình học 3,66 cm³: giảm 64,5% so với gá OPT101 cũ, 62,7% so với gá BPW34 cũ. Đây không phải cam kết giảm giá/thời gian in tương ứng; slicer quyết định lượng nhựa thực.

Gá driver vẫn là `driver_70x50_adapter_print.stl`, không thay đổi. Không dùng `13_khung_board_5x7.stl` hoặc khung receiver bắt vít cũ cùng với gá U. Các bàn ghép `00_ban_*.stl` thuộc bộ gốc, chưa được thay bằng gá U; kéo STL mới riêng vào Bambu Studio.
