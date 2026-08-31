# PPG Simulator — Mô hình 3D toàn hệ thống (Raspberry Pi)

> Mô hình 3D **toàn bộ hệ thống** PPG Simulator: hộp tối quang 2 làn (Red 622 nm
> [ASSUME] / IR 875 nm → 2× OPT101) + board cảm biến 5×7 cm + đế chung mang Pi 4, Grove HAT,
> board driver LED và 2× MCP4725. Sinh bằng script tham số `build_system.py`
> (trimesh + Manifold CSG), duyệt trực tiếp trên trình duyệt tại `viewer.html`
> (three.js, chạy offline).

Kế thừa thiết kế buồng đơn v1 (bản legacy — xem lịch sử git trước commit xóa
`chamber_3d/`); file này dựng **toàn hệ thống** gắn trên một đế chung và bổ
sung khối điện tử ngoài hộp tối.

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
│  │  param_ctl    │             │  LM358 (op-amp) → 2×2N4401 current sink│  │
│  │  state_machine│             │  R_sense: IR R3=82 Ω / Red R6=100 Ω    │  │
│  └──────┬────────┘             └───────────────────┬────────────────────┘  │
│         │                                          │ I_LED (V_cmd/R_sense) │
│         │           ┌──────────────────────────────▼─────────────────────┐ │
│         │           │  HỘP TỐI + BOARD 5×7 + ĐẾ (docs/system_3d/)       │ │
│         │           │   Làn Đỏ z=-19.25: LED 622nm*──▶ OPT101 #2 (A2)  │ │
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

> \* Bước sóng **622 nm** của LED Đỏ là `[ASSUME]` — BOM không ghi rõ bước sóng
> này; đo kiểm trên vật thật trước khi hiệu chuẩn (Stage 6).

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
- Đế chung: **198 × 286 mm**, chia đôi tại z=0 (nửa `-Z` ~198×164 mm, nửa `+Z`
  ~198×122 mm — vừa bàn in thông dụng). **Nửa `-Z` chứa toàn bộ khối điện tử**:
  Pi 4 + Grove HAT + board driver (xoay 90°) + 2× MCP4725 cùng nằm một bên;
  nửa `+Z` chỉ đỡ hộp tối.
- Khoảng cách mặc định (chóp LED → cửa sổ OPT101 tại x=120): **Đỏ d=25 mm**,
  **IR d=85 mm** — theo ngân sách quang học §2.1 dưới đây (Đỏ để gần
  vì LED yếu, IR để xa để tránh bão hòa).

### 2.1 Ngân sách quang học (di chuyển từ chamber_3d §4 — bản legacy)

Mô hình điểm-xấp-xỉ-nghịch-bình-phương `V_out = Rv × Ie × (A/d²) + V_dark`:

**Kênh ĐỎ (622 nm — [ASSUME])** — LED yếu → để gần sensor:

| Vdac | I_LED | d=15 | d=25 | d=40 | d=60 | d=85 mm |
|---|---|---|---|---|---|---|
| 1.0 V | 5.0 mA | 1.457 | **0.529** | 0.211 | 0.098 | 0.053 V |
| 2.0 V | 10 mA | 2.907 | **1.051** | 0.415 | 0.189 | 0.098 V |

→ **d = 25 mm** khuyến nghị: dải Vdac 0.5–3.28 V đều dưới trần 2.13 V (không kẹp).

**Kênh IR (875 nm)** — LED rất mạnh → phải để xa để tránh bão hòa:

| Vdac | I_LED | d=25 | d=60 | d=85 mm |
|---|---|---|---|---|
| 1.0 V | 6.1 mA | 11.29 (⚠ kẹp) | 1.966 | **0.983** V |
| 2.0 V | 12.2 mA | 22.57 (⚠ kẹp) | 3.925 | **1.959** V |

→ **d = 85 mm** khuyến nghị: tại d=85 Vdac được phép tới 2.17 V; tại d=25 chỉ
0.19 V (gần như không điều khiển được). Đây là lý do ray trượt phải dài 15–85 mm.

> ⚠ Giá trị Rv 0.35/0.49 V/µW là ước lượng đồ thị từ datasheet (chỉ 0.45 A/W
> @650 nm được ghi rõ). Trước khi chốt hiệu chuẩn nên đo thực tế ở Stage 6.

> Nguồn: `chamber_3d/README.md` §4 — thư mục legacy đã bị xóa khỏi source
> tree (lịch sử git vẫn giữ đầy đủ). Lưu ý: dải d 15–85 mm của bản legacy
> đã mở thành **15–90 mm** trong v2 (`D_MIN, D_MAX = 15.0, 90.0` trong
> `build_system.py`).

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
   mới tới lỗ vách; bắt 2 vít M3×8 QUA bích chụp (lỗ xuyên từ mặt ngoài),
   tự khoan vào mồi Ø2.5 sâu 2.6 mm trên vách.
5. **Tấm khẩu độ** trượt trong rãnh sàn tại x=113..115, ngay trước sensor:
   `blank` (bịt — đo nền tối), `d2` (Ø2), `d5` (Ø5), `d16` (Ø16).
6. **Khung giữ board 5×7** bịt kín tiết diện lòng hộp, mang bản vách ngăn nối tiếp
   phía sau; dây đi qua cửa luồn có chủ đích (không để hở đường sáng).

---

## 4. Cơ cấu điều chỉnh khoảng cách — cần trượt nam châm

- **Trục trượt D-shaft Ø8** mỗi làn (x=1..111), vát phẳng chống xoay; vạch chia
  5 mm (vạch lớn mỗi 25 mm) trên mặt vát, dải d=15..90 mm.
- **Carrier LED** (khối trượt 22×18 mm) ôm trục bằng lỗ D, **trượt tự do**
  (bỏ kẹp xẻ + vít M3 của bản v1), loa che sáng 45° trước chóp LED. Trên lưng
  carrier có **cột nam châm** (đỉnh y=63.5, khe 0.5 mm tới nóc buồng) chứa
  nam châm đĩa **Ø10×3 N35** ép khít vào hốc mù mở trên đỉnh cột + 1 giọt keo;
  tâm cột = x_front − 12.
- **Cần trượt nam châm** (khối 16×14×5.3) chạy trong 2 ray dẫn trên nắp, đáy
  nằm trên panel recess mỏng 2.2 mm: nam châm trong cần ↔ nam châm trong cột
  carrier **cộng hưởng xuyên nắp** → kéo carrier dọc trục từ NGOÀI hộp, không
  cần mở nắp, cơ cấu **không thêm khe hở nào** → kín sáng tuyệt đối.
- Mapping hành trình: **tâm cần x = 107 − d** (d=15..90 → x=92..17), chặn đầu
  bởi 2 stop trên nắp (x=9 và x=100..101).
- **Thước khắc trên nắp**: d=15..90 bước 5 mm, NGOÀI mỗi ray; vạch to tại
  **Đỏ d=25** (x=82) và **IR d=85** (x=22).
- [ASSUME] lực kéo ước tính **3–6 N** (cặp nam châm N35 Ø10×3 qua 2.2 mm nhựa)
  — **chưa đo trên vật thật**. Nếu kéo yếu: dán thêm 1 nam châm vào cần
  (tăng diện tích cộng hưởng) hoặc nhỏ giọt keo/mối bôi trơn giảm ma sát ray.
- Vị trí mặc định: **Đỏ d=25 mm** (tâm cần x=82), **IR d=85 mm** (tâm cần
  x=22) — chính là trạng thái ban đầu của model và viewer.

---

## 5. Các phần in 3D (14 file STL — out/stl/)

| File | Vai trò | Số lượng in |
|---|---|---|
| `body.stl` | Thân hộp tối (2 làn + vách ngăn + máng dây + mồi vít chụp) | 1 |
| `lid.stl` | Nắp labyrinth + 2 ray cần trượt nam châm + thước khắc d | 1 |
| `slide_shaft_red.stl` | Trục trượt D Ø8 — dùng chung 2 làn (đối xứng) | 2 |
| `led_carrier_red.stl` | Carrier LED (trượt tự do + cột nam châm) — dùng chung 2 làn | 2 |
| `mag_slider_red.stl` | Cần trượt nam châm (kèm nam châm Ø10×3) — dùng chung 2 làn | 2 |
| `frame.stl` | Khung giữ board 5×7 | 1 |
| `aperture_red_blank.stl` | Khẩu độ bịt kín (nền tối) | 2 (Đỏ + IR) |
| `aperture_red_d2.stl` | Khẩu độ Ø2 mm | 2 |
| `aperture_red_d5.stl` | Khẩu độ Ø5 mm | 2 |
| `aperture_red_d16.stl` | Khẩu độ Ø16 mm | 2 |
| `hood_l_red.stl` | Chụp che sáng trái (thành -X, cáp LED) — dùng chung 2 làn | 2 |
| `hood_r_red.stl` | Chụp che sáng phải (thành +X, cáp OPT101) — dùng chung 2 làn | 2 |
| `base_neg.stl` | Đế — nửa Pi 4 + Grove HAT + driver | 1 |
| `base_pos.stl` | Đế — nửa dưới hộp tối | 1 |

> **Một thiết kế dùng cho cả 2 làn**: vì 2 làn quang đối xứng quanh z=0, các chi tiết
> `slide_shaft`, `led_carrier`, `mag_slider`, `aperture_*` và `hood_*` chỉ xuất bản
> `red` làm khuôn mẫu, dùng cho cả làn IR (bản `*_ir` trong `model.json` chỉ để
> hiển thị — không có file STL riêng). In thêm 1 bản nữa cho mỗi làn theo bảng trên.

> **Linh kiện mua ngoài (KHÔNG in)** — **4× nam châm đĩa Ø10×3 N35** (2 vào carrier,
> 2 vào cần trượt), **8× vít M3×8** (bắt 4 chụp cáp), **4× vít M3×16** (tai bắt hộp
> xuống đế). Ngoài ra chỉ hiển thị trong viewer để duyệt lắp ráp: `led_red`, `led_ir`,
> `opt101_red` (#2 → A2), `opt101_ir` (#1 → A0), `sensor_board` (5×7 cm), `pi4`,
> `grove_hat`, `driver_board` (perfboard + LM358 + 2×2N4401 + 2× MCP4725), `wiring`.

**Thông số in khuyến nghị**

- Nhựa **đen mờ** (matte) giảm phản xạ nội buồng — PLA đủ dùng, PETG/ABS nếu LED
  công suất cao. Đế nên PETG/ABS bền cơ.
- Lớp 0.2 mm, tường ≥ 4 vòng (tường thực ≥ 2.4 mm), infill 20–30% (thân/đế),
  100% (carrier).
- Bản in sẵn tư thế (không support) là gói `--bambu` trong `out/print_bambu/`;
  STL trong `out/stl/` giữ hệ thế giới (mở bằng slicer cần xoay — xem §8.3).
- Đế in 2 nửa `base_neg` + `base_pos`, nối bằng **5 mộng vuông** (10/43/77/111/144)
  — không cần vít bắt chéo đường nối z=0.

---

## 6. Lắp ráp

1. **Hộp tối**: ép carrier LED (kèm LED) lên trục trượt D mỗi làn (trượt tự do,
   không vít); đẩy trục vào lỗ mù vách trái, đầu còn lại tựa cột đỡ. Nhét nam
   châm Ø10×3 vào hốc đỉnh cột carrier (ép khít + 1 giọt keo). Lắp khung giữ
   board, luồn board 5×7 + 2 module OPT101, chốt bằng 2 vấu nắp.
2. **Tấm khẩu độ**: **LẮP TRƯỚC KHI ĐÓNG NẮP** — trượt vào rãnh tại x=113..115
   (bắt đầu `blank` → đo nền tối, sau đó `d5`/`d16`).
3. **Chụp che sáng**: bắt 2 vít M3×8 QUA bích (lỗ xuyên từ mặt ngoài) vào mồi
   Ø2.5 trên vách hộp — 4 chụp (mỗi làn 1 cặp trái/phải — mỗi file in 2 bản),
   8 vít M3×8.
4. **Đế**: ghép 2 nửa `base_neg`/`base_pos` bằng 5 mộng vuông; bắt hộp tối lên
   đế qua 4 tai (vít M3×16) tại x=21/129, z=±40.
5. **Điện tử**: Pi 4 lên 4 trụ M2.5 của `base_neg`, Grove HAT cắm header; board
   driver (xoay 90°) lên 4 trụ M3 của `base_neg` — **cùng bên -Z với Pi** —,
   2 breakout MCP4725 hàn trên board.
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
7. **Nắp + cần trượt**: đậy nắp labyrinth; nhấn nam châm Ø10×3 vào hốc đáy 2
   cần trượt (+1 giọt keo), đặt cần lên 2 ray trên nắp; kéo tới vạch to
   **25 (Đỏ)** / **85 (IR)** — carrier chạy theo trong lòng hộp. Chạy
   `python3 main.py --dry-run` trước khi chạy thật.

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
nút **🧱 Vách ngăn quang** tô đỏ lớp ngăn z=0 (minh hoạ, không phải hình học in) ·
checkbox ẩn/hiện từng bộ phận (nhãn tiếng Việt; đỏ = LED Đỏ, tím = LED IR,
xanh dương = cửa sổ OPT101, trắng = cáp Grove).

**Trượt vị trí LED**: mục *"Vị trí LED — cần trượt nam châm"* có 2 slider d=15..90 mm —
carrier + LED + chùm sáng + cần trượt di chuyển dọc trục D đúng cơ cấu vật lý, chùm
sáng giữ nguyên góc mở datasheet và luôn ghim đầu xa tại cửa sổ OPT101 (x=120).

### Ảnh preview tĩnh (không cần mở trình duyệt)

| Ảnh | Mô tả |
|---|---|
| `out/preview_assembled.png` | Lắp ráp hoàn chỉnh (3 góc) |
| `out/preview_exploded.png` | Tháo rời — thứ tự lắp ráp |
| `out/preview_cross_section.png` | Mặt cắt nhìn từ nóc: 2 làn Đỏ (-Z) / IR (+Z) |
| `out/preview_electronics.png` | Khối điện tử trên đế chung (Pi + HAT · driver + DAC) |

Tái sinh ảnh (cần matplotlib): `../../.cad_venv/bin/python render_preview.py`

Tái sinh texture từ ảnh thô (cần Pillow): `../../.cad_venv/bin/python process_images.py`
(chạy ngay trong `docs/system_3d/` — đọc `assets/*_raw.jpg`, ghi
`assets/textures.json` + `assets/*.png`).

---

## 8. Tái sinh mô hình (single source of truth)

Mọi tham số nằm ở §1 đầu `build_system.py` (mm); thay đổi → chạy lại:

```bash
../../.cad_venv/bin/python build_system.py        # STL + model.json + viewer.html
../../.cad_venv/bin/python render_preview.py      # 4 ảnh preview (matplotlib)
```

Chạy từ thư mục `docs/system_3d/` hoặc từ gốc repo (đường dẫn tuyệt đối trong script).

Phụ thuộc: `trimesh`, `manifold3d`, `numpy`, `matplotlib` (đã cài trong `.cad_venv/`).

### 8.1 Các chế độ build (CLI)

| Lệnh | Kết quả | Dùng khi |
|---|---|---|
| `build_system.py` | STL **full** + model.json + viewer.html | Viewer trình diễn / ảnh đẹp (mặc định) |
| `build_system.py --detail simple` | STL **simple** + model.json + viewer | Mô hình in 3D tối giản, vẫn duyệt web được |
| `build_system.py --detail simple --stl-only` | Chỉ STL simple | Xuất file in nhanh (~1 s) |
| `… --stl-only --only carrier` | Chỉ STL khớp tên (`led_carrier_*`) | Chỉnh 1 chi tiết, build lại từng phần |
| `build_system.py --no-visual` | STL full + model.json không dây/board mua sẳn | Viewer gọn, bỏ chi tiết minh hoạ |
| `build_system.py --bambu` | Gói in Bambu A1 (`out/print_bambu/`) | **Xuất file đưa thẳng vào máy in** |

**`--detail simple` khác `full` ở chỗ nào?** Chỉ giữ chi tiết **chức năng** trên các
chi tiết in 3D, bỏ toàn bộ chi tiết thẩm mỹ:

| Chi tiết | `full` | `simple` |
|---|---|---|
| `body` | + vát 4 góc đứng, chỉ bóng ngang, vát vành mép | Mặt phẳng, góc vuông |
| `lid` | + panel giữa thụt (chức năng: ray/chặn cần trượt giữ nguyên cả 2 chế độ), vát vành | Tấm phẳng + rãnh labyrinth + ray/chặn cần trượt |
| `hood` | + vát góc ngoài | Hộp phẳng |
| `aperture` | + khắc mã nhận dạng (vạch) | Không khắc |
| `base` | + gân chu vi dưới đế, vát góc, vát mép | Tấm phẳng 4 mm — in không phải bridge |

Mọi chi tiết chức năng (vách ngăn quang, lỗ trục, khe khẩu độ, bệ vít, mộng nối
đế, trụ đỡ board) đều **giữ nguyên ở cả 2 chế độ** — chỉ bỏ phần trang trí.

### 8.3 Gói in Bambu Lab A1 (`--bambu`)

```bash
../../.cad_venv/bin/python build_system.py --bambu
```

Xuất `out/print_bambu/` — hộp tối + trục/carrier/cần trượt + chụp luồn dây +
khẩu độ, bỏ phần đế/khung board:

| File | Chi tiết | Kích thước bàn (mm) |
|---|---|---|
| `00_ppg_hop_toi_A1_all_in_one.stl` | **Cả 11 chi tiết xếp sẵn** trên 1 bàn | ~238×233, cao 64 |
| `01_than_hop_toi.stl` | Thân hộp (đã có lỗ luồn dây, khe khẩu độ, máng dây) | 150×103, cao 64 |
| `02_nap_labyrinth.stl` | Nắp labyrinth (2 ray cần trượt + thước khắc) | 150×80, cao 12.4 |
| `03_truc_truot_D.stl` | Trục trượt D Ø8 (in 2 bản) | 110×6.5, cao 8 |
| `04_carrier_led.stl` | Carrier LED (in 2 — đáy xuống bàn, cột nam châm hướng lên) | 25×18, cao 58.5 |
| `05_can_truot_nam_cham.stl` | Cần trượt nam châm (in 2 — lật ngửa, hốc nam châm hở lên) | 16×14.4, cao 5.3 |
| `06`/`07_chup_luon_day_*.stl` | Chụp che sáng lỗ luồn dây (trái/phải) | 15.5×36, cao 21 |
| `08..11_khau_do_*.stl` | Khẩu độ bịt/Ø2/Ø5/Ø16 (nằm phẳng, tab cầm cắt gọn) | 61×35, cao 3 |

[BOM] mua ngoài: **4× nam châm đĩa Ø10×3 N35** (2 vào carrier, 2 vào cần trượt).

Tất cả đã **chuyển về hệ trục slicer** (Z = chiều cao — STL gốc trong `out/stl/`
dùng hệ thế giới Y-lên trời nên sẽ nằm nghiêng nếu mở trực tiếp) và **xoay sẵn
tư thế in không cần support**. Bambu Studio: mở file all-in-one → `Split to
objects` nếu muốn in tách bàn. In bằng nhựa đen mờ, layer 0.2mm, tường ≥4 vòng
(tham khảo §5).

**Thu nhỏ hộp**: thêm `--scale S` (ví dụ `--bambu --scale 0.85` → hộp
~128×57×68 mm, bàn in ~230×185 mm). Các cặp lắp ghép vẫn khớp nhau vì cùng tỉ
lệ; lỗ vít M3/trục Ø8 nhỏ theo (khoan lại hoặc dán). Khuyến nghị `S >= 0.8`
để tường còn ≥ 2.4 mm kín sáng. Lưu ý: hộp ở scale 1.0 đã chỉ dài 15cm —
kích thước ~23cm của file all-in-one là **bàn in xếp trải 11 chi tiết**,
không phải kích thước hộp.

### 8.2 Cấu trúc file

```
build_system.py        — hình học + tham số (single source of truth)
viewer_template.html   — giao diện viewer (HTML/JS, tách khỏi Python) — sửa
                         giao diện ở đây rồi chạy lại build_system.py
out/stl/*.stl          — chi tiết in (theo chế độ build gần nhất)
out/model.json         — hình học cho viewer (theo chế độ build gần nhất)
```

> Lưu ý: `out/` phản ánh lần build cuối. Nếu build `simple` rồi muốn quay lại
> viewer đầy đủ, chạy lại `build_system.py` (không cờ) trước khi deploy_pages.

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

---

## 10. Nhật ký sửa đổi v2 (2026-08-30)

- **(a) Cần trượt nam châm** — cơ cấu chỉnh d mới: nam châm Ø10×3 N35 trong cột
  trên lưng carrier ↔ nam châm trong cần trượt chạy trên 2 ray của nắp (tâm cần
  x = 107 − d, thước khắc d=15..90, chặn đầu hành trình). Bỏ **2 cửa hatch +
  tấm phủ hatch + vít kẹp carrier** (carrier trượt tự do) → không thêm khe hở
  nào trên hộp, kín sáng giữ nguyên.
- **(b) Lỗ vít chụp xuyên bích** [VERIFIED ray-cast trên STL]: 4 lỗ M3 trên chụp
  cáp giờ xuyên hẳn bích, vặn từ mặt ngoài (bản v1 bịt mặt ngoài, không vặn được);
  mồi trên vách sâu 2.3 → 2.6 mm.
- **(c) Mộng nối đế 3 → 5** (x=10/43/77/111/144); bỏ 2 lỗ vít M3 "xiết mối nối"
  vô dụng (vít dọc Y không thể bắt chéo đường nối z=0).
- **(d) Khe khẩu độ 1.8 → 2.0 mm** cho tấm dày 1.6 mm (khe 0.2/cạnh); tấm được
  căn giữa khe (đặt tại AP_X0 + 0.2).
- **(e) Loại STL trùng `_ir`** — `out/stl/` còn đúng **14 file** (bản `_red` dùng
  cho cả 2 làn; xoá `led_carrier_ir.stl`, `slide_shaft_ir.stl` cũ; thêm
  `mag_slider_red.stl`).
- **(f) Viewer thêm mục tải STL** (fieldset "📦 Tải file in 3D") + cập nhật nhãn
  cơ cấu thành "cần trượt nam châm".

---

## 11. Nhật ký 2026-08-31

- **(a) Bẹ dây "đi theo bẹ" 2 hành lang** — −X (dòng LED) / +X (tín hiệu):
  bẹ nhiều sợi song song buộc dây rút định kỳ, dựng bằng helper `harness()`
  trong `wires_vis()` của `build_system.py`; chỉ hiển thị trong viewer
  (không ảnh hưởng STL in).
- **(b) Chuyển ngân sách quang học legacy vào §2.1** và xóa `chamber_3d/`
  khỏi source tree (lịch sử git vẫn giữ đầy đủ).
- **(c) Chuyển `process_images.py` về `docs/system_3d/`** — đọc/ghi thẳng
  `assets/` tại chỗ, hết đồng bộ thủ công.
