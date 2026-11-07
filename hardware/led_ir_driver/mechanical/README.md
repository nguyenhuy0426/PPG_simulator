# Adapter driver 70 × 40 mm — không vít, 4 nút nhựa thẳng

- `driver_70x40_adapter_print.stl`: bao 70 × 55 × 6 mm, tấm dày 1,6 mm, in nằm
  (mặt tấm áp bàn), không support. Ít nhựa hơn bản bốn vít cũ 31 %
  (2 732 mm³ so với 3 947 mm³).
- `driver_snap_button_print.stl`: **nút nhựa thẳng**, cần 4 cái. Cao 8,6 mm, đầu
  Ø5,6 × 1,0, thân thon Ø3,05 sát đầu → Ø2,45 ở chóp, **không khấc, không gờ**.
  In dựng, đầu áp bàn, không support.

## Lắp PCB driver

PCB đặt tại (0; 7; 6) mm trên adapter, tựa lên bốn ống Ø6. Bốn lỗ PCB Ø3,2 tại
local (4;24), (66;24), (4;36), (66;36) mm; mỗi lỗ có một lỗ Ø2,9 xuyên ống đỡ và
tấm gá. Đặt PCB lên ống, lỗ thẳng hàng, rồi ấn từng nút từ trên xuống tới khi đầu
nút chạm mặt PCB. Nút giữ bằng **ma sát** trong lỗ ống (lỗ in ra nhỏ hơn 2,9 mm,
thân thon nêm vào). Gỡ bằng cách kéo thẳng đầu nút lên, có thể dùng nhíp.

Độ ôm phụ thuộc độ hụt lỗ in của máy (giả định A1 hụt 0,2–0,4 mm):

| Lỗ in hụt | Ôm mỗi bên | Đoạn ôm trong ống |
|---|---|---|
| 0 mm | 0,01 mm | 0,3 mm: **gần như lỏng** |
| 0,2 mm | 0,11 mm | 2,8 mm |
| 0,4 mm | 0,21 mm | 5,4 mm: chặt, cần ấn mạnh |

Nếu in ra mà nút **lỏng**: quấn một vòng băng keo mỏng quanh thân nút hoặc chấm
keo nến vào lỗ. Nếu **quá chặt**: mài nhẹ thân nút bằng giấy nhám, không bẻ.

## 4 lỗ trùng Grove Base Hat

Bốn lỗ góc Ø3,2 (in ra ~2,8–3,0, lọt trụ/ren M2.5) nằm tại X = 6 / 64, Y = 3 / 52 mm,
bước **58 × 49 mm**. Tấm gá nằm chồng lên trụ đồng M2.5 xếp trên Grove Base Hat.
Các lỗ cách PCB driver ≥ 4 mm nên không bị che.

**Nguồn số liệu:** file Eagle chính thức của Seeed (`Raspberry Pi Grove Base HAT
v1.0.zip`, link ở trang wiki): board 65 × 56 mm, 4 lỗ Ø2,75 tại (3,5; 3,5),
(3,5; 52,5), (61,5; 3,5), (61,5; 52,5). Bước 58 × 49 mm khớp với gá. Đây là dữ
liệu thiết kế, chưa đo trên Hat thật.

**Chưa biết:** trang wiki không có file 3D của Hat, nên **chiều cao** các cổng Grove
và chip trên Hat chưa được kiểm tra. Chọn chiều cao trụ đồng đủ cao hơn linh kiện
cao nhất của Hat, đo bằng thước cặp trên Hat thật.

## Kiểm tra

- Nút không chạm PCB và không chạm gá (ngoài phần ôm ma sát 0,009 mm³).
- Đầu nút cách vùng courtyard linh kiện gần nhất (R9) 0,68 mm, cách pad 1,04 mm;
  khoảng cách này tính từ pad và courtyard trong file KiCad, **không** phải thân
  linh kiện 3D.
- Thân nút lọt lỗ PCB Ø3,2, hở 0,075 mm mỗi bên.
- C7 mặt sau nằm trên cửa rỗng giữa adapter; chân hàn dài tối đa 2 mm.

`fit_report.json` chỉ xác nhận hình học danh nghĩa; chưa thử in, chưa thử ép nút.
