# PPG Simulator — Mô hình 3D toàn hệ thống (Raspberry Pi)

> Mô hình 3D **toàn bộ hệ thống** PPG Simulator: hộp tối quang 2 làn (Red 622 nm
> [ASSUME] / IR 875 nm → 2× OPT101) + board cảm biến 5×7 cm + đế chung mang Pi 4, Grove HAT,
> board driver LED, 2× MCP4725 và **đế đỡ màn hình cảm ứng 7 inch**.
> Khoảng cách LED→cảm biến chỉnh từ ngoài bằng **thanh trượt đẩy-kéo Ø5**
> (v3 — thay cơ cấu nam châm). Sinh bằng script tham số `build_system.py`
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

> **-Z là MẶT TRƯỚC** (phía người dùng ngồi). Thứ tự trước → sau trên đế chung:
> **màn hình 7"** (z −190..−136) → **Pi 4 + board driver** (z −112..−52) →
> **hộp tối** (z −40..+40, tai bắt vươn tới ±51.5) → **vùng lỗ mở rộng**
> (z 62..80). Màn hình ngả 15° ra sau, mặt hiển thị quay về `-Z` → nhìn và
> chạm được ngay, không bị hộp tối che.

- Kích thước hộp tối: **150 × 67 × 80 mm** (X×Y×Z, gồm nắp).
- Trục quang tại y=32 mm; tâm 2 làn tại z = ±19.25 mm.
- Đế chung: **198 × 288 mm** (x −24..174, z −196..92), chia đôi tại z=0 —
  nửa `-Z` **198 × 196 mm**, nửa `+Z` **198 × 92 mm** (cả hai vừa bàn in
  256×256). **Nửa `-Z` là nửa TRƯỚC**: 2 chân đỡ màn hình 7 inch (§4.3) ở hàng
  đầu, rồi board driver + Pi 4 + Grove HAT + 2× MCP4725. Nửa `+Z` là nửa SAU:
  đỡ hộp tối và mang lưới lỗ mở rộng (§4.4).
- **Không gian thao tác**: thanh trượt Ø5 thò ra phía `-X`; ở d=90 mm đuôi núm
  tới **x = −110 mm**, tức cần chừa **≥ 86 mm bàn trống** ngoài mép đế (đế kết
  thúc ở x=−24).
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
0.19 V (gần như không điều khiển được). Đây là lý do hành trình trượt phải phủ
15–90 mm.

> **v3 (2026-09-02) — ngân sách quang học KHÔNG đổi.** Việc thay cần trượt nam
> châm bằng thanh trượt đẩy-kéo chỉ đổi *cách* dịch carrier, không đổi bước
> sóng, góc mở LED, dải d, vị trí cửa sổ OPT101 hay tấm khẩu độ. Các bảng trên
> giữ nguyên. Thông số **thiết kế cơ khí** thay đổi được liệt kê ở §4 và §12.
> Điểm mới đáng dùng: **chiều dài thanh lộ ra ngoài bệ = d (mm)** — đo bằng
> thước kẹp là biết ngay khoảng cách quang, không cần thước khắc trên nắp.

> ⚠ Giá trị Rv 0.35/0.49 V/µW là ước lượng đồ thị từ datasheet (chỉ 0.45 A/W
> @650 nm được ghi rõ). Trước khi chốt hiệu chuẩn nên đo thực tế ở Stage 6.

> Nguồn: `chamber_3d/README.md` §4 — thư mục legacy đã bị xóa khỏi source
> tree (lịch sử git vẫn giữ đầy đủ). Lưu ý: dải d 15–85 mm của bản legacy
> đã mở thành **15–90 mm** trong v2 (`D_MIN, D_MAX = 15.0, 90.0` trong
> `build_system.py`).

Bố trí tổng thể theo X:

| x (mm) | Thành phần |
|---|---|
| −110..−18 | Thanh trượt Ø5 lộ ra ngoài + núm cầm Ø16 (ở d=90; phần lộ = d) |
| −18..0 | Bệ dẫn hướng thanh trượt (lỗ Ø5.4 dài 21 mm kể cả vách 3 mm) |
| 0..111 | Lòng hộp tối (2 làn, vách ngăn liền khối 3 mm tại z=0) |
| 1..111 | Trục trượt D-shaft Ø8 (mỗi làn) |
| 113..115 | Rãnh trượt tấm khẩu độ |
| 120 | Mặt cửa sổ OPT101 (= mốc đo d) |
| 124.3..125.5 | Module OPT101 PDIP-8 + PCB nhỏ |
| 137.5..139.1 | Board cảm biến 5×7 cm dựng đứng |
| 141.5..147 | Vách ngăn sau khung board |
| -24..174 | Đế chung (Pi 4 + Grove HAT + driver + 2× MCP4725) |

Bố trí tổng thể theo Z (**-Z = trước, +Z = sau**):

| z (mm) | Thành phần |
|---|---|
| −196 | Mép trước đế chung (`base_neg`) |
| −190..−136 | 2 chân đỡ màn hình 7 inch (x = 20 và 130) |
| −175.7..−127.9 | Panel màn hình 7 inch, ngả 15°, mặt hiển thị quay về -Z |
| −136..−112 | Khe thao tác cổng USB-C / HDMI của Pi (24 mm) |
| −112..−57 | Board driver LED 70×55 (x −12..58, không xoay) |
| −110..−51.5 | Pi 4B + Grove HAT kể cả connector (PCB z −108..−52, x 62..147) |
| −106.5 | Hàng chân 2× MCP4725 trên board driver |
| −51.5..+51.5 | 4 tai bắt hộp tối xuống đế (x = 21 và 129) |
| −40..+40 | Hộp tối (làn Đỏ z = −19.25, làn IR z = +19.25) |
| +62 / +80 | Lưới 3×2 lỗ M3 dự phòng mở rộng (§4.4) |
| +92 | Mép sau đế chung (`base_pos`) |

---

## 3. Cơ chế chống rò sáng (light-tightness)

1. **Tường 3 mm đặc** — LED đặt trong, trên carrier trượt, không khoan xuyên tường.
2. **Vách ngăn 3 mm** liền khối giữa 2 làn Đỏ/IR — cách ly quang tuyệt đối
   (OPT101 nhạy toàn dải 300–1100 nm nên 2 làn phải tách hẳn).
3. **Nắp labyrinth** — rãnh khóa ngoằn ngoèo trên đỉnh thành + môi nắp khớp khuôn.
4. **Chụp che sáng (hood)** trước mỗi lỗ ra cáp — ánh sáng phải quay 90° hai lần
   mới tới lỗ vách. **Khớp 4 trụ cắm Ø4** (không còn vít): 4 trụ liền khối trên
   chụp cắm vào 4 lỗ Ø4.30 trên bệ vách (khe 0.15 mm/mặt — ép nhẹ bằng tay, rút
   ra được, không tự rơi). Quanh lỗ cáp còn **vòng mộng âm-dương kín** (gân
   1.2 mm trên chụp ↔ rãnh 1.5 × 1.5 mm trên bệ vách, khe 0.15 mm mỗi mặt): một
   vòng khép kín bao trọn lỗ cáp nên không tồn tại đường sáng thẳng nào; 4 trụ
   cắm nằm NGOÀI vòng mộng (z = ±14.5 so với vòng ±13) → khoan lỗ trụ không cắt
   qua vòng kín.
5. **Tấm khẩu độ** trượt trong rãnh sàn tại x=113..115, ngay trước sensor:
   `blank` (bịt — đo nền tối), `d2` (Ø2), `d5` (Ø5), `d16` (Ø16).
6. **Khung giữ board 5×7** bịt kín tiết diện lòng hộp, mang bản vách ngăn nối tiếp
   phía sau; dây đi qua cửa luồn có chủ đích (không để hở đường sáng).
7. **Bẫy sáng khe vành của thanh trượt** — lỗ duy nhất mới mở trên hộp là lỗ
   tròn Ø5.4 cho thanh Ø5. Khe hướng kính chỉ **0.20 mm** nhưng dài **21 mm**
   (bệ dẫn hướng 18 mm nhô ra ngoài + vách 3 mm) → tỉ lệ **≈105:1**. Ánh sáng
   muốn vào phải phản xạ nhiều lần trong ống hẹp nhựa đen mờ; đây là bẫy sáng
   khe vành tiêu chuẩn, hiệu quả hơn hẳn một lỗ khoan xuyên vách 3 mm.
   Bệ được **đắp thêm vật liệu chứ không khoét vào vách**: ống Ø10.4 (vách
   2.5 mm quanh lỗ) mọc ra ngoài, cộng bệ phẳng dày 2.0 mm nâng vách chỗ đục
   lỗ cáp từ 3.0 → 5.0 mm ⇒ **kết cấu hộp khoẻ hơn bản v2**, không yếu đi.

---

## 4. Cơ cấu điều chỉnh khoảng cách — thanh trượt đẩy-kéo Ø5

### 4.1 Thanh trượt (thay hoàn toàn cần trượt nam châm)

- **Trục trượt D-shaft Ø8** mỗi làn (x=1..111) giữ nguyên: vát phẳng chống xoay,
  dải d=15..90 mm. **Carrier LED** (22×18 mm) vẫn ôm trục bằng lỗ D và trượt tự do.
- **Thanh trụ tròn Ø5 × 130 mm** gắn cứng vào **mặt lưng carrier**, **song song
  trục D** (cùng phương X, cùng làn, tâm tại y=24 mm): đầu trước cắm sâu
  **15 mm** vào lỗ mù trên lưng carrier (còn 7 mm vật liệu đặc phía trước lỗ),
  đuôi thò ra ngoài thành `-X`. Người dùng **đẩy/kéo trực tiếp bằng tay** →
  carrier chạy dọc trục D. Không mở nắp, không nam châm, không lực kéo phụ thuộc
  từ trường.
- **Vật liệu & dung sai thanh** — `[SPEC]` **thanh trụ tròn Ø5 h8, thép hoặc
  inox 304, dài 130 mm, mua sẵn** (loại dùng làm trục dẫn hướng máy in 3D /
  linear shaft Ø5). *Không khuyến nghị in nhựa*: thanh dài 130 mm in FDM sẽ
  cong theo lớp và mòn nhanh ở lỗ dẫn hướng. Nếu buộc phải in: dựng đứng theo Z,
  infill 100%, và chấp nhận sai số Ø ±0.3 mm → phải doa lại lỗ bệ.
- **Bệ dẫn hướng** trên vách `-X`: ống ngoài Ø10.4 (vách 2.5 mm) dài 18 mm nhô ra
  ngoài + 3 mm vách = **lỗ dẫn hướng Ø5.4 dài 21 mm**. Khe hướng kính 0.20 mm →
  trượt nhẹ tay nhưng **kín sáng** (bẫy sáng khe vành ≈105:1 — §3 mục 7).
  Tiết diện ống là **giọt nước ngược** (nửa trên tròn, đáy chụm 45° tại y=18.8)
  → in ngang không cần support.
- **Núm cầm Ø16 × 8 mm** (in 3D, 6 rãnh chống trượt tay) ở đuôi thanh: lỗ mù
  Ø5.1 sâu 6 mm + **1 vít lục giác chìm M3 xuyên ngang** (lỗ Ø2.6, ta-rô trực
  tiếp vào nhựa) kẹp chặt vào thanh — tháo được để rút thanh ra khi bảo trì.
- **Đọc khoảng cách không cần thước khắc**: chiều dài thanh **lộ ra ngoài mặt bệ
  (x = −18)** đúng bằng **d tính bằng mm** (chọn `ROD_LEN = 130` để có quan hệ
  này). Ví dụ d=25 → thò ra 25 mm; d=85 → thò ra 85 mm. Đo bằng thước kẹp là
  biết ngay, không phải tin vào vạch khắc.

**Vì sao thanh đi ra phía `-X`, không phải `+X`** — phía `+X` bị chặn hoàn toàn:
khe khẩu độ (x=113.2..115.2), OPT101 (x=120), khung board (x=137.5..141.5).
Phía `-X` chỉ có thành hộp.

**Kiểm tra va chạm (đã verify trên STL, xem §9)**

| Đối tượng | Vị trí | Kết luận |
|---|---|---|
| Bó dây TX (LED) | y ≈ 1.8..9 mm, sát sàn | Thanh ở **y=24** — cách ≥ 15 mm |
| Máng dây sàn | x ≥ 9 (lùi ra sau trụ trụ cắm chụp) | Không cắt qua bệ thanh |
| Chùm sáng LED | chóp LED tại x = 120 − d | Đầu thanh tại x = 112 − d ⇒ **luôn lùi sau chóp LED ≥ 8 mm**, không chắn quang |
| Cửa sổ OPT101 | x = 120, y=32 | Thanh dừng ở x ≤ 97 (d=15) |
| Trục D-shaft | y = 16.75 (mặt vát) | Thanh y=24 — nằm giữa mặt vát và hốc chân LED (y≈29.2) |
| Lỗ ra cáp / chụp | y = 5.5..13.5 | Bệ thanh ở y = 18.8..29.2 — tách hẳn |
| `body × led_carrier`, `body × slide_shaft`, `led_carrier × slide_shaft` | — | thể tích giao = 0 (verify_geometry §9) |

### 4.2 Khớp chụp che sáng — 4 trụ cắm (bỏ vít M3)

- 4 trụ **Ø4.0 × 6.5 mm** liền khối trên bích chụp, đặt tại **y = 5.0 / 13.5**
  và **z = tâm làn ± 14.5** — 4 góc, **ngoài** vòng mộng kín sáng (±13).
- 4 lỗ **Ø4.30** trên bệ vách (khe 0.15 mm/mặt): ép vào bằng tay, **giữ chắc
  không tự rơi**, rút ra được không cần dụng cụ.
- Đáy mỗi lỗ tựa lên **trụ đứng liền khối trong lòng hộp** (x=3..8, cao tới
  y=19.5) → lỗ không xuyên thủng thành, và bích chụp có mặt tì cứng.
- Kín sáng do **vòng mộng âm-dương khép kín** (§3 mục 4) chứ không do lực vít —
  tháo lắp nhiều lần không làm hỏng ren nhựa như bản v2.

### 4.3 Đế đỡ màn hình cảm ứng 7 inch

- **2 chân đỡ rời** (`screen_foot_1.stl`, in 2 bản) đặt ở **hàng đầu của nửa
  đế `-Z`**: x = 20 và 130 (cách nhau 110 mm, đối xứng qua trục hộp x=75),
  z = −190..−136 — tức **trước Pi 4 và trước hộp tối**, đúng thứ tự
  màn hình → Pi → hộp. Mép sau chân cách mép trước board driver (z=−112)
  **24 mm** → còn khe cắm USB-C/HDMI cho Pi; cách hộp tối > 95 mm
  (verify: `body × screen_foot_1` = 0 mm³, `base_* × screen_foot_1` = 0 mm³).
- Mỗi chân: **máng kẹp rộng 21 mm, sâu 14 mm, ngả 15°** so với phương thẳng
  đứng; cạnh dưới panel tì vào đáy máng ở y=8 mm.
- `[SPEC]` **Raspberry Pi 7" Touch Display: 194 × 110 × 20 mm** (kể cả bo mạch
  sau). Máng 21 mm nhận panel dày 20 mm với khe 0.5 mm mỗi bên. `[ASSUME]` các
  panel 7" phổ thông khác dày ~15..21 mm cũng kẹp được nhờ **vít kẹp M3 xuyên
  thành sau máng** (thành dày ≥ 10 mm, ta-rô vào nhựa) — **không phụ thuộc toạ
  độ lỗ bắt VESA của panel**, vì mỗi hãng một kiểu.
- Bắt xuống đế: **2 vít M3×12 mỗi chân** (tổng 4) — lỗ suốt Ø3.5 trên chân,
  **ta-rô trực tiếp** vào lỗ mồi Ø2.8 sâu 10 mm của `base_neg` (đế 4 mm + bệ trụ
  Ø9.2 đúc liền trong hốc gân, 6 mm) tại z = −186 và −139. Thêm **2 vít kẹp M3**
  (mỗi chân 1, lỗ mồi Ø2.5 xuyên thành sau máng) giữ panel.
- **Không cản Pi 4** `[VERIFIED]` (bounds trong `out/model.json`): panel chiếm
  z −175.7..−127.9, y 5.4..116.8; mép sau cùng (z = −127.9) ở độ cao y ≈ 111.7 —
  **không trùm lên Pi**, vì Pi kể cả connector chỉ bắt đầu ở z = −110 và cao
  22 mm. Khe 24 mm giữa chân màn hình (z=−136) và board driver (z=−112) để cắm
  cáp DSI/HDMI/USB-C và thoát khí quạt.
- Biên dạng chân được dựng sao cho **mọi mặt hướng xuống ≤ 39° so với phương
  thẳng đứng** → in **đứng đúng tư thế lắp, không cần support**.

### 4.4 Dự phòng mở rộng

**Lưới 3×2 lỗ M3 suốt (Ø3.4)** trên `base_pos` tại x = 30/75/120 (bước 45 mm),
z = 62/80 (bước 18 mm) — **dải đế trống phía SAU hộp tối**: sau 4 tai bắt hộp
(tai vươn tới z=51.5), **trước gân chu vi** (z ≥ 87). Đủ chỗ bắt thêm 1 module cỡ 40×25 mm
(MCP4725 dự phòng, cảm biến nhiệt-ẩm-ánh sáng nền, quạt 40 mm, hub I2C…) bằng
vít M3 + đai ốc mà không phải in lại đế.

---

## 5. Các phần in 3D (15 file STL — out/stl/)

| File | Vai trò | Số lượng in |
|---|---|---|
| `body.stl` | Thân hộp tối (2 làn + vách ngăn + máng dây + bệ thanh trượt + 8 lỗ trụ cắm chụp) | 1 |
| `lid.stl` | Nắp labyrinth (tấm phẳng — **không còn ray/thước khắc**) | 1 |
| `slide_shaft_red.stl` | Trục trượt D Ø8 — dùng chung 2 làn (đối xứng) | 2 |
| `led_carrier_red.stl` | Carrier LED (lỗ D + lỗ mù Ø5.1 cho thanh trượt) — dùng chung 2 làn | 2 |
| `rod_knob_red.stl` | Núm cầm Ø16×8 ở đuôi thanh trượt — dùng chung 2 làn | 2 |
| `frame.stl` | Khung giữ board 5×7 | 1 |
| `aperture_red_blank.stl` | Khẩu độ bịt kín (nền tối) | 2 (Đỏ + IR) |
| `aperture_red_d2.stl` | Khẩu độ Ø2 mm | 2 |
| `aperture_red_d5.stl` | Khẩu độ Ø5 mm | 2 |
| `aperture_red_d16.stl` | Khẩu độ Ø16 mm | 2 |
| `hood_l_red.stl` | Chụp che sáng trái (thành -X, cáp LED) — 4 trụ cắm Ø4 | 2 |
| `hood_r_red.stl` | Chụp che sáng phải (thành +X, cáp OPT101) — 4 trụ cắm Ø4 | 2 |
| `screen_foot_1.stl` | Chân đỡ màn hình cảm ứng 7 inch | 2 |
| `base_neg.stl` | Đế nửa TRƯỚC — bệ chân màn hình + Pi 4 + Grove HAT + driver | 1 |
| `base_pos.stl` | Đế nửa SAU — dưới hộp tối + lưới lỗ mở rộng | 1 |

> **Một thiết kế dùng cho cả 2 làn**: vì 2 làn quang đối xứng quanh z=0, các chi tiết
> `slide_shaft`, `led_carrier`, `rod_knob`, `aperture_*` và `hood_*` chỉ xuất bản
> `red` làm khuôn mẫu, dùng cho cả làn IR (bản `*_ir` trong `model.json` chỉ để
> hiển thị — không có file STL riêng). Tương tự `screen_foot_1` in 2 bản cho cả
> 2 chân. In thêm 1 bản nữa cho mỗi làn theo cột "Số lượng in".

> **Linh kiện mua ngoài (KHÔNG in)**
> - **2× thanh trụ tròn Ø5 h8 × 130 mm**, thép hoặc inox 304 `[SPEC]` — cơ cấu chỉnh d.
> - **2× vít lục giác chìm M3×6** — chặn núm cầm vào thanh trượt.
> - **4× vít M3×16** — 4 tai bắt hộp tối xuống đế.
> - **4× vít M3×12** — bắt 2 chân màn hình xuống `base_neg` (ta-rô vào nhựa).
> - **2× vít M3×16** — vít kẹp panel màn hình (xuyên thành sau máng).
> - *(tuỳ chọn)* **6× vít M3 + đai ốc** — lưới lỗ mở rộng Ø3.4 (3×2) trên
>   `base_pos`, phía sau hộp tối (§4.4).
>
> **ĐÃ BỎ so với v2**: 4× nam châm đĩa Ø10×3 N35 và 8× vít M3×8 bắt chụp cáp
> (chụp giờ dùng 4 trụ cắm liền khối).
>
> Ngoài ra chỉ hiển thị trong viewer để duyệt lắp ráp: `led_red`, `led_ir`,
> `opt101_red` (#2 → A2), `opt101_ir` (#1 → A0), `sensor_board` (5×7 cm), `pi4`,
> `grove_hat`, `driver_board` (perfboard + LM358 + 2×2N4401 + 2× MCP4725),
> `push_rod_red/_ir` (thanh Ø5 mua sẵn), `screen7` (panel 7"), `wiring`.

**Thông số in khuyến nghị**

- Nhựa **đen mờ** (matte) giảm phản xạ nội buồng — PLA đủ dùng, PETG/ABS nếu LED
  công suất cao. Đế nên PETG/ABS bền cơ.
- Lớp 0.2 mm, tường ≥ 4 vòng (tường thực ≥ 2.4 mm), infill 20–30% (thân/đế),
  100% (carrier, núm cầm, chân màn hình).
- **Bệ dẫn hướng thanh trượt** in cùng thân, tiết diện giọt nước ngược → không
  cần support. Sau khi in nên **doa nhẹ lỗ Ø5.4** bằng chính thanh Ø5 (xoay
  tay vài vòng) để bỏ ba-via lớp đầu.
- Bản in sẵn tư thế (không support) là gói `--bambu` trong `out/print_bambu/`;
  STL trong `out/stl/` giữ hệ thế giới (mở bằng slicer cần xoay — xem §8.3).
- Đế in 2 nửa `base_neg` + `base_pos`, nối bằng **5 mộng vuông** (10/43/77/111/144)
  — không cần vít bắt chéo đường nối z=0.

---

## 6. Lắp ráp

1. **Hộp tối**: ép carrier LED (kèm LED) lên trục trượt D mỗi làn (trượt tự do,
   không vít); đẩy trục vào lỗ mù vách trái, đầu còn lại tựa cột đỡ. Lắp khung
   giữ board, luồn board 5×7 + 2 module OPT101, chốt bằng 2 vấu nắp.
2. **Thanh trượt**: luồn thanh Ø5 từ NGOÀI qua bệ dẫn hướng vách `-X`, cắm
   **15 mm** vào lỗ mù trên lưng carrier (ép khít; 1 giọt keo nếu muốn cố định
   hẳn — không bắt buộc, cắm khít đã đủ đẩy/kéo). Đẩy tới khi phần thò ra ngoài
   mặt bệ = d mong muốn (Đỏ 25 mm / IR 85 mm). Xỏ **núm cầm** vào đuôi thanh,
   siết **vít M3×6** ngang. *Kiểm tra*: kéo-đẩy vài lần, carrier phải chạy êm,
   không kẹt, không xoay.
3. **Tấm khẩu độ**: **LẮP TRƯỚC KHI ĐÓNG NẮP** — trượt vào rãnh tại x=113..115
   (bắt đầu `blank` → đo nền tối, sau đó `d5`/`d16`).
4. **Chụp che sáng**: **không dùng vít** — gióng 4 trụ Ø4 của chụp vào 4 lỗ Ø4.30
   trên bệ vách, đồng thời gióng gân kín sáng vào vòng rãnh, **ấn đều bằng tay**
   cho tới khi bích chụp tì sát bệ. 4 chụp (mỗi làn 1 cặp trái/phải — mỗi file
   in 2 bản). Tháo: kẹp mép bích, kéo thẳng ra.
5. **Đế**: ghép 2 nửa `base_neg`/`base_pos` bằng 5 mộng vuông; bắt hộp tối lên
   đế qua 4 tai (vít M3×16) tại x=21/129, z=±40.
6. **Điện tử**: Pi 4 lên 4 trụ M2.5 của `base_neg` (x 62..147), Grove HAT cắm
   header; board driver 70×55 (**không xoay**) lên 4 trụ M3 của `base_neg` ngay
   **bên -X kề Pi** (x −12..58, cùng dải z) — cạnh `+Z` mang header ra LED quay
   thẳng về hộp tối; 2 breakout MCP4725 hàn trên board, hàng chân quay lên.
7. **Dây** theo `docs/hardware/PPG_PROTOTYPE_WIRING_AND_TEST_POINTS.md`:
   TX driver→LED qua chụp -X, RX OPT101→cáp Grove→socket A0/A2, I2C HAT→2 DAC,
   USB-C→Pi. Trong mô hình, dây được dựng thành **bẹ dây** (`harness()`): nhiều
   sợi song song sát nhau trên cùng lộ trình, buộc **dây rút (cable tie)** định
   kỳ 12–40 mm:
   - **TX**: bẹ 2 sợi (đỏ/đen) chạy trên đế → chui qua **khe sàn chụp -X**
     (x=-19..-12) → trong lòng chụp → cổng ra → **máng sàn bắt đầu tại x=9**
     (lùi sau 4 trụ đứng đỡ lỗ trụ cắm) → carrier LED. Bẹ chạy ở **y ≈ 1.8..9**,
     **thấp hơn thanh trượt (y=24) ít nhất 15 mm** → không bao giờ vướng.
   - **RX**: bẹ 3 sợi (đỏ/đen/vàng) từ header 6 chân module → **khe dây trên
     khung board** (y 56..60) → cửa luồn dây (y 12..58) → chụp +X → khe sàn →
     nối vào **cáp Grove trắng** vòng qua nóc hộp → socket A0/A2 trên HAT.
   - **I2C**: bẹ 2 cáp trắng chung đoạn HAT→nóc hộp, tách về 2 MCP4725.
8. **Nắp**: đậy nắp labyrinth (tấm phẳng, không còn ray/cần trượt). Chỉnh d
   bằng thanh trượt từ ngoài — **không cần mở nắp nữa**.
9. **Màn hình 7 inch**: bắt 2 chân đỡ xuống **`base_neg`** (hàng đầu, 4 vít
   M3×12), tra panel vào máng ngả 15° — **mặt hiển thị quay ra -Z, về phía người
   dùng**; siết 2 vít kẹp M3 ở thành sau. Cáp DSI/HDMI + nguồn màn hình luồn qua
   khe 24 mm giữa chân màn hình và board driver, không chắn quạt hay cổng Pi.
10. Chạy `python3 main.py --dry-run` trước khi chạy thật.

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

**Trượt vị trí LED**: mục *"Vị trí LED — thanh trượt đẩy-kéo Ø5"* có 2 slider
d=15..90 mm — carrier + LED + chùm sáng + **thanh trượt + núm cầm** di chuyển dọc
trục D đúng cơ cấu vật lý (thấy rõ phần thanh thò ra ngoài bệ dài đúng bằng d),
chùm sáng giữ nguyên góc mở datasheet và luôn ghim đầu xa tại cửa sổ OPT101 (x=120).

**Màn hình 7 inch** hiển thị dưới dạng khối `screen7` [SPEC] 194×110×20 mm ngả 15°
trên 2 chân đỡ — bật/tắt trong danh sách bộ phận để kiểm tra tầm nhìn và va chạm.

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
| `lid` | + vát vành mép | Tấm phẳng + rãnh labyrinth |
| `screen_foot` | + vát 4 cạnh đứng phần đế chân | Không vát |
| `hood` | + vát góc ngoài | Hộp phẳng |
| `aperture` | + khắc mã nhận dạng (vạch) | Không khắc |
| `base` | + gân chu vi dưới đế, vát góc, vát mép | Tấm phẳng 4 mm — in không phải bridge |

Mọi chi tiết chức năng (vách ngăn quang, lỗ trục, khe khẩu độ, **bệ + lỗ dẫn
hướng thanh trượt**, **lỗ trụ cắm chụp + vòng mộng kín sáng**, mộng nối đế,
trụ đỡ board, máng kẹp màn hình) đều **giữ nguyên ở cả 2 chế độ** — chỉ bỏ
phần trang trí.

### 8.3 Gói in Bambu Lab A1 (`--bambu`)

```bash
../../.cad_venv/bin/python build_system.py --bambu
```

Xuất `out/print_bambu/` — hộp tối + trục/carrier/núm thanh trượt + chụp luồn dây
+ khẩu độ, bỏ phần đế/khung board/chân màn hình:

| File | Chi tiết | Kích thước bàn (mm) |
|---|---|---|
| `00_ppg_hop_toi_A1_all_in_one.stl` | **Cả 11 chi tiết xếp sẵn** trên 1 bàn (MaxRects) | 237×235, cao 64 |
| `01_than_hop_toi.stl` | Thân hộp (lỗ luồn dây, khe khẩu độ, máng dây, **bệ thanh trượt**) | 170×103, cao 64 |
| `02_nap_labyrinth.stl` | Nắp labyrinth (tấm phẳng — bỏ ray/thước khắc) | 150×80, cao 11 |
| `03_truc_truot_D.stl` | Trục trượt D Ø8 (in 2 bản) | 110×6.5, cao 8 |
| `04_carrier_led.stl` | Carrier LED (in 2 — đáy xuống bàn, lỗ mù thanh trượt nằm ngang) | 25×18, cao 35 |
| `05_num_thanh_truot.stl` | Núm cầm thanh trượt (in 2 — mặt đĩa úp xuống bàn, lỗ mù ngửa lên) | 16×15.5, cao 8 |
| `06`/`07_chup_luon_day_*.stl` | Chụp che sáng lỗ luồn dây (trái/phải, **4 trụ cắm Ø4**) | 22.5×35.5, cao 16.5 |
| `08..11_khau_do_*.stl` | Khẩu độ bịt/Ø2/Ø5/Ø16 (nằm phẳng, tab cầm cắt gọn) | 61.1×34.9, cao 3 |

> Thân rộng **170 mm** (thay vì 150 ở v2): bao thân giờ là x = −18..152 — thêm
> **bệ dẫn hướng thanh trượt nhô ra 18 mm** ở thành `-X` và 2 mm tai bắt hộp ở
> `+X`. Vẫn dư bàn 256 mm. Thuật toán xếp bàn đã đổi từ *shelf next-fit* sang
> **MaxRects best-short-side-fit (có xoay 90°)** để 11 chi tiết vẫn vừa 1 bàn
> sau khi thân to ra.

[BOM] mua ngoài cho gói này: **2× thanh trụ Ø5 h8 × 130 mm** (thép/inox) +
**2× vít lục giác chìm M3×6** (chặn núm). Gói `--bambu` **không** gồm đế và chân
màn hình (in bằng build thường: `--stl-only --only base` / `--only screen`).

Tất cả đã **chuyển về hệ trục slicer** (Z = chiều cao — STL gốc trong `out/stl/`
dùng hệ thế giới Y-lên trời nên sẽ nằm nghiêng nếu mở trực tiếp) và **xoay sẵn
tư thế in không cần support**. Bambu Studio: mở file all-in-one → `Split to
objects` nếu muốn in tách bàn. In bằng nhựa đen mờ, layer 0.2mm, tường ≥4 vòng
(tham khảo §5).

**Thu nhỏ hộp**: thêm `--scale S` (ví dụ `--bambu --scale 0.85` → hộp
~128×57×68 mm, bàn in ~230×185 mm). Các cặp lắp ghép vẫn khớp nhau vì cùng tỉ
lệ; lỗ vít M3/trục Ø8 nhỏ theo (khoan lại hoặc dán). Khuyến nghị `S >= 0.8`
để tường còn ≥ 2.4 mm kín sáng. Lưu ý: hộp ở scale 1.0 đã chỉ dài 15cm —
kích thước ~23.7cm của file all-in-one là **bàn in xếp trải 11 chi tiết**,
không phải kích thước hộp. Khi `--scale S`, **thanh trượt Ø5 mua sẵn KHÔNG
scale theo** — phải doa lại lỗ bệ về Ø5.4 hoặc dùng thanh Ø khác.

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
- `[SPEC]` Pi 4B (PCB 85×56×1.4, lỗ M2.5 bước 58×49), khuôn HAT 65×56.5;
  **Raspberry Pi 7" Touch Display 194×110×20 mm**; **thanh trụ tròn Ø5 h8**
  (linear shaft thương mại — dung sai h8 = 0/−0.018 mm).
- `[VERIFIED]` ray-cast + boolean trên chính STL đã xuất, chạy bằng
  `verify_geometry.py` — **96/96 PASS**: 15 chi tiết watertight, 14 cặp lắp ghép
  giao nhau = 0 mm³ (kể cả `body × screen_foot_1` và `base_neg/base_pos ×
  screen_foot_1`), thứ tự trước→sau (chân màn hình z ≤ −136 nằm hẳn trước board
  driver z = −112, đế nửa trước phủ hết chân), lỗ dẫn hướng thanh trượt thông
  suốt, 4 lỗ trụ cắm chụp mở, vòng mộng âm-dương khớp, lưới lỗ mở rộng thông,
  gói Bambu đúng 12 file và nằm trong bàn 256×256.
- `[ASSUME]` **lực đẩy/kéo và độ rơ của thanh trượt chưa đo trên vật thật**:
  khe 0.20 mm hướng kính là giá trị thiết kế cho in FDM 0.2 mm; ma sát thực tế
  phụ thuộc chất lượng lớp in. Nếu chặt → doa lỗ; nếu rơ → thay thanh Ø5.1 hoặc
  in lại bệ với `ROD_BORE_R` nhỏ hơn.
- `[ASSUME]` **hiệu quả kín sáng của bẫy khe vành 105:1 là suy luận kỹ thuật**
  (khe hẹp + dài + nhựa đen mờ), **chưa đo bằng OPT101 ở chế độ khẩu độ `blank`**.
  Phép đo bắt buộc trước khi tin số liệu: đo nền tối với thanh ở d=15 và d=90,
  so với nền tối khi bịt kín lỗ bằng băng dính đen.
- `[ASSUME]` panel 7" ngoài loại `[SPEC]` ở trên: dày 15..21 mm mới kẹp được.
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

---

## 12. Nhật ký v3 (2026-09-02) — thanh trượt đẩy-kéo, chụp trụ cắm, đế màn hình

- **(a) Bỏ hoàn toàn cần trượt nam châm** → **thanh trụ Ø5 h8 × 130 mm** gắn cứng
  vào lưng carrier, xuyên vách `-X` qua bệ dẫn hướng dài 21 mm (§4.1). Không còn
  nam châm N35, không còn ray/chặn/thước khắc trên nắp — **nắp giờ là tấm phẳng**.
  Lỗ Ø5.4 / khe 0.20 mm / dài 21 mm = **bẫy sáng khe vành ≈105:1**; bệ được đắp
  thêm vật liệu (ống Ø10.4 vách 2.5 mm + bệ phẳng 2.0 mm nâng vách 3.0 → 5.0 mm)
  nên **kết cấu hộp khoẻ hơn**, không yếu đi.
- **(b) Chiều dài thanh lộ ra ngoài bệ = d (mm)** nhờ chọn `ROD_LEN = 130` —
  đọc khoảng cách bằng thước kẹp, không cần thước khắc.
- **(c) Chụp cáp đổi từ 2 vít M3 → 4 trụ cắm Ø4** (lỗ Ø4.30, khe 0.15 mm/mặt) +
  **vòng mộng âm-dương khép kín** quanh lỗ cáp (gân 1.2 mm ↔ rãnh 1.5×1.5 mm).
  Bỏ 8 vít M3×8. Sửa lỗi thật: gân bịt vào đảo rãnh 13.1 mm³ ở cả 2 chụp
  (đặt lệch dấu khe ở mép trong) — nay `body × hood_*` = 0 mm³.
- **(d) Thêm 2 chân đỡ màn hình cảm ứng 7 inch** trên nửa đế `+Z` (§4.3), in
  đứng không cần support, máng kẹp ngả 15° + vít kẹp M3 → nhận cả panel không
  cùng chuẩn lỗ bắt. Chân lùi về **z = 56..110** để né 4 tai bắt hộp (z≤51.5).
- **(e) Lưới 2×3 lỗ M3 dự phòng** (x 55/95, z 65/90/115) trên `base_pos` cho
  module mở rộng sau này (§4.4).
- **(f) `out/stl/` 14 → 15 file**: bỏ `mag_slider_red.stl`, thêm
  `rod_knob_red.stl` + `screen_foot_1.stl`. `out/print_bambu/` vẫn **12 file**
  (`05_can_truot_nam_cham.stl` → `05_num_thanh_truot.stl`).
- **(g) Xếp bàn in đổi sang MaxRects** (best-short-side-fit, xoay 90°) — thân
  to ra 150 → 170 mm làm shelf next-fit cũ vỡ bàn; nay all-in-one = 237×235 mm.
  Thêm bước **dọn STL mồ côi** trong `export()` và `export_print_package()` để
  file của lần build trước không còn sót lại khi đổi tên chi tiết.
- **(h) `verify_geometry.py` viết lại: 69 → 93 check, tất cả PASS.** Thêm cặp
  `body × screen_foot_1` — chính check này bắt được va chạm chân màn hình với
  tai bắt hộp (98.5 mm³) trước khi in.
- **(i) Viewer**: nhãn cơ cấu đổi thành "thanh trượt đẩy-kéo Ø5", slider d kéo
  theo cả `push_rod_*` và `rod_knob_*`, danh sách tải STL cập nhật đúng 15 file,
  thêm khối `screen7` xem trước màn hình.

---

## 13. Nhật ký bố cục (2026-09-02, sau v3) — xếp hàng màn hình → Pi 4 → hộp tối

Lý do: ở bố cục v3 màn hình nằm ở nửa `+Z`, **sau hộp tối** so với chỗ ngồi của
người dùng → bị hộp che, không nhìn và không chạm được. Nay **-Z được định nghĩa
là mặt trước** và cả 3 cụm xếp thành một hàng trước → sau.

- **(a) Đế chung 198×286 → 198×288 mm**, `BASE_Z0, BASE_Z1 = −196, 92`
  (trước: −164, 122). Nửa trước `base_neg` 198×196, nửa sau `base_pos` 198×92 —
  cả hai vẫn vừa bàn in 256×256. Mộng ghép tại z=0 giữ nguyên.
- **(b) Chân màn hình chuyển từ `base_pos` (z 56..110) sang hàng đầu của
  `base_neg`** (`SCR_FOOT_Z0 = −190` → z −190..−136, lỗ bắt z = −186 / −139).
  Panel chiếm z −175.7..−127.9 (mép sau ở y ≈ 111.7) → **không trùm lên Pi 4**
  (Pi kể cả connector z ≥ −110).
- **(c) Board driver LED bỏ phép xoay 90°** (xoá ma trận `_DRV_R`) — nay chỉ tịnh
  tiến, `DRV_WX, DRV_WZ = −12, −112` → chiếm x −12..58, z −112..−57. Khe hở:
  4 mm tới Pi (x=62), 12 mm tới mép đế (x=−24), 5.5 mm tới tai bắt hộp (z=−51.5).
  Cạnh `+Z` mang header ra LED quay thẳng về hộp tối → đường TX ngắn nhất.
- **(d) Lưới lỗ mở rộng chuyển ra dải đế trống phía sau hộp**: x 30/75/120,
  z 62/80 (trước: x 55/95, z 65/90/115 — vùng đó nay là mép sau đế).
- **(e) Sửa một sai sót mô hình dây có từ trước**: bó TX cũ chạy ở y=1.8 dọc
  x=−7 → **xuyên thẳng qua vách đặc của chụp che sáng**. Nay bó TX vòng ra
  ngoài đầu ống chụp (x=−21) rồi **chui lên đúng khe sàn** (x −18.5..−13,
  y 1..5) vào lòng ống; làn IR chạy ở y=4.4 khi song song để không đè lên bó Đỏ
  (y=1.8). Bó I2C và nguồn cũng được vẽ lại theo board driver không xoay.
- **(f) Viewer**: các preset camera lật về phía trước — `iso` và `Trước` nay đặt
  camera ở `-Z` nhìn thẳng vào mặt màn hình, `Khối điện tử` ngắm cụm Pi + driver
  (target z=−84), lưới sàn dời về tâm bố cục mới (z=−52).
- **(g) `verify_geometry.py` 93 → 96 check, tất cả PASS**: thêm 2 cặp
  `base_neg × screen_foot_1`, `base_pos × screen_foot_1` và 2 check thứ tự
  trước→sau. Gói Bambu **không đổi** (12 file, all-in-one 237×235 mm) vì
  `PRINT_SET` không chứa đế và chân màn hình.
