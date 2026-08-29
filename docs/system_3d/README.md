# PPG Simulator — Mô hình 3D toàn hệ thống (Raspberry Pi)

> Mô hình 3D **toàn bộ hệ thống** PPG Simulator: hộp tối quang 2 làn (Red 622 nm /
> IR 875 nm → 2× OPT101) + board cảm biến 5×7 cm + đế chung mang Pi 4, Grove HAT,
> board driver LED và 2× MCP4725. Sinh bằng script tham số `build_system.py`
> (trimesh + Manifold CSG), duyệt trực tiếp trên trình duyệt tại `viewer.html`
> (three.js, chạy offline).

Kế thừa thiết kế buồng đơn trong `chamber_3d/`; file này dựng **toàn hệ thống**
gắn trên một đế chung và bổ sung khối điện tử ngoài hộp tối.

---

## 1. Kiến trúc hệ thống (đúng theo sơ đồ trong docs/architecture/)

```
┌────────────────────────────── Raspberry Pi 4 ─────────────────────────────┐
│                                                                            │
│  ┌───────────────┐   I2C bus   ┌────────────────────────────────────────┐  │
│  │  main.py      │────────────▶│  TX: LED driver (led_driver/ + hw/)    │  │
│  │  (CTkApp UI)  │             │                                        │  │
│  │               │  MCP4725 #1 │  MCP4725 #1 (0x60) ─ IR  DAC channel   │  │
│  │  SignalEngine │  MCP4725 #2 │  MCP4725 #2 (0x61) ─ Red DAC channel   │  │
│  │  (1 kHz PPG)  │             │  10 kΩ/10 kΩ divider → V_cmd = Vdac/2  │  │
│  │  param_ctl    │             │  LM358 (op-amp) → 2SC1815 current sink │  │
│  │  state_machine│             │  R_sense: IR R3=82 Ω / Red R6=100 Ω    │  │
│  └──────┬────────┘             └───────────────────┬────────────────────┘  │
│         │                                          │ I_LED (V_cmd/R_sense) │
│         │           ┌──────────────────────────────▼─────────────────────┐ │
│         │           │  HỘP TỐI + BOARD 5×7 + ĐẾ (docs/system_3d/)       │ │
│         │           │   Làn Đỏ z=-19.25: LED 622 nm ──▶ OPT101 #2 (A2)  │ │
│         │           │   Làn IR  z=+19.25: LED 875 nm ──▶ OPT101 #1 (A0)  │ │
│         │           │   Trục trượt D d=15..90 + tấm khẩu độ (x=113..115) │ │
│         │           └──────────────────────┬─────────────────────────────┘ │
│         │                     V_out (0..~2.13 V, 300..1100 nm)             │
│         │           ┌──────────────────────▼─────────────────────────────┐ │
│         ├───────────▶│  RX: OPT101 → Grove ADC (hw/opt101_rx.py)         │ │
│         │   (UI hiển │   Grove Base HAT ADC 0x08, 12-bit                 │ │
│         │   thị A0/A2)│   A0 = IR · A2 = Red · A1 không dùng             │ │
│         │            │   Thread "OPT101Rx" 100 Hz, buffer 2000           │ │
│         │            └───────────────────────────────────────────────────┘ │
│         ▼                                                                   │
│  core/: signal_engine (tạo PPG 1 kHz), digital_filters, csv/tx_rx logger   │
│  ui/:   ctk_app.py + frames (playback, pathology, calibration)             │
│  models/ppg_model.py · config.py · config_store.py · calibration.py        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Quy ước trục & bố trí (mm)

Hệ lắp ráp (xem thêm header `build_system.py` §1):

| Trục | Ý nghĩa |
|---|---|
| **+X** | Trục quang, từ đầu LED → cửa sổ OPT101 |
| **+Y** | Lên trên |
| **+Z** | Ngang; **làn Đỏ ở -Z**, **làn IR ở +Z**, vách ngăn quang tại z=0 |

- Kích thước hộp tối: **150 × 67 × 80 mm** (X×Y×Z, gồm nắp).
- Trục quang tại y=32 mm; tâm 2 làn tại z = ±19.25 mm.
- Đế chung: **198 × 244 mm**, chia đôi tại z=0 (mỗi nửa 190×122 mm — vừa bàn in
  thông dụng). Nửa `-Z`: Pi 4 + Grove HAT; nửa `+Z`: board driver + 2× MCP4725.
- Khoảng cách mặc định (chóp LED → cửa sổ OPT101 tại x=120): **Đỏ d=25 mm**,
  **IR d=85 mm** — theo ngân sách quang học `chamber_3d/README.md` §4 (Đỏ để gần
  vì LED yếu, IR để xa để tránh bão hòa).

Bố trí tổng thể theo X:

| x (mm) | Thành phần |
|---|---|
| 0..111 | Lòng hộp tối (2 làn, vách ngăn liền khối 3 mm tại z=0) |
| 1..111 | Trục trượt D-shaft Ø8 (mỗi làn) |
| 113..115 | Rãnh trượt tấm khẩu độ |
| 120 | Mặt cửa sổ OPT101 (= mốc đo d) |
| 124.3..125.5 | Module OPT101 PDIP-8 + PCB nhỏ |
| 137.5..139.1 | Board cảm biến 5×7 cm dựng đứng |
| 141.5..147 | Vách ngăn sau khung board |
| -24..174 | Đế chung (Pi 4 + Grove HAT + driver + 2× MCP4725) |

---

## 3. Cơ chế chống rò sáng (light-tightness)

1. **Tường 3 mm đặc** — LED đặt trong, trên carrier trượt, không khoan xuyên tường.
2. **Vách ngăn 3 mm** liền khối giữa 2 làn Đỏ/IR — cách ly quang tuyệt đối
   (OPT101 nhạy toàn dải 300–1100 nm nên 2 làn phải tách hẳn).
3. **Nắp labyrinth** — rãnh khóa ngoằn ngoèo trên đỉnh thành + môi nắp khớp khuôn.
4. **Chụp che sáng (hood)** trước mỗi lỗ ra cáp — ánh sáng phải quay 90° hai lần
   mới tới lỗ vách; bắt vít M3 mù vào bệ dày trên thân hộp.
5. **Tấm khẩu độ** trượt trong rãnh sàn tại x=113..115, ngay trước sensor:
   `blank` (bịt — đo nền tối), `d2` (Ø2), `d5` (Ø5), `d16` (Ø16).
6. **Khung giữ board 5×7** bịt kín tiết diện lòng hộp, mang bản vách ngăn nối tiếp
   phía sau; dây đi qua cửa luồn có chủ đích (không để hở đường sáng).

---

## 4. Cơ cấu điều chỉnh khoảng cách

- **Trục trượt D-shaft Ø8** mỗi làn (x=1..111), vát phẳng chống xoay; vạch chia
  5 mm (vạch lớn mỗi 25 mm) trên mặt vát, dải d=15..90 mm.
- **Carrier LED** (khối trượt 22×18 mm) ôm trục bằng lỗ D + kẹp xẻ rãnh xiết vít
  M3, loa che sáng 45° trước chóp LED; vạch chỉ vị trí phía trên.
- Vị trí mặc định: **Đỏ d=25 mm**, **IR d=85 mm** — chính là trạng thái ban đầu
  của model và viewer.

---

## 5. Các phần in 3D (16 file STL — out/stl/)

| File | Vai trò | Số lượng in |
|---|---|---|
| `body.stl` | Thân hộp tối (2 làn + vách ngăn + máng dây + bệ vít) | 1 |
| `lid.stl` | Nắp labyrinth + vấu chặn khung | 1 |
| `slide_shaft_red.stl` | Trục trượt D Ø8 — dùng chung 2 làn (đối xứng) | 1 |
| `led_carrier_red.stl` | Carrier LED — dùng chung 2 làn | 2 |
| `frame.stl` | Khung giữ board 5×7 | 1 |
| `aperture_red_blank.stl` | Khẩu độ bịt kín (nền tối) | 2 (Đỏ + IR) |
| `aperture_red_d2.stl` | Khẩu độ Ø2 mm | 2 |
| `aperture_red_d5.stl` | Khẩu độ Ø5 mm | 2 |
| `aperture_red_d16.stl` | Khẩu độ Ø16 mm | 2 |
| `hood_l_red.stl` | Chụp che sáng trái (thành -X, cáp LED) | 1 |
| `hood_r_red.stl` | Chụp che sáng phải (thành +X, cáp OPT101) | 1 |
| `base_neg.stl` | Đế — nửa Pi 4 + Grove HAT | 1 |
| `base_pos.stl` | Đế — nửa driver + 2× MCP4725 | 1 |

> **Một thiết kế dùng cho cả 2 làn**: vì 2 làn quang đối xứng quanh z=0, các chi tiết
> `slide_shaft`, `led_carrier`, `aperture_*` và `hood_*` chỉ xuất bản `red` làm
> khuôn mẫu, dùng cho cả làn IR (bản `*_ir` trong `model.json` chỉ để hiển thị).
> In thêm 1 bản nữa cho mỗi làn theo bảng trên.

> **Linh kiện mua sẵn (KHÔNG in)** — chỉ hiển thị trong viewer để duyệt lắp ráp:
> `led_red`, `led_ir`, `opt101_red` (#2 → A2), `opt101_ir` (#1 → A0), `sensor_board`
> (5×7 cm), `pi4`, `grove_hat`, `driver_board` (perfboard + LM358 + 2SC1815 +
> 2× MCP4725), `wiring` (bó dây TX/RX/I2C/PWR minh hoạ).

**Thông số in khuyến nghị**

- Nhựa **đen mờ** (matte) giảm phản xạ nội buồng — PLA đủ dùng, PETG/ABS nếu LED
  công suất cao. Đế nên PETG/ABS bền cơ.
- Lớp 0.2 mm, tường ≥ 4 vòng (tường thực ≥ 2.4 mm), infill 20–30% (thân/đế),
  100% (carrier).
- Không cần hỗ trợ (support) — các file đã xoay sẵn về tư thế in (`flip` trong
  `build_system.py`).
- Đế in 2 nửa `base_neg` + `base_pos`, nối bằng 3 mộng vuông + 2 vít M3 (lỗ Ø3.5).

---

## 6. Lắp ráp

1. **Hộp tối**: ép carrier LED (kèm LED) lên trục trượt D mỗi làn; đẩy trục vào lỗ
   mù vách trái, đầu còn lại tựa cột đỡ. Lắp khung giữ board, luồn board 5×7 +
   2 module OPT101, chốt bằng 2 vấu nắp.
2. **Tấm khẩu độ**: trượt vào rãnh tại x=113..115 (bắt đầu `blank` → đo nền tối,
   sau đó `d5`/`d16`).
3. **Chụp che sáng**: bắt vít M3 mù vào 4 bệ trên thân hộp (2 đầu trục quang).
4. **Đế**: xiết 2 nửa `base_neg`/`base_pos` bằng 2 vít M3; bắt hộp tối lên đế qua
   4 tai (vít M3 Ø3.5) tại x=21/129, z=±40.
5. **Điện tử**: Pi 4 lên 4 trụ M2.5 của `base_neg`, Grove HAT cắm header; board
   driver lên 4 trụ M3 của `base_pos`, 2 breakout MCP4725 hàn trên board.
6. **Dây** theo `docs/hardware/PPG_PROTOTYPE_WIRING_AND_TEST_POINTS.md`:
   TX driver→LED qua chụp -X, RX OPT101→cáp Grove→socket A0/A2, I2C HAT→2 DAC,
   USB-C→Pi. Trong mô hình, dây được dựng thành **bẹ dây** (`harness()`): nhiều
   sợi song song sát nhau trên cùng lộ trình, buộc **dây rút (cable tie)** định
   kỳ 12–40 mm — không còn dây rời rạc thưa thớt:
   - **TX**: bẹ 2 sợi (đỏ/đen) chạy trên đế → chui qua **khe sàn chụp -X**
     (x=-19..-12) → trong lòng chụp → cổng ra → máng sàn → carrier LED.
   - **RX**: bẹ 3 sợi (đỏ/đen/vàng) từ header 6 chân module → **khe dây trên
     khung board** (y 56..60) → cửa luồn dây (y 12..58) → chụp +X → khe sàn →
     nối vào **cáp Grove trắng** vòng qua nóc hộp → socket A0/A2 trên HAT.
   - **I2C**: bẹ 2 cáp trắng chung đoạn HAT→nóc hộp, tách về 2 MCP4725.
7. Đậy nắp labyrinth; chạy `python3 main.py --dry-run` trước khi chạy thật.

---

## 7. Web viewer (duyệt mô hình 3D)

```bash
python3 -m http.server 8008 --directory docs/system_3d
# mở http://localhost:8008/viewer.html
```

Hoặc mở thẳng file `docs/system_3d/viewer.html` (three.js + OrbitControls đã nhúng,
chạy offline).

**Mô phỏng quang học (PPG)**: bấm "🔦 Bật LED phát sáng" để xem LED Đỏ và IR
phát sáng theo dạng sóng PPG (xung tâm thu — tâm trương). Điều chỉnh:
- **Nhịp tim (BPM)**: 30–200 nhịp/phút
- **Biên độ AC**: độ mạnh của thành phần xung
- **Mức nền DC**: ánh sáng nền tĩnh
- **Độ sáng**: tổng thể
- Đồ thị PPG hiển thị trên canvas, LED nhấp nháy theo nhịp, chùm sáng (nón
  mở rộng đúng góc datasheet: Đỏ 50°, IR 30°) + đèn điểm chiếu sáng lòng hộp.

**Lưu ý**: mô hình dựng bằng 3D thuần (không texture ảnh dán).

**Điều khiển**: kéo chuột xoay · lăn thu phóng · phải chuột di chuyển ·
thanh **Tách rời** xem thứ tự lắp · thanh **Mặt cắt theo X** cắt dọc trục quang ·
nút **Trong suốt thân** xuyên qua hộp thấy LED + OPT101 · nút **Trong làn IR/Đỏ**
đưa camera ngang trục quang từng làn · nút **Trục quang** hiện 2 trục Đỏ/IR ·
nút **Khối điện tử** xem đế (Pi + HAT + driver + DAC) · nút **Tự xoay** ·
checkbox ẩn/hiện từng bộ phận (nhãn tiếng Việt; đỏ = LED Đỏ, tím = LED IR,
xanh dương = cửa sổ OPT101, trắng = cáp Grove).

### Ảnh preview tĩnh (không cần mở trình duyệt)

| Ảnh | Mô tả |
|---|---|
| `out/preview_assembled.png` | Lắp ráp hoàn chỉnh (3 góc) |
| `out/preview_exploded.png` | Tháo rời — thứ tự lắp ráp |
| `out/preview_cross_section.png` | Mặt cắt nhìn từ nóc: 2 làn Đỏ (-Z) / IR (+Z) |
| `out/preview_electronics.png` | Khối điện tử trên đế chung (Pi + HAT · driver + DAC) |

Tái sinh ảnh (cần matplotlib): `../../.cad_venv/bin/python render_preview.py`

Tái sinh texture từ ảnh thô (cần Pillow): `../../.cad_venv/bin/python process_images.py`
(chạy trong `chamber_3d/`, sau đó copy `assets/textures.json` + `*.png` sang đây
hoặc đồng bộ thủ công — script hiện ghi vào `chamber_3d/assets/`).

---

## 8. Tái sinh mô hình (single source of truth)

Mọi tham số nằm ở §1 đầu `build_system.py` (mm); thay đổi → chạy lại:

```bash
../../.cad_venv/bin/python build_system.py        # STL + model.json + viewer.html
../../.cad_venv/bin/python render_preview.py      # 4 ảnh preview (matplotlib)
```

Chạy từ thư mục `docs/system_3d/` hoặc từ gốc repo (đường dẫn tuyệt đối trong script).

Phụ thuộc: `trimesh`, `manifold3d`, `numpy`, `matplotlib` (đã cài trong `.cad_venv/`).

---

## 9. Bằng chứng kích thước & giới hạn

- `[DS]` kích thước OPT101 (PDIP-8, vùng nhạy 2.29² mm), LED 3 mm, Grove HAT
  (MM32F031F6P6, ADC 0x08) — lấy từ datasheet trong `docs/ds_linhkien/`.
- `[SPEC]` Pi 4B (PCB 85×56×1.4, lỗ M2.5 bước 58×49), khuôn HAT 65×56.5.
- `[ASSUME]` toạ độ chi tiết connector/IC và bó dây **chưa đo trên vật thật** —
  chỉ để nhận dạng trực quan, **KHÔNG dùng để gia công**. Đo lại trước khi in/đặt
  linh kiện (đánh dấu `[ASSUME]` trong `build_system.py`).

Mô hình là công cụ thiết kế & mô phỏng. Không phải thiết bị y tế, không có giá trị
lâm sàng.
