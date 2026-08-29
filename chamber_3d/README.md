# Buồng tối PPG — Thiết kế in 3D cho hệ PPG Simulator (Raspberry Pi)

> Buồng tối quang học 2 kênh (Red 622 nm / IR 875 nm → 2× OPT101), sinh bằng
> script tham số `build_chamber.py` (trimesh + Manifold CSG), duyệt mô hình 3D
> trực tiếp trên trình duyệt tại `viewer.html` (three.js, chạy offline).

---

## 1. Kiến trúc hệ thống

```
┌────────────────────────────── Raspberry Pi 4 ──────────────────────────────┐
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
│         │            ┌─────────────────────────────▼─────────────────────┐ │
│         │            │  BUỒNG TỐI 3D (chamber_3d/) — 2 buồng cách quang  │ │
│         │            │   Đỏ  y=3..29 : LED 622 nm ──▶ OPT101 #2 (Red)    │ │
│         │            │   IR  y=32..58: LED 875 nm ──▶ OPT101 #1 (IR)     │ │
│         │            │   Ray trượt LED d=15..85 mm + tấm khẩu độ (x=95)  │ │
│         │            └──────────────────────┬────────────────────────────┘ │
│         │                     V_out (0..~2.13 V, 300..1100 nm)             │
│         │            ┌──────────────────────▼────────────────────────────┐ │
│         ├────────────▶│  RX: OPT101 → Grove ADC (hw/opt101_rx.py)        │ │
│         │   (UI hiển  │   Grove Base HAT ADC 0x08, 12-bit                │ │
│         │   thị A0/A2)│   A0 = IR · A2 = Red · A1 không dùng             │ │
│         │            │   Thread "OPT101Rx" 100 Hz, buffer 2000           │ │
│         │            └───────────────────────────────────────────────────┘ │
│         ▼                                                                  │
│  core/: signal_engine (tạo PPG 1 kHz), digital_filters, csv/tx_rx logger  │
│  ui/:   ctk_app.py + frames (playback, pathology, calibration)            │
│  models/ppg_model.py · config.py · config_store.py · calibration.py       │
└────────────────────────────────────────────────────────────────────────────┘
```

**Ghi chú kiến trúc then chốt** (từ mã nguồn):

- **TX tách biệt RX**: `DACManager` (Blinka busio, 1 kHz tick) và `OPT101Receiver`
  (smbus2, thread riêng 100 Hz) dùng 2 file descriptor I2C riêng; kernel tuần tự
  hóa giao dịch I2C theo adapter nên ghi DAC không thể làm hỏng đọc ADC.
- **RX không bao giờ viết DAC**, không import stack Blinka — lỗi RX chỉ làm
  ứng dụng chạy chế độ TX-only, không chết tiến trình.
- **Không bịa mẫu**: mỗi lần đọc lỗi đều không thêm gì vào buffer; `--dry-run`
  là trạng thái mô phỏng có gắn nhãn rõ (`is_simulated=True`).
- **Kênh A0=IR, A2=Red** là mapping đã xác minh — không bao giờ hoán đổi.

---

## 2. Sequence diagram — chuỗi tín hiệu 1 chu kỳ mẫu

```mermaid
sequenceDiagram
    autonumber
    participant UI as CTkApp (ui/ctk_app.py)
    participant SE as SignalEngine (core/signal_engine.py)
    participant DAC as DACManager (hw/dac_manager.py + led_driver/dac.py)
    participant LED as LED driver (LM358 + 2SC1815 + R_sense)
    participant CH as Buồng tối 3D (LED ↔ OPT101)
    participant RX as OPT101Receiver (hw/opt101_rx.py)
    participant ADC as Grove ADC (0x08, A0=IR A2=Red)
    participant PROC as Digital filters / log (core/)

    UI->>SE: Start / thay đổi tham số (HR, SpO2, patho…)
    SE->>SE: Tạo sóng PPG 1 kHz (DC + AC, mô hình Đỏ/IR)
    loop Mỗi tick TX 1 kHz
        SE->>DAC: set_code(channel, code)  # IR→0x60, Red→0x61
        DAC->>DAC: code → Vdac (12-bit, 3.28 V)
        DAC->>LED: Vdac qua chia 10k/10k → V_cmd = Vdac/2
        LED->>LED: op-amp ép V_sense = V_cmd; I_LED = V_cmd / R_sense
        LED->>CH: Phát xạ I_e (µW/sr) theo khoảng cách d (mm)
    end

    loop Mỗi tick RX 100 Hz (thread OPT101Rx, decoupled)
        ADC->>CH: Đọc quang thông tại cửa sổ OPT101 (2.29×2.29 mm)
        CH->>ADC: V_out = R_v × E × A + V_dark  (≤ ~2.13 V)
        RX->>ADC: read_raw(A0|A2) → 12-bit code 0..4095
        RX->>PROC: RXSample(timestamp, raw, saturated) → deque(2000)
        PROC->>PROC: Lọc, tính SpO2 (tỷ lệ AC/DC Đỏ–IR), ghi TX/RX log
    end
    UI-->>SE: Hiển thị dạng sóng / chỉ số trực tiếp (poll buffers)
```

---

## 3. Range thu/phát — bằng chứng datasheet (docs/ds_linhkien/)

| Đại lượng | LED Đỏ (red_led_3.3mm) | LED IR (IR_led_3.3mm) | OPT101 (opt101.pdf) |
|---|---|---|---|
| Bước sóng | 620–625 nm dominant | 875 ± 45 nm | Đáp ứng phổ **300–1100 nm** |
| Cường độ | 150–200 mcd (~711 µW/sr @20 mA) | 5600–24000 µW/sr (typ ~9000 @20 mA) | — |
| Góc nửa công suất 2θ½ | 40–60° | 30° | — |
| Độ nhạy Rv | — | — | **0.45 A/W @ 650 nm** (đỉnh ~800–900 nm ≈ 0.49 A/W @875) |
| Diện tích thu | — | — | Photodiode **2.29 × 2.29 mm** |
| Đầu ra | — | — | 0 → **VS − 1.15 V ≈ 2.13 V** @ VS=3.28 V |

**Kết luận range**: OPT101 nhạy toàn dải 300–1100 nm nên **cả 2 LED đều rơi
trong vùng phổ thu** — vì vậy buồng tối phải cách quang hoàn toàn giữa 2 buồng,
nếu không tín hiệu Đỏ sẽ lọt sang kênh IR và ngược lại (sai phép đo SpO2).

---

## 4. Ngân sách quang học (optical budget)

Mô hình điểm-xấp-xỉ-nghịch-bình-phương `V_out = Rv × Ie × (A/d²) + V_dark`:

**Kênh ĐỎ (622 nm)** — LED yếu → để gần sensor:

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

---

## 5. Thiết kế buồng tối 3D

### 5.1 Quy ước trục (hệ lắp ráp)

- **+X** : trục quang, tường LED (trái) → cửa sổ OPT101 (phải)
- **+Y** : lên trên — buồng **Đỏ trên** (y 3..29), buồng **IR dưới** (y 32..58)
- **+Z** : trước/sau — tấm khẩu độ tụt vào rãnh sàn, nắp đậy phía trên

Kích thước tổng thể: **116 × 63 × 36 mm** (X×Y×Z, đã gồm chân đế).

### 5.2 Cơ chế chống rò sáng (light-tightness)

1. **Tường 3 mm đặc** — không khoan lỗ LED xuyên tường (LED ở trong, trên carrier
   trượt); loại bỏ hoàn toàn đường rò sáng từ ngoài.
2. **Vách ngăn 3 mm** giữa buồng Đỏ và IR (cách ly quang học tuyệt đối 2 kênh).
3. **Nắp labyrinth** — rãnh khóa ngoằn ngoèo trên thành nắp + môi nắp khớp
   khuôn, không có đường thẳng từ ngoài vào trong.
4. **Kênh dây & ống dẫn** — dây LED/OPT101 đi qua rãnh sàn vào **ống dẫn kín
   phía sau tường phải**, thoát qua lỗ chân đế phía dưới (nằm dưới khay điện tử).
5. **Tấm khẩu độ** tại x=93.4..95 (trước sensor, sau mọi vị trí LED d=15..85)
   chặn ánh sáng lệch trục; có thể thay: `blank` (bịt kín — đo nền tối), `d2`
   (Ø2 mm), `d5` (Ø5 mm), `open` (Ø16 mm).
6. **Phễu thu hẹp** (frustum 6.4→4.9 mm) ngay trước cửa sổ OPT101 làm màn chắn
   thứ cấp.

### 5.3 Cơ cấu điều chỉnh khoảng cách

- **Ray trượt** trên sàn mỗi buồng (rộng 8 mm, cao 4 mm) từ x=6 đến x=92.
- **Carrier LED** (12×18 mm) ôm ray, lỗ khoan LED Ø3.2 mm + collar chắn sáng
  nghiêng 45°, chân lò xo bấm 2 bên ray.
- **Rãnh định vị (detent)** mỗi 5 mm từ d=15..85 — kéo carrier theo từng nấc,
  đọc vạch thước 10 mm trên sàn.
- Vị trí mặc định: **Đỏ d=25 mm**, **IR d=85 mm**.

### 5.4 Vị trí OPT101

- Hốc sensor x=101..103 (cửa sổ phẳng tại x=103), rộng 10.4 × 9.2 mm (DIP-8).
- 8 lỗ chân Ø1.1 mm đúng chuẩn DIP-8 (bước 2.54 mm, 2 hàng z=±3.81 mm) xuyên
  vào ống dẫn → chân ra khay điện tử bên dưới.

---

## 6. Các phần in 3D (15 file STL — out/stl/)

| File | Vai trò | Số lượng | Vật liệu |
|---|---|---|---|
| `body.stl` | Thân buồng (2 khoang + ống dẫn + chân đế) | 1 | PLA/ABS đen mờ |
| `lid.stl` | Nắp labyrinth | 1 | PLA/ABS đen mờ |
| `led_carrier_red.stl` | Carrier trượt LED Đỏ | 1 | PLA đen |
| `led_carrier_ir.stl` | Carrier trượt LED IR | 1 | PLA đen |
| `aperture_*_blank.stl` | Tấm bịt kín (nền tối) | 2 (Đỏ+IR) | PLA đen |
| `aperture_*_d2.stl` | Khẩu độ Ø2 mm | 2 | PLA đen |
| `aperture_*_d5.stl` | Khẩu độ Ø5 mm | 2 | PLA đen |
| `aperture_*_open.stl` | Khẩu độ Ø16 mm | 2 | PLA đen |
| `wire_cover_red.stl` | Nắp rãnh dây buồng Đỏ | 1 | PLA đen |
| `wire_cover_ir.stl` | Nắp rãnh dây buồng IR | 1 | PLA đen |
| `base_tray.stl` | Khay điện tử (driver + Grove HAT) | 1 | PLA đen |

> **Linh kiện mua sẵn (KHÔNG in)** — chỉ hiển thị trong viewer để duyệt:
> `led_red` (LED Đỏ 622nm), `led_ir` (LED IR 875nm), `opt101_red` (OPT101 #2 → A2),
> `opt101_ir` (OPT101 #1 → A0, DIP-8). Chúng nằm ở đúng vị trí lắp ráp trong
> model 3D: LED trong carrier (Đỏ d=25mm, IR d=85mm), OPT101 trong hốc x=101..103.

**Thông số in khuyến nghị**

- Nhựa **đen mờ** (matte) để giảm phản xạ nội buồng (tối ưu) — ABS/PETG chịu nhiệt
  tốt hơn nếu LED công suất cao; PLA đủ dùng cho 3.3 mm LED.
- Lớp 0.2 mm, tường ≥ 4 vòng (tường thực ≥ 2.4 mm), infill 20–30% (thân), 100% (carrier).
- Không cần hỗ trợ (support) với tư thế in trong file (đã xoay sẵn theo hướng in).
- Dung sai: lỗ chân OPT101 Ø1.1 mm — nếu in lệch, doa lại Ø1.2 mm; lỗ LED carrier
  Ø3.2 mm doa Ø3.3 mm.

---

## 7. Lắp ráp & hiệu chuẩn

1. Luồn 2 LED vào carrier (Đỏ → carrier đỏ), dây đi qua rãnh thoát phía sau.
2. Lắp OPT101 #1 (IR) vào hốc dưới, #2 (Red) vào hốc trên; chân xuyên vào ống dẫn.
3. Đặt body lên `base_tray`, dây dẫn đi qua lỗ chân đế xuống khay (driver + Grove HAT).
4. Kéo carrier theo ray tới nấc detent mong muốn: Đỏ 25 mm, IR 85 mm (hoặc theo
   ngân sách quang §4).
5. Chèn tấm khẩu độ (bắt đầu bằng `blank` ở cả 2 buồng → đo nền tối; sau đó `open`/`d5`).
6. Đậy nắp labyrinth, vặn/ép khít.
7. Chạy `python3 main.py --dry-run` trước, sau đó chạy thật với đồng hồ đo tại
   TP_OPT101_* (xem `docs/hardware/PPG_PROTOTYPE_WIRING_AND_TEST_POINTS.md`).

---

## 8. Web viewer (duyệt mô hình 3D)

```bash
python3 -m http.server 8008 --directory chamber_3d
# mở http://localhost:8008/viewer.html
```

Hoặc mở thẳng file `chamber_3d/viewer.html` (three.js đã nhúng, chạy offline).

**Điều khiển**: kéo chuột xoay · lăn thu phóng · phải chuột di chuyển ·
thanh **Tách rời** xem thứ tự lắp · thanh **Mặt cắt X** nhìn vào trong buồng ·
nút **Trong suốt thân** xuyên qua thân buồng để thấy LED + OPT101 bên trong ·
nút **Trong buồng IR/Đỏ** đưa camera vào ngang trục quang của từng buồng ·
nút **Trục quang** hiển thị 2 trục Đỏ/IR · checkbox ẩn/hiện từng bộ phận
(nhãn tiếng Việt; LED/OPT101 có màu riêng: đỏ = LED Đỏ, tím = LED IR,
xanh dương = cửa sổ photodiode OPT101, vàng = chân linh kiện).

### Ảnh preview tĩnh (không cần mở trình duyệt)

| Ảnh | Mô tả |
|---|---|
| `out/preview_assembled.png` | Mô hình lắp ráp hoàn chỉnh (3 góc) |
| `out/preview_exploded.png` | Dạng tháo rời — thứ tự lắp ráp |
| `out/preview_cross_section.png` | Mặt cắt dọc: 2 buồng + carrier + khẩu độ |

Tái sinh ảnh (cần matplotlib): `../.cad_venv/bin/python render_preview.py`

---

## 9. Tái sinh mô hình (single source of truth)

Mọi tham số nằm ở đầu `build_chamber.py` (mm); thay đổi → chạy lại:

```bash
../.cad_venv/bin/python build_chamber.py          # budget + STL + model.json + viewer.html
../.cad_venv/bin/python build_chamber.py --budget-only
```

Phụ thuộc: `trimesh`, `manifold3d`, `numpy` (đã cài trong `.cad_venv/`).
