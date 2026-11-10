# PPG Mac Desktop V2 — biến thể hông (mac_desktop_v2_side)

Vỏ kiểu Modern Mac: phần màn hình cao 170 mm phía trước, thân thấp 90 mm phía sau. Mặt màn hình nghiêng 10°. Làm cho máy in 420 × 420 × 500 mm, mỗi chi tiết in một lần, không cần bàn phụ.

Kích thước ngoài: **rộng 280 × sâu 205 × cao 170 mm**. Vách, sàn, mái và các tấm cửa dày **2 mm**. Tấm màn hình dày 4 mm.

## Chi tiết in

Slice bằng Bambu Studio 2.9.1, máy H2S, profile 0.20 mm Standard, PETG, bật support tree(auto). Số gam và thời gian là ước tính của Bambu, máy thật có thể lệch vài phần trăm.

| File | Ghi chú | Gam | Thời gian |
|---|---|---:|---:|
| `VO_LIEN_KHOI.stl` | Sàn + vách trái + phần màn hình + đế trước + 4 khối góc. In đứng | 315.5 (support ~30) | 10.4 h |
| `CUA_SAU_TREN.stl` | Nắp chữ L: mặt sau trên + mái khối màn hình. In úp mặt sau | 65.4 | 1.8 h |
| `NAP_NGANG.stl` | Mái thân thấp, 2 gân cứng dưới, 10 khe thoát nhiệt. In úp mặt trên | 61.4 | 1.9 h |
| `CUA_SAU_DUOI.stl` | Mặt sau thân thấp | 33.8 | 1.0 h |
| `CUA_HONG.stl` | Cửa bên phải 184.2 × 85.2 mm, có khe nguồn 60 × 25 | 22.0 | 0.9 h |
| `PHU_KIEN_1.stl` | 4 kẹp giữ màn hình | 4.2 | 0.2 h |
| **Tổng** | | **≈ 502** | **≈ 16.3 h** |

Tất cả file nằm trong `VO_RIENG_420/` (cùng `VO_RIENG_420.zip`) và đã xoay sẵn theo hướng in. Đơn vị mm, scale 100%.

## Thiết kế chính

- **Lớp da ngoài kín.** Các tấm nắp (`CUA_HONG`, `CUA_SAU_TREN`, `NAP_NGANG`, `CUA_SAU_DUOI`) có lớp da 0.6 mm ở mặt ngoài. Phần trong được khoét thành túi (ô ~22 mm, gân 2 mm, sâu 1.4 mm). Mặt ngoài in mịn, không cần support.
- **Ít support.** Mọi khối treo trên vách có gân chéo 45°. Trần đế trước là mái hai dốc 45°. Khe thông gió trên vách trái là khe lá sách nghiêng 45°.
- **Nắp chữ L** (`CUA_SAU_TREN`) gộp mặt sau trên và mái khối màn hình, hạ thẳng từ trên xuống. Có một đường ghép 2 mm dưới đỉnh.
- **Khe thoát nhiệt:** 10 khe 4 × 80 mm trên `NAP_NGANG`, nằm ngay trên hộp Pi.
- **Khe nguồn** 60 × 25 mm trên cửa bên phải (y 72.5–132.5, cách sàn 20 mm). Khe này được giữ hở để cắm dây. 4 khe dây rút nằm cạnh khe nguồn cũng để hở.
- **Không có thanh ngang và không có chân đế.** Sàn khoét dải rộng tối đa 20 mm; có gờ 10 mm quanh hộp Pi và buồng tối.

## Lắp ghép

Dùng **19 bulông M4 × 16** và đai ốc M4 (AF 7.4 mm) nằm trong túi lục giác:

- `CUA_HONG`: 4 bulông vào 4 trụ trên vách. Đai ốc nằm trong túi lục giác sau 3.7 mm.
- `CUA_SAU_DUOI`: 3 bulông. 2 bulông trên vào khối góc sau, 1 bulông dưới-phải vào trụ trên sàn.
- `NAP_NGANG`: 4 bulông đi từ dưới lên. 3 bulông vào khối góc, 1 bulông vào khối trên `CUA_HONG`. Khối này nằm trên mặt trong cửa, nên **phải tháo bulông đó trước khi tháo cửa**.
- `CUA_SAU_TREN`: 4 bulông vào trụ hai bên khối màn hình.
- 4 kẹp màn hình: mỗi kẹp 1 bulông M4 × 16.

**Thứ tự lắp hộp Pi:** tháo `NAP_NGANG`, hạ hộp Pi xuống rồi đẩy ra trước 20 mm. Hoặc tháo `CUA_HONG` rồi rút hộp Pi ngang qua cửa. Sau đó tháo `CUA_SAU_DUOI` và trượt buồng tối vào từ phía sau.

Kích thước bulông, khe lắp và đường đi của đai ốc đều đã được kiểm tra trên CAD. **Chưa lắp vật thật.** Lỗ M4 4.5 mm và túi đai ốc vẫn nên in một mẫu thử trước.

## Kiểm tra

Chạy từ thư mục `docs/system_3d`:

```bash
/home/huynn/.cache/ppg-cad312-venv/bin/python mac_desktop_v2_side/build.py
/home/huynn/.cache/ppg-cad312-venv/bin/python mac_desktop_v2_side/check.py
/home/huynn/.cache/ppg-cad312-venv/bin/python mac_desktop_v2_side/check_bolts.py
/home/huynn/.cache/ppg-cad312-venv/bin/python mac_desktop_v2_side/kiem_tra_lap.py
/home/huynn/.cache/ppg-cad312-venv/bin/python mac_desktop_v2_side/ban_ve.py
/home/huynn/.cache/ppg-cad312-venv/bin/python shell_only.py mac_desktop_v2_side
```

Kết quả hiện tại:
- `kiem_tra_lap.py`: **49/49** mục đạt (giao thoa, khe lắp, bulông, đường lắp Pi và buồng tối, khe nguồn).
- `check_bolts.py`: **15/15** trục bulông thông và có đủ nhựa quanh lỗ.
- `shell_only.py` sinh lại `VO_RIENG_420/` và `HUONG_DAN.txt`. Các con số trong hướng dẫn lấy từ kết quả slice ở bảng trên.

Kết quả chi tiết nằm trong `out/kiem_tra_lap.json`.

## Chưa kiểm tra

- Chưa in thử, chưa lắp vật thật. Các số gam và giờ là ước tính của slicer cho máy H2S, không phải máy 420 × 420 × 500.
- Chưa đo nhiệt độ Pi khi hộp đóng kín. Với 10 khe trên `NAP_NGANG` và các lỗ sàn, cần chạy Pi đầy tải khoảng 20 phút rồi đo bằng `vcgencmd measure_temp` và `vcgencmd get_throttled`.
- Chưa kiểm tra độ vừa của khe và đai ốc thật, cũng như độ lật của vỏ khi nghiêng.
- Trong Tinkercad, mặt ngoài phẳng có thể hiện các đường ngang hoặc chấm rỗ. Đó là lỗi hiển thị do lưới tam giác dài và mảnh, không phải lỗi hình học. Bambu Studio không báo lỗi khi slice.

## Tái dựng

Mã nguồn: `build.py` (hình học), `check.py`, `check_bolts.py`, `kiem_tra_lap.py` (kiểm tra), `ban_ve.py` (bản vẽ `BAN_VE_KICH_THUOC.png`), `../shell_only.py` (xuất STL và `HUONG_DAN.txt`), `../render_side.py` (ảnh render, có trong `render360/`).

Thư mục này dùng lại buồng tối và hộp Pi từ `../cyberdock_v3`. Các thông số lấy từ `build.py`, không sửa tay file STL.
