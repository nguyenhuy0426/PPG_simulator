# PPG Mac Desktop V2 (màn hình nghiêng 10°, đế thấp phía trước)

Bản V2 lấy dáng Modern Mac: mặt màn hình **nghiêng ra sau 10°**, đế thấp nhô ra phía trước có khe gió hai bên hông, ô logo tròn (chỉ là ô lõm trơn, không phải logo thật), rãnh đĩa và ô nút đẩy trang trí. Màn hình khung nhôm **178 × 105 × 10 mm**. V1 (`../mac_desktop_v1`) được giữ nguyên.

Kích thước lắp xong, theo CAD: **rộng 220 × sâu 200,5 × cao 170 mm** (chưa tính đầu ốc, đệm chân). Đế cao 30 mm, nhô ra trước thân 50 mm; đỉnh mặt nghiêng lùi cách mặt trước thân 9 mm.

Bố cục theo yêu cầu: cụm Pi + buồng tối xếp chồng **nằm trong thân cao phía sau màn hình**, giữ nguyên toạ độ V1 (hộp Pi Z=19–89, buồng tối Z=89…). Đế thấp chỉ là phần vỏ rỗng phía trước. Cửa sau tháo bằng M4, rút khay + cụm Pi/buồng tối về phía sau như V1. Thân, cửa sau, khay, hộp Pi và buồng tối không đổi so với V1; chỉ bỏ bốn vít góc mặt trước và hai rãnh dẫn hướng góc ở thân.

File gửi in nằm trong **GUI_IN_6_STL/** hoặc **GUI_IN_6_STL.zip**: sáu file **BAN_01.stl … BAN_06.stl**, **21 chi tiết** (3, 2, 6, 8, 1, 1 chi tiết mỗi file), mỗi bàn trong 180 × 180 × 180 mm, đơn vị mm, không scale.

| Nhóm | Số lượng |
|---|---:|
| Thân vỏ chia trái/phải và trước/sau | 4 |
| Nắp trước (đế + mặt nghiêng), chia trái/phải | 2 |
| Kẹp khung nhôm màn hình | 4 |
| Cửa sau | 2 |
| Khay rút | 2 |
| Thân buồng tối, nắp, bốn chụp dây, hộp Pi M4 | 7 |
| **Tổng** | **21** |

## Lắp ghép

Mối ghép kết cấu dùng M4, lỗ thông Ø4,5 mm, hốc đai ốc AF7,4 mm. Mô hình kiểm tra với đai ốc M4 AF7 dày 3,2 mm và long đen Ø9 dày 0,8 mm.

- Nắp trước gắn vào thân bằng **4 vít dọc** tại X=40/180, Y=7: hai vít từ dưới (qua sàn thân vào tai trong nắp, đai ốc nằm trên tai), hai vít từ trên (qua mái thân vào tai treo dưới mái, đai ốc nằm dưới tai). Không có vít ở mặt trước phía dưới; đầu vít chỉ lộ ở mặt trên/đáy máy.
- Hai nửa nắp trước ghép bằng 2 vít M4x20 đi vuông góc mặt nghiêng tại X=116 (hai điểm, cạnh dưới và cạnh trên), đai ốc trong tai phía sau.
- Màn hình ép bằng bốn kẹp M4x14 tì vào khung nhôm, không siết lên kính. Khoảng hở 0,5 mm giữa kính và mặt trong của nắp là hình học danh định.
- Các mối ghép còn lại giữ như V1: cửa sau 4 vít (M4x16) + 3 vít ghép hai nửa (12 mm); thân nối ngang 2 vít mái (12) + 1 vít đáy (10), nối trước–sau 2 vít mái (12) + 2 vít đáy (10); khay 2 vít ghép (12) + 2 vít giữ (16); Pi vào khay 4 vít (20); buồng tối lên Pi 4 vít (16). **Tổng 36 vít M4**; chiều dài là theo hình học, cần đối chiếu bộ ốc thực tế.
- Dán bốn đệm cao su dày **ít nhất 5 mm** dưới đáy để chừa đầu vít đáy.
- Thứ tự: nạp đai ốc, lắp màn hình + kẹp vào nửa nắp, ghép hai nửa nắp, trượt nắp vào mặt trước thân (tai sàn nằm trên sàn, tai mái treo dưới mái), siết 4 vít dọc, sau đó đặt cụm khay vào từ phía sau và đóng cửa.

Toạ độ lắp ráp (X ngang, Y ra sau, Z lên): đế Y từ −50 đến 0, thân Y 0–150, cửa sau đến Y=150,5. Màn hình nằm trong khung cục bộ xoay 10° quanh trục X, nên hộp bao của màn hình không còn là hộp thẳng.

## Nguồn dựng và kiểm tra

Chạy từ gốc dự án với môi trường CadQuery đã có (đặt `PYTHONPATH` là thư mục này khi chạy `render.py`/`verify.py`):

```sh
cd docs/system_3d/mac_desktop_v2
python build.py && python pack.py && python verify.py && python render.py && python deliver.py
```

`build.py` dựng nắp trước, thân, khay và dùng lại cửa sau/buồng tối/hộp Pi từ `../cyberdock_v3`. `verify.py` kiểm tra khối kín, BRep STEP, phép xoay in không phản chiếu, mở lại 3MF, giao thoa lắp ráp (ngưỡng 0,02 mm³ là dung sai tính lưới), đường đi ren M4 (kể cả các trục nghiêng của kẹp và vít ghép nắp), một số hốc đai ốc/long đen, đường rút khay qua cửa sau và sáu nhóm STL. Kết quả nằm trong `out/verification.json`.

**Chưa kiểm tra:** slice/support/brim (đế nhô ra trước có mái rỗng 50 mm cần support hoặc đổi hướng in), thử tải, độ ổn định lật khi màn nghiêng, creep PETG, tản nhiệt, vùng hiển thị thực của màn hình, độ vừa của PCB/cáp thật, độ kín sáng và hiệu chuẩn quang. Đây là mô hình CAD kỹ thuật chưa in thử.
