# HANDOFF — Mô hình 3D hệ thống PPG simulator (`docs/system_3d`)

Tài liệu bàn giao để tiếp tục công việc ở cuộc hội thoại sau.
Cập nhật: 2026-09-02 (lần 2 — đổi bố cục, xem §0 đầu tiên). Nhãn bằng chứng: `[VERIFIED]` = đã chạy/đo được trong
phiên này, `[SPEC]/[DS]` = theo tài liệu, `[ASSUME]` = giả định, cần đo thật.

---

## 0. CẬP NHẬT BỐ CỤC (2026-09-02, SAU v3) — màn hình → Pi 4 → hộp tối

**Mục này ghi đè mục 0-v3 ở các điểm 5, 6 và mọi toạ độ đế/board driver bên dưới.**
Lý do: ở v3 màn hình nằm nửa `+Z`, tức **sau hộp tối** so với người dùng → bị che,
không nhìn/chạm được. Nay **`-Z` = MẶT TRƯỚC**, 3 cụm xếp thành 1 hàng.

Trạng thái `[VERIFIED]` **96/96 check** (`verify_geometry.py`; 15/15 STL
watertight, **14 cặp** lắp ghép giao nhau = 0 mm³), gói Bambu **không đổi**
(12 file, all-in-one 237×235 mm — `PRINT_SET` không chứa đế/chân màn hình).

| Cụm | z (mm) | Ghi chú |
|---|---|---|
| Mép trước đế | −196 | `BASE_Z0` (trước: −164) |
| 2 chân màn hình 7" | −190..−136 | x = 20/130; lỗ bắt z = −186 / −139, trên **`base_neg`** |
| Panel 7" (ngả 15°) | −175.7..−127.9 | mặt hiển thị quay về `-Z`; y 5.4..116.8, mép sau (z=−127.9) ở y ≈ 111.7 |
| Khe cắm USB-C/HDMI | −136..−112 | 24 mm trống |
| Board driver 70×55 | −112..−57 | x −12..58, **không xoay** (đã xoá ma trận `_DRV_R`) |
| Pi 4B + Grove HAT | −108..−52 | x 62..147 (giữ nguyên); kể cả connector: z −110..−51.5, cao 22 mm |
| Tai bắt hộp | ±51.5 | x = 21/129 |
| Hộp tối | −40..+40 | giữ nguyên toàn bộ |
| Lưới lỗ mở rộng 3×2 | 62 / 80 | x = 30/75/120, trên `base_pos` |
| Mép sau đế | +92 | `BASE_Z1` (trước: 122) |

- Đế chung **198 × 288 mm**; `base_neg` 198×196 (nửa TRƯỚC), `base_pos` 198×92
  (nửa SAU) — cả hai vẫn vừa bàn in 256×256. Mộng ghép tại z=0 giữ nguyên.
- Khe hở board driver `[VERIFIED]`: 4 mm tới Pi (x=62), 12 mm tới mép đế
  (x=−24), 5.5 mm tới tai bắt hộp (z=−51.5), 24 mm tới chân màn hình.
  Cạnh `+Z` mang **header cái ra LED** (world x 12..29, z −61..−57, đỉnh chân
  y = 15.1) quay thẳng về hộp tối → đường TX ngắn nhất.
- Hàng chân 2× MCP4725 (world): **0x60 → IR** x −8.4..4.3, **0x61 → Đỏ**
  x 39.8..52.5, cùng z −107.5..−105.5, mặt trên module y = 16.3.
- **Lỗi mô hình dây đã sửa trong đợt này**: bó TX cũ chạy ở y=1.8 dọc x=−7 →
  **xuyên qua vách đặc của chụp che sáng**. Nay bó vòng ra ngoài đầu ống chụp
  (x=−21) rồi **chui lên đúng khe sàn** (x −18.5..−13, y 1..5) vào lòng ống;
  làn IR đi ở y=4.4 khi song song để không đè bó Đỏ (y=1.8). I2C + nguồn vẽ lại
  theo board driver không xoay (I2C 0x60 vòng phía trước board tại z=−114).
- Viewer: preset camera lật về `-Z` (`iso`, `Trước` nhìn thẳng mặt màn hình;
  `Khối điện tử` target z=−84; lưới sàn dời về z=−52).

---

## 0. CẬP NHẬT v3 (2026-09-02) — thanh trượt đẩy-kéo, chụp 4 trụ cắm, đế màn hình

Ghi đè mục 0-v2 và các mục cũ ở những chỗ đụng chạm. Trạng thái
`[VERIFIED]` **93/93 check** (`docs/system_3d/verify_geometry.py`; 15/15 STL
watertight, 12 cặp lắp ghép giao nhau = 0 mm³).

1. **Cơ cấu chỉnh d = thanh trụ tròn Ø5 h8 × 130 mm** (thép/inox `[SPEC]`, mua
   sẵn) gắn cứng vào lỗ mù Ø5.1 sâu 15 mm trên **lưng carrier**, song song trục
   D tại **y = 24**, xuyên vách `-X` qua **bệ dẫn hướng Ø10.4/lỗ Ø5.4 dài 21 mm**
   (ống nhô 18 mm + vách 3 mm). Đẩy/kéo **bằng tay** từ ngoài; **núm cầm Ø16×8**
   in 3D (`rod_knob_red.stl`) kẹp bằng vít lục giác chìm M3×6.
   **Phần thanh lộ ra ngoài mặt bệ = d (mm)** → đọc khoảng cách bằng thước kẹp.
   Kín sáng bằng **bẫy khe vành 0.20 mm × 21 mm ≈ 105:1** `[ASSUME]` — CHƯA đo
   bằng OPT101 ở khẩu độ `blank`; đây là phép đo bắt buộc ở Stage 6.
   **Bỏ toàn bộ nam châm N35, ray/chặn/thước khắc trên nắp → nắp là tấm phẳng.**
2. **Không va chạm** `[VERIFIED]`: thanh ở y=24 vs bó dây TX y≈1.8..9 (cách
   ≥15 mm), vs trục D y=16.75, vs hốc chân LED y≈29.2; đầu thanh x=112−d luôn
   **lùi sau chóp LED (x=120−d) 8 mm** nên không chắn quang. Máng dây sàn đã dời
   về **x ≥ 9** (sau 4 trụ đứng đỡ lỗ trụ cắm).
3. **Kết cấu KHOẺ HƠN, không yếu đi**: bệ là vật liệu ĐẮP THÊM (ống vách 2.5 mm)
   + bệ phẳng 2.0 mm nâng vách chỗ khoét từ 3.0 → 5.0 mm.
4. **Chụp che sáng: 4 trụ cắm Ø4 × 6.5 mm** (y = 5.0/13.5, z = tâm làn ±14.5)
   vào lỗ Ø4.30 (khe 0.15/mặt) — **bỏ 8 vít M3×8**. Kín sáng bằng **vòng mộng
   âm-dương khép kín** quanh lỗ cáp (gân 1.2 mm ↔ rãnh 1.5×1.5 mm, khe
   0.15/mặt), 4 trụ nằm NGOÀI vòng mộng (±14.5 vs ±13). Đáy lỗ tựa **trụ đứng
   liền khối trong hộp** (x=3..8, cao y=19.5) → lỗ không xuyên thủng vách.
5. **2 chân đỡ màn hình 7"** (`screen_foot_1.stl`, in 2) — *(vị trí đã đổi,
   xem §0 bố cục: nay ở **`base_neg`, z −190..−136**)*:
   x = 20/130, máng kẹp rộng 21 sâu 14 ngả **15°**,
   4 vít M3×12 xuống đế + 2 vít kẹp M3. `[SPEC]` panel Pi 7" 194×110×20 mm;
   `[ASSUME]` panel khác dày 15..21 mm. Không cản Pi (z −108..−52) hay quạt.
   In **đứng đúng tư thế lắp, không support** (mọi mặt hướng xuống ≤39°).
6. **Lưới lỗ M3 Ø3.4 dự phòng** trên `base_pos` — *(đã đổi: nay **3×2 lỗ,
   x 30/75/120, z 62/80**, xem §0 bố cục)*.
7. **STL: 15 file** `out/stl/` (bỏ `mag_slider_red.stl`; thêm `rod_knob_red.stl`,
   `screen_foot_1.stl`). Bambu **12 file** (`05_num_thanh_truot.stl` thay
   `05_can_truot_nam_cham.stl`). Thân in rộng 150 → **170 mm** ⇒ đã đổi thuật
   toán xếp bàn sang **MaxRects** (all-in-one 237×235 mm); thêm bước **dọn STL
   mồ côi** trong `export()` / `export_print_package()`.
8. **BOM mua thêm (v3)**: 2× thanh Ø5 h8 ×130 mm, 2× vít lục giác chìm M3×6,
   4× vít M3×16 (tai đế), 4× vít M3×12 (chân màn hình), 2× vít M3×16 (kẹp panel),
   *(tuỳ chọn)* 6× vít M3 + đai ốc (lưới mở rộng). **BỎ**: 4 nam châm N35,
   8 vít M3×8.
9. **Lỗi thật đã sửa trong đợt này**: gân kín sáng của chụp cấn vào đảo rãnh
   thân **13.1 mm³ mỗi bên** (đặt lệch dấu khe ở 2 mép trong) và chân màn hình
   cấn tai bắt hộp **98.5 mm³ mỗi chân**. Cả hai đều do check giao nhau bắt
   được — **luôn chạy `verify_geometry.py` trước khi in**.

---

## 0. CẬP NHẬT v2 (2026-08-30) — cơ cấu "cần trượt nam châm"

Ghi đè các mục cũ dưới đây ở những chỗ đụng chạm. Trạng thái mới `[VERIFIED]`
(69/69 check geometry pass — script trong repo `docs/system_3d/verify_geometry.py`,
đã chạy lại sau các fix review: deploy script, hằng số dùng chung, lid STL
không lật; 12 cặp giao nhau = 0 mm³, 14/14 STL watertight):

1. **Chỉnh d từ NGOÀI hộp**: carrier LED bỏ vít kẹp M3 (trượt tự do trên trục D); trên carrier có **cột nam châm** (tâm local x=−12, đỉnh y=63.5, khe 0.5 mm tới nóc) chứa nam châm Ø10×3 N35; trên nắp có **2 ray dẫn cần trượt** (x 8..101, ray ±7.5..9.5 quanh mỗi làn) + 2 chặn đầu (tâm cần x ∈ 17..92) + thước khắc d=15..90 (vạch to: Đỏ 25 / IR 85); **cần trượt** (mag_slider_red.stl, in 2) chứa nam châm thứ 2 — cộng hưởng xuyên nắp 2.2 mm (vùng recess). Tâm cần x = 107 − d. Hộp giữ kín sáng tuyệt đối (không thêm khe hở nào). [ASSUME] lực kéo nam châm ~3–6 N — chưa đo thật.
2. **Bỏ 2 cửa hatch + tấm phủ + build_hatch_cover()** — không còn cần mở nắp để chỉnh.
3. **Chụp che sáng (4 cái)**: lỗ vít M3 XUYÊN bích, vặn từ mặt ngoài (mồi Ø2.5 sâu 2.6 mm) — bản cũ (đang deploy trên web trước hôm nay) bịt kín mặt ngoài, đúng lỗi người dùng báo.
4. **Đế**: 5 mộng vuông (bỏ 2 lỗ vít vô dụng ở x=43/111 — vít dọc Y không bắt chéo được đường nối z=0).
5. **Khẩu độ**: khe 1.8→2.0 mm, tấm 1.6 căn giữa (0.2 mm/side).
6. **STL dedup: 14 file** out/stl/ (bỏ *_ir trùng lặp; in 2 bản từ file _red). Bambu package 12 file (05_can_truot_nam_cham.stl thay 05_tam_hatch.stl).
7. **BOM mua thêm**: 4× nam châm đĩa Ø10×3 N35, 8× vít M3×8 (chụp), 4× vít M3×16 (tai đế).
8. **gh-pages đã dọn**: trước đây chứa 4.711 file rác (.cad_venv vendored + __pycache__ + dataset); bản deploy mới = index.html + stl/ + print_bambu/ + README.md + .nojekyll.
9. **`chamber_3d/` đã xóa** (2026-08-31) — ngân sách quang học legacy chuyển vào README §2.1; lịch sử git vẫn giữ đầy đủ.

---

## 1. Yêu cầu gốc của người dùng

Dựng mô hình 3D **chân thực nhất có thể** cho toàn hệ PPG simulator:

- **Trong hộp tối**: LED Đỏ/IR gắn trên trục trượt; đối diện là board 5×7 cm
  mang 2 cảm biến OPT101.
- **Ngoài hộp**: Raspberry Pi 4 + Seeed Grove Base HAT + 2 module DAC MCP4725
  + board driver LED.

3 lựa chọn thiết kế đã được người dùng CHỐT:
1. 2 trục trượt riêng Ø8 mm + vách ngăn quang 3 mm (Đỏ d≈25 mm, IR d≈85 mm).
2. Board cảm biến 70 mm ngang (Z) × 50 mm cao (Y), 2 OPT101 đặt cạnh nhau.
3. Một đế chung: Pi+HAT một bên, driver perfboard + 2 MCP4725 bên kia.

**Yêu cầu đang xử lý (chưa xong)** — nguyên văn:
> "tại sao lại thiết kế hộp xấu thế? cải tiến lại cho hộp đẹp hơn, **dây phải
> đi theo bẹ chứ không phải đi rải rác thưa thớt**, đồng thời trên web tôi mở
> ra coi lại không được, chỉ là một màu đen và không có thấy gì hết. tiến hành
> sửa lại cho đúng yêu cầu thẩm mỹ"

→ 3 phần: (a) hộp đẹp hơn — **ĐÃ XONG**; (b) web đen — **ĐÃ XONG**;
(c) **dây đi theo bẹ — ĐÃ LÀM 2026-08-31** (xem §6).

---

## 2. Ảnh chụp trạng thái build v1 (LỊCH SỬ — toạ độ đế đã lỗi thời, xem §0 bố cục)

Chạy `.cad_venv/bin/python build_system.py` — **build sạch**:

- 15/15 part in được đều `watertight`: `body, lid, slide_shaft_red/ir,
  led_carrier_red/ir, frame, aperture_red_{blank,d2,d5,d16},
  hood_l_red, hood_r_red, base_neg, base_pos`.
- `out/model.json` 2.1 MB, `out/viewer.html` 4.0 MB.
- Server đang chạy: `python3 -m http.server 8000` (pid 1788411, bind
  127.0.0.1) trong `docs/system_3d`; `GET /viewer.html` → **HTTP 200,
  4 000 040 bytes**. Người dùng cần **hard-refresh** (Ctrl+Shift+R).

Kiểm tra giao cắt (thể tích giao, mm³) — tất cả = 0 (giá trị ~1e-13 là nhiễu số):

```
body x hood_l_red = 0      body x hood_r_red = 0
body x hood_l_ir  = 0      body x hood_r_ir  = 0
body x base_neg   = 0      body x base_pos   = 0
body x lid        = 0
hood_l_red x hood_l_ir = 0 hood_r_red x hood_r_ir = 0
```

Bounds thực tế:
```
body        -5.00   0.00 -51.50 → 155.00  64.00  51.50
lid          0.00  56.00 -40.00 → 150.00  67.00  40.00
base_neg   -24.00 -10.00-122.00 → 174.00   5.00   9.00
base_pos   -24.00 -10.00   0.00 → 174.00 122.00 ... (x,y,z: 174/5/122)
hood_l_red -21.50   3.00 -37.25 →  -5.00  24.00  -1.25
hood_r_red 155.00   3.00 -37.25 → 171.50  24.00  -1.25
hood_l_ir  -21.50   3.00   1.25 →  -5.00  24.00  37.25
hood_r_ir  155.00   3.00   1.25 → 171.50  24.00  37.25
```

`body.contains()` cho 8 điểm nằm trên tuyến cáp dự kiến — **toàn bộ False**
(tức là hành lang cáp thông, không bị bịt):
`(-2,11,±19.25)`, `(152,11,±19.25)`, `(-15,1.6,±19.25)`, `(165,1.6,19.25)`,
`(-15,1.6,60)`.

---

## 3. Môi trường & pipeline

- venv: `/home/huynn/final_project/PPG_simulator_raspi/.cad_venv/bin/python`
  — **luôn gọi bằng đường dẫn tuyệt đối** (cwd của shell hay bị lệch).
- trimesh 5.0.0 + manifold3d + numpy 2.5.2. **KHÔNG có scipy** → cấm dùng
  `fix_normals()`, `body_count`, `connected_components` (đều gọi scipy).
- `build_system.py` → `out/stl/*.stl` (đã xoay tư thế in) + `out/model.json`
  (đỉnh float32 / mặt uint32, base64) + `viewer.html` tự chứa
  (three.js **r147 UMD** + OrbitControls nhúng thẳng).
- three.js r147: dùng `THREE.sRGBEncoding`, `texture.encoding`,
  `renderer.outputEncoding`. **KHÔNG** dùng `SRGBColorSpace` (r152+) —
  đây chính là nguyên nhân màn hình đen trước đây.
- Part in được → CSG boolean thật. Part mua sẵn / chỉ để nhìn → gom mesh màu
  qua accumulator `Vis` (không boolean, rẻ tri-count).

---

## 4. Hệ toạ độ & hằng số chính `[VERIFIED — in ra từ module]`

**+X = trục quang (LED → board cảm biến), +Y = lên, +Z = ngang.**

| Nhóm | Giá trị |
|---|---|
| Hộp | `X0..X_TOT = 0..150`, `X_IN0..X_IN1 = 3..147`, `Y_FL = 3`, `Y_TOP = 64`, `Y_LID = 67`, `Z0..Z1 = −40..40`, `Z_IN0..Z_IN1 = −37..37`, `WALL = 3` |
| Làn quang | `LANE_Z = {red: −19.25, ir: +19.25}`, vách ngăn `SEPT_HW = 1.5` tại z=0, `Y_AX = 32` |
| Trục trượt | `SH_Y = 14`, `SH_R = 4` (Ø8, vát D), `SH_X0..SH_X1 = 1..111` |
| Carrier LED | `CAR_L = 22`, `CAR_ZW = 18`, `CAR_Y0..Y1 = 5..40`; mặt trước `x_front(ir)=34`, `x_front(red)=94` → **mặt sau carrier x = 12 (IR) / 72 (Đỏ)** |
| Khoảng cách | `D_DEFAULT = {red: 25, ir: 85}`, `X_WIN = 120` (mặt cửa sổ OPT101), `LED_TIP_OUT = 1` |
| OPT101 / board | `X_MOD0..X_MOD1 = 124.3..125.5`, `X_BF = 137.5`, `X_BR = 139.1` (board 1.6 mm), `FRM_X0..FRM_X1 = 137.5..141.5`, `BRD_Y0..Y1 = 7..57`, `BRD_Z0..Z1 = −35..35` |
| Cổng cáp trên vách | `EX_Y0..EX_Y1 = 6..16`, `EX_ZW = 20` → lỗ x −5.5..3.5 (−X) và 146.5..155.5 (+X), z = làn ±10 |
| Bệ bắt chụp | `PAD_T = 5`, `PAD_HW = 18` → khối đặc x −5..0 và 150..155, y 0..24, z làn ±18 |
| Chụp che sáng | `HOOD_Y0..Y1 = 3..24`, `HOOD_T = 2.5`, `HOOD_D = 10`; local a0=5, a1=9, a2=21.5; `HW = 18` |
| Khe cáp sàn chụp | `HOOD_SLOT_L = 7`, `HOOD_SLOT_HW = 6` → local x 12..19, y 2.5..6.0, z làn ±6 → **world x −19..−12 (−X), 162..169 (+X)** |
| Vít giữ chụp | `HOOD_BOLT_Y = (5.5, 21.0)`, `HOOD_BOLT_Z = (−14.5, 14.5)` |
| Máng cáp sàn hộp | `zw = ±33`, cắt `box(4, 104, 1.6, 3.05, zw±3)` → rộng 6 mm, sâu 1.4 mm |
| Đế | `BASE_T = 4` (mặt trên y=0), `BASE_X0..X1 = −24..174`, `BASE_Z0..Z1 = −196..92`, `RIB_H = 6` |
| Pi 4 | `PI_X0 = 62`, `PI_Z0 = −108`, PCB 85×56×1.4, `PI_Y0..Y1 = 5..6.4` |
| Grove HAT | 65×56.5×1.6, `HAT_Y0..Y1 = 14.9..16.5`, `HDR_H = 8.5` |
| Driver perfboard | `DRV_L/W/T = 70/55/1.6`, `DRV_WX/WZ = −12/−112` (**không xoay**), `DRV_Y0..Y1 = 5..6.6` → x −12..58, z −112..−57 |
| MCP4725 | `DAC_L/W = 17.8/15.2`, `DAC_HDR_H = 8.5`; header 0x60 (IR) x −8.4..4.3; 0x61 (Đỏ) x 39.8..52.5; cùng z −107.5..−105.5 |

**Điểm nối đã xác minh (cần giữ nguyên khi vẽ dây):**

```
Header cái ra LED trên driver (cạnh +Z, quay về hộp tối):
    world x = 12..29, z = −61..−57 (hàng chân z ≈ −59), đỉnh chân y = 15.1
Socket Grove (miệng cắm):
    A0 (IR RX)  = (71.5, 19.9, −57.5)
    A2 (Đỏ RX)  = (84.5, 19.9, −57.5)
    I2C1        = (74.0, 19.9, −80.0)
    I2C2        = (89.0, 19.9, −80.0)
Cửa luồn dây trên frame: x 139.3..141.7, y 12..52, z |4..32| theo làn
Khe dây lên máng trên frame: z = làn ±3.5, y 56..60.2
```

---

## 5. Đã sửa xong (phiên trước + đã kiểm chứng lại hôm nay)

### 5.1 Web viewer đen — ĐÃ SỬA
Nguyên nhân: dùng API three.js r152+ (`SRGBColorSpace`) trên bản r147.
Đã đổi về `sRGBEncoding` / `outputEncoding`. Viewer trả HTTP 200, 4.0 MB.

### 5.2 Thẩm mỹ hộp — ĐÃ SỬA
Thêm primitive CSG mới (do không có shapely/scipy):
- `prism(axis, pts, a0, a1)` — lăng trụ lồi từ đa giác 2D; **tự kiểm thể tích
  có dấu bằng numpy rồi lật chiều quấn mặt** (thay cho `fix_normals()`).
- `chamfer_v()`, `chamfer_box_v()`, `chamfer_edge_top(..., out=False)` —
  dao cắt vát 45°; `out=True` lật chân vát ra ngoài để vát viền hốc âm.

Áp dụng:
- Thân hộp: vát 4 góc đứng `BODY_CHAM = 2.5` (dừng ở y = 57, **nằm ngoài vùng
  rãnh labyrinth** nên không ảnh hưởng kín sáng), chỉ bóng ngang y 46..48.5
  sâu 0.8 mm, vát vành mép trên 1.0 mm.
- Nắp: **bỏ 3 gân nổi cũ (xấu + vướng)**, thay bằng panel giữa thụt 0.8 mm +
  2 cụm rãnh cầm tay ÂM + vát vành mép 1.5 mm.
- Chụp che sáng: vát góc đứng + vành mép `HOOD_CHAM = 2.0`.
- Đế: vát 2 góc ngoài mỗi nửa `BASE_CHAM = 8.0` (mép z=0 để vuông vì là mặt ghép).
- Bệ bắt chụp `PAD_*` bo góc `PAD_CHAM = 2.0`.

### 5.3 Lỗi NGHIÊM TRỌNG đã sửa
| Lỗi | Hậu quả trước khi sửa | Cách sửa |
|---|---|---|
| 4 chụp che sáng **không được dời vị trí** | nằm ở z −18..18 thay vì ±19.25; `hood_r_*` chui vào **trong** hộp (x 5..21.5), cắt vách ngăn quang 345 mm³, 2 trục trượt 220.9 mm³/cái, carrier IR 589.2 mm³ | thêm `apply_transform(translation_matrix([0 hoặc X_TOT, 0, LANE_Z[ch]]))` trong `collect_parts()` |
| Bệ bắt chụp **bịt kín cổng cáp** | pad được `uni` SAU khi `dif(m, cuts)` → lấp lỗ cổng; `contains()` trả True tại (−2,11,±19.25) | chuyển lệnh cắt cổng từ `cuts` sang `holes` (cắt cuối cùng), x trải hết bề dày pad |
| Hộp **không đứng phẳng** | pad thụt xuống y = −1 → giao đế 369.3 / 334.6 mm³ | pad bắt đầu từ `Y0 = 0` |
| Lỗ vít giữ chụp **nửa nằm ngoài chụp** | hàng vít dưới ở y 2.5 trong khi chụp bắt đầu y = 3 | định nghĩa `HOOD_BOLT_Y = (5.5, 21.0)` / `HOOD_BOLT_Z` dùng chung cho `build_body()` và `build_hood()` |
| Cửa cáp trên mặt ngoài chụp | có đường nhìn thẳng gần như trực tiếp tới lỗ vách | đổi thành **khe ở SÀN chụp** → ánh sáng phải ngoặt 90° hai lần |
| Chụp che sáng bịt kín mặt ngoài (lỗi bản deployed) | không vặn vít được từ ngoài | lỗ vít xuyên bích + mồi sâu 2.6 (v2, [VERIFIED]) |

---

## 6. VIỆC CHÍNH CÒN LẠI — vẽ lại bó dây "đi theo bẹ"

> ✅ **ĐÃ LÀM 2026-08-31** — đã hiện thực trong `build_system.py`
> (`wires_vis()` + `harness()`: bẹ nhiều sợi song song + dây rút định kỳ),
> tọa độ đã suy ra lại theo hình học v2 (khe sàn chụp −16..−10.5 /
> 160.5..166.5; board driver ở −Z). Chi tiết: README §2.1 và docstring
> `wires_vis`.

`wires_vis()` ở **`build_system.py:1012`** vẫn là bản CŨ: các polyline viết tay
rời rạc (TX 2 sợi r=0.55/kênh; RX 3 sợi r=0.35/làn; Grove r=1.1; I2C r=0.8).
Đây chính là cái người dùng chê "rải rác thưa thớt".

### 6.1 Nguyên tắc thiết kế đã chốt (phân tích xong, **chưa code**)

**Tách 2 miền theo §9 của `docs/hardware/PPG_PROTOTYPE_SCHEMATIC.md`:**
- **Hành lang −X** (x ≈ −19..−10, y < 3, dưới gầm 2 chụp trái) = **miền dòng
  LED**: bẹ TX + bẹ nguồn. Toàn bộ dây có dòng LED 20 mA điều chế đi ở đây.
- **Hành lang +X** (x ≈ 156..174, y < 3, dưới gầm 2 chụp phải) = **miền tín
  hiệu**: 2 cáp Grove RX + 2 cáp Grove I2C.

Đây vừa là bố trí đẹp (2 bẹ song song, gọn) vừa đúng yêu cầu tách đường về
GND của dòng LED khỏi đường về tín hiệu.

**Kiểm chứng hình học đã làm `[VERIFIED]`:** gầm chụp y 0..3 thông suốt
(chụp bắt đầu ở y = 3, mặt đế y = 0); dải x trống bên −X là −24..−5 (19 mm),
bên +X là 155..174 (19 mm). `body.contains()` = False tại các điểm thử.

### 6.2 Cấu trúc bẹ trục −X (thân bẹ thu nhỏ dần — dáng loom thật)

Tâm bẹ `TRK_X = −14.0`, `TRK_Y = 1.6`, bước sợi `1.6 mm`, 6 sợi:

| slot a | x | sợi |
|---|---|---|
| −2.5 | −18.0 | IR anode (đỏ) |
| −1.5 | −16.4 | IR cathode (đen) |
| −0.5 | −14.8 | Đỏ anode (đỏ) |
| +0.5 | −13.2 | Đỏ cathode (đen) |
| +1.5 | −11.6 | 5V0 (đỏ, r = 0.7) |
| +2.5 | −10.0 | GND đường về dòng LED (đen, r = 0.7) |

Các trạm dọc z (bẹ dày lên rồi mỏng dần):
```
z = 110      : nguồn nhập bẹ (từ cầu đấu 3 vị trí x 34..42, z 110)
z = 100      : cặp Đỏ nhập  (từ cầu đấu z 97.46/102.54)
z = 62       : cặp IR nhập  (từ cầu đấu z 59.46/64.54)
z = 19.25    : cặp IR tách ra, dựng lên qua khe sàn chụp IR trái
z = −19.25   : cặp Đỏ tách ra, dựng lên qua khe sàn chụp Đỏ trái
z → −47      : còn 2 sợi nguồn, bo cua rồi chạy +x tới Pi
```

**Kiểm tra lọt khe sàn chụp `[VERIFIED]`** (khe world x −19..−12, bán kính sợi
0.55):

| nhánh | bao ngoài bó | lọt khe? |
|---|---|---|
| IR (slot −2.5, −1.5) | −18.55 .. −15.85 | ✅ |
| Đỏ (slot −0.5, +0.5) | −15.35 .. −12.65 | ✅ |
| nguồn (slot +1.5, +2.5) | không lên chụp, chạy tiếp trên đế | — |

Lưu ý: nếu chọn `TRK_X = −14.5` thì bao ngoài nhánh IR = −19.05, **vượt mép
khe 0.05 mm** → phải dùng −14.0 như trên (hoặc tăng `HOOD_SLOT_L` 7.0 → 9.0).

Trong hộp (sau khi qua cổng vách x −5.5..3.5, y 6..16):
cặp dây hạ xuống **máng sàn z = ±33** (y ≈ 2.2, máng rộng 6 sâu 1.4) → chạy
+x → leo lên **hốc sau carrier** tại (12, 32, 19.25±1.27) cho IR và
(72, 32, −19.25±1.27) cho Đỏ. **Phải để vòng dự trữ (service loop)** vì
carrier trượt để đổi d.

### 6.3 Hành lang +X — 4 cáp Grove dẹt (đúng nghĩa "bẹ")

Cáp Grove = **cáp dẹt 4 lõi, bước 2.0 mm (JST PH)** → tự thân đã là bẹ.
Màu chuẩn Grove: **vàng / trắng / đỏ / đen**.

- **RX**: OPT101 → cầu đấu board 5×7 → qua cửa luồn dây frame → cổng vách +X
  (x 146.5..155.5, y 6..16) → lòng chụp phải → **rơi xuống qua khe sàn
  x 162..169** → chạy −z → tới A0 (IR) và A2 (Đỏ).
  Miệng socket A0/A2 quay về **+z** (z ≈ −51.7) → cáp tiếp cận từ phía hộp.
  Gán làn: RX cặp xếp chồng 2 lớp, tâm x ≈ 161.5, y 1.35 (dày 2.5 mm < 3 mm
  gầm chụp).
- **I2C**: I2C1/I2C2 → chạy +z men theo mép HAT → xuống đế → chạy +x tới
  x ≈ 169.5 → chạy +z **dưới gầm 2 chụp phải** → rẽ −x vào header MCP4725
  0x60 (z ≈ 49.3) và 0x61 (z ≈ 102.5).
  Màu: vàng = SCL, trắng = SDA, đỏ = VCC 3V3, đen = GND.

**Lưu ý topo điện (khớp schematic §1/§7):** MCP4725 lấy 3V3 + GND từ cáp Grove
I2C; OPT101 lấy 3V3 + GND từ cáp Grove A0/A2. Do đó **board driver chỉ cần
5V0 + GND** (2/3 vị trí của cầu đấu nguồn) → đúng luật "chỉ LM358P pin 8 và 2
anode LED được nối 5V0", và đường về dòng LED đi riêng một sợi.

**Điểm lấy nguồn trên Pi**: `[ASSUME]` — schematic KHÔNG chỉ định điểm đấu vật
lý. Header GPIO 40 chân đã bị HAT chiếm; thực tế phải dùng header xếp chồng
hoặc breakout. Trong mô hình sẽ vẽ dây lên mép header GPIO tại
(x ≈ 70, y ≈ 12, z ≈ −53) và **ghi rõ nhãn `[ASSUME]` trong docstring**.

### 6.4 Hàm cần viết mới

```python
def _ribbon_frames(P):
    """Khung 'bẹ': u ⟂ hướng đi và LUÔN NẰM NGANG ở đoạn ngang; ở đoạn thẳng
    đứng u được NỘI SUY giữa 2 đầu -> bẹ xoắn mềm 90° như cáp dẹt thật."""
    # u_i = cross(T_i, [0,1,0]); |u| < 0.25 -> đánh dấu invalid, nội suy tuyến
    # tính giữa 2 u hợp lệ bao quanh, rồi trực giao hoá với T và chuẩn hoá.
    # w = cross(u, T)   (≈ thẳng đứng ở đoạn ngang -> dùng để xếp lớp)

def bundle(v, path, wires, pitch=2.0, n=8):
    """wires: list (màu, a, b[, r]); a = vị trí ngang (đơn vị pitch),
    b = vị trí lớp (đơn vị 1.25 mm). Mọi sợi dùng CHUNG một đường tâm."""

def cable_tie(v, x, y, z, along, hw, hh, ...):
    """Đai rút quấn quanh bẹ — ghép 4 hộp mỏng, KHÔNG dùng CSG cho rẻ."""
```

**Lý do phải tự nội suy khung**: parallel-transport thuần sẽ làm bẹ dựng
đứng sau khúc cua xuống-rồi-rẽ-ngang (đã phân tích: u bị xoay thành [0,−1,0]),
bẹ 7 mm dựng đứng thì **không lọt gầm chụp 3 mm**.

### 6.5 Kẹp cáp in liền đế (cần thêm vào `build_base()`)

```python
def cable_clip(xa, xb, zc, h=3.4, t=1.6, w=3.0):
    """Cầu vòm giữ bẹ cáp áp mặt đế. Nhịp ~13 mm, in bridging được, không support."""
    return dif(box(xa - t, xb + t, 0.0, h + t, zc - w/2, zc + w/2),
               [box(xa, xb, -0.5, h, zc - w/2 - 0.5, zc + w/2 + 0.5)])
```
Vị trí đề xuất (tránh gầm chụp — chụp chiếm z 1.25..37.25 và −37.25..−1.25):
- −X: z = 45, 70, 95 (base_pos); z = −44 (base_neg); và trên đoạn chạy +x tại
  z ≈ −47 thì đặt theo x = 5, 30, 55.
- +X: z = 45, 75, 100 và z = −45.

Bó dây đặt ở y 1.05..2.15 → lọt dưới vòm cao 3.4 mm.

---

## 7. Tồn đọng khác (cập nhật 2026-08-31)

1. ✅ **ĐÃ SỬA 2026-08-31** — Dây RX xuyên qua board 5×7: cầu đấu 3 chân + tụ
   100 nF đã dời ra **mặt sau board** (cầu đấu x `X_BR..X_BR+5.2`, vít quay +x;
   tụ x `X_BR..X_BR+3.5`); dây RX được vẽ lại: vượt qua miệng board trên khe
   dây lên máng (y 56..60.2), chạm cầu đấu mặt sau, rồi chạy xuống kênh sau
   khung (x 141.5..147) ra chụp +X. Visual-only, không ảnh hưởng STL in.
2. ✅ **ĐÃ SỬA 2026-08-31** — "622 nm" đã gắn nhãn `[ASSUME]` tại
   `build_system.py` (label LED Đỏ) và `README.md` (đầu trang + sơ đồ khối,
   có chú thích *) — BOM không ghi bước sóng LED Đỏ.
3. ✅ **ĐÃ SỬA** — README ghi đúng kích thước đế; sau đợt đổi bố cục
   (2026-09-02, §0) là **198×196 (base_neg, nửa trước) / 198×92 (base_pos,
   nửa sau)**.
4. ✅ **ĐÃ SỬA 2026-08-31** — `led_red`/`led_ir` đã bỏ khỏi
   `assets/textures.json` (-220 KB). Lưu ý thêm: hiện **toàn bộ** texture đều
   chưa được nối vào model (Vis hỗ trợ `tex=` nhưng chưa nơi nào gọi với tex)
   — nếu muốn PCB có ảnh thật cần viết bước nạp `textures.json` vào
   `model.json`/viewer.
5. ✅ **ĐÃ SỬA 2026-08-31** — nhãn console: phát hiện `_ir` bằng
   `"_ir" in name` (trước đây `endswith("_ir")` bỏ sót `aperture_ir_*`);
   mọi bản dedup đều in đúng "dùng chung file bản _red, in 2 bản".
6. ⬜ **`render_preview.py`** cho ra 4 ảnh PNG gần như vô dụng về mặt thị giác
   → hoặc làm lại cho đọc được, hoặc giảm vai trò vì viewer đã chạy. (Còn lại
   — mức ưu tiên thấp, không chặn deploy.)

---

## 8. Ràng buộc bắt buộc khi làm tiếp

- **Không có scipy** → tuyệt đối tránh `fix_normals()`, `body_count`,
  `connected_components`.
- Gọi Python bằng **đường dẫn tuyệt đối** tới `.cad_venv/bin/python`.
- three.js **r147** — không dùng API r152+.
- Sau MỌI thay đổi hình học: chạy lại build và **kiểm tra `watertight` +
  thể tích giao giữa các part** (script mẫu đã dùng: dựng part, in bounds,
  `trimesh.boolean.intersection`, `mesh.contains(points)`).
- Theo `CLAUDE.md`: tách bạch `[VERIFIED]` / `[DS]` / `[SPEC]` / `[ASSUME]`;
  **không bịa** số đo, kết quả build hay kết quả kiểm tra phần cứng.
- Mọi toạ độ đặt linh kiện trên driver board, vị trí socket Grove, số chân
  header module OPT101/MCP4725 hiện là `[ASSUME]` — **phải đo lại trên vật
  thật** trước khi dùng để gia công.
