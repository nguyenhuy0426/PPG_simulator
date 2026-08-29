# PPG Simulator — Mô hình 3D toàn hệ thống

Viewer 3D offline của mô hình PPG Simulator (Raspberry Pi 4): hộp tối 2 làn quang
(Đỏ 622nm / IR 875nm → 2× OPT101) trên đế chung mang Pi 4 + Grove HAT + board
driver LED (LM358 + 2× 2N4401 + 2× MCP4725).

## 🔗 Xem mô hình

Mở thẳng: **https://nguyenhuy0426.github.io/PPG_simulator/**

(File `index.html` là viewer three.js tự chứa hoàn toàn — không cần server,
có thể tải về và mở offline bằng double-click.)

## 🎮 Điều khiển

- **Kéo chuột** xoay · **lăn chuột** zoom · **chuột phải** di chuyển
- **Tách rời / Mặt cắt**: thanh trượt xem thứ tự lắp ráp và cắt dọc trục quang
- **🔦 Bật LED phát sáng**: LED Đỏ & IR phát sáng theo sóng PPG thật
  (mô hình 3-Gaussian Allen 2007, port từ `models/ppg_model.py`)
- Điều chỉnh: **Nhịp tim, PI, SpO₂, Nhịp thở** — LED nhấp nháy theo nhịp
- **R cảm biến (E→GND)**: chọn giá trị → 4 vòng màu trên điện trở 3D đổi theo
  mã 4 vạch ±5%, hiển thị I_LED = V_DAC / R (mA) tức thời
- **🏷️ Nhãn linh kiện**: nhãn MCP4725, LM358, 2N4401, R_sense, OPT101…

## 📁 Mã nguồn

Toàn bộ mã nguồn dựng mô hình nằm ở branch [`huynn`](https://github.com/nguyenhuy0426/PPG_simulator/tree/huynn)
— xem `docs/system_3d/build_system.py` (single source of truth, tham số mm).
