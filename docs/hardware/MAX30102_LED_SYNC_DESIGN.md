# Thiết kế đồng bộ LED mô phỏng với xung LED của MAX30102

**Trạng thái: THIẾT KẾ TÍNH TOÁN, CHƯA LẮP, CHƯA ĐO.** Nhánh thử: `test/max30102-led-sync`
(không chạy trên `main`). Các giá trị dưới đây là tính toán từ datasheet và mạch hiện có;
mọi kết luận về thời gian, độ rò và độ tuyến tính phải được đo trên phần cứng.

## 1. Vì sao cần

Phép đo ngày 23/11/2026 (`firmware/esp32s3_max30102/bench/results/20261123/`) cho thấy ánh sáng
liên tục của LED mô phỏng có tới photodiode của MAX30102 nhưng bị mạch triệt ánh sáng môi trường
(ALC) trừ đi: mức trung bình chỉ lệch khoảng 17 count (dải 2048 nA, thang 262143), không có thành
phần 75 bpm trên nền nhiễu. MAX30102 lấy mẫu "môi trường" khi LED của chính nó tắt rồi trừ khỏi mẫu
khi LED bật, nên một nguồn sáng không đồng bộ luôn bị coi là ánh sáng môi trường.

Để cảm biến "thấy" tín hiệu mô phỏng, LED mô phỏng phải **chỉ sáng trong cửa sổ xung LED của
MAX30102** và tắt trong cửa sổ lấy mẫu môi trường. Khi đó photodiode nhận ánh sáng mô phỏng như
thể là ánh sáng LED phản xạ qua mô, và biên độ của nó vẫn do DAC của Pi đặt (DC + AC theo dạng sóng).

## 2. Nguyên lý

```
 MAX30102 module                      Mạch đồng bộ (mới)                 Driver LED hiện có (mỗi kênh)
 ┌──────────────┐                                                       DAC ─R1a 10k─┬─ CMD ──► LM358 IN+
 │ LED đỏ  ─ RD ├──► phát hiện LED bật ──► GATE_RED ──► Q_SH_RED ──────────────────────┤   (shunt CMD→GND
 │ LED IR  ─ IRD├──► phát hiện LED bật ──► GATE_IR  ──► Q_SH_IR  ─► (kênh IR)          │    khi LED MAX tắt)
 └──────────────┘                                                              R1b 10k ┘
```

- **Nguồn thời gian:** chân `RD` và `IRD` của module là cathode LED đỏ/IR, nối vào bộ kéo dòng
  bên trong MAX30102 (cần xác minh trên module đang dùng, mục 7). Khi LED của MAX30102 bật, cathode
  bị kéo xuống khoảng `VLED − Vf`; khi tắt, cathode lên gần `VLED`.
- **Cổng:** mỗi kênh dùng một comparator (LM393, cực thu hở) và một NMOS 2N7002 nối từ nút `CMD`
  xuống GND. LED MAX tắt → NMOS dẫn → `CMD ≈ 0` → LED mô phỏng tắt. LED MAX bật → NMOS ngắt →
  `CMD = DAC/2` → dòng LED mô phỏng = `CMD / R_sense` như hiện nay.
- Kênh đỏ mô phỏng được mở theo xung đỏ (`RD`), kênh IR theo xung IR (`IRD`). Vậy mỗi kênh ADC của
  MAX30102 chỉ thấy kênh mô phỏng tương ứng, đúng cấu trúc của máy mô phỏng SpO₂.
- Không cần sửa phần mềm Pi: DAC vẫn đặt biên độ. Phần mềm chỉ cần lưu ý mục 6.

## 3. Sơ đồ mỗi kênh (vẽ cho kênh đỏ, kênh IR giống hệt với `IRD`)

```
 VLED (anode LED trên module, đo bằng DMM)
   │
  Rp 10k                          VLED
   │                               │
 RD ──┬──────────────┐            R_ref1 100k
 (cathode)          R_d1 100k      │
      │              │             ├───────────── IN− (LM393 chân 2)       V_REF ≈ 0.405·VLED
      │              ├──── IN+ ────┼─(chân 3)      │
      │             R_d2 100k      │              R_ref2 68k
      │              │            R_hys 2.2M       │
      │             GND            │ (IN+ ↔ OUT)  GND
      │                            │
      │                 5V0 ─ R_pu 4.7k ─┬── OUT (LM393 chân 1) ──► GATE_RED
      │                                  │
      │                                  └── gate Q_SH (2N7002)
      │                                       drain → CMD_RED (= LM358 chân 3, TP_CMD_RED)
      │                                       source → GND
      │                                  JP_SYNC (jumper): nối gate Q_SH xuống GND
      │                                                    = chế độ liên tục như hiện nay
 LM393: chân 8 → 5V0 (+100 nF), chân 4 → GND. Nửa B (5,6,7) cho kênh IR.
```

Cực tính: LED MAX **tắt** → `IN+ = VLED/2 > V_REF` → ngõ ra hở, R_pu kéo lên 5 V → 2N7002 dẫn
→ CMD bị kéo xuống. LED MAX **bật** → `IN+ < V_REF` → ngõ ra xuống thấp → 2N7002 ngắt → CMD trở về
`DAC/2`.

## 4. Tính toán

### 4.1 Phát hiện cathode

| Đại lượng | Giá trị | Ghi chú |
|---|---|---|
| Rp (cathode → VLED) | 10 kΩ | Không có Rp, bộ chia 200 kΩ sẽ cho một dòng µA chạy qua LED, cathode tụt khoảng 1–1.4 V dù LED "tắt" (đặc tính log của diode), mất phân biệt bật/tắt |
| Cathode khi tắt | VLED·200k/210k ≈ 0.95·VLED | Áp trên LED ≈ 0.05·VLED (≈ 0.16 V ở 3.3 V) → LED không dẫn |
| Dòng Rp lấy bớt khi bật | ≈ Vf/10k ≈ 0.14–0.2 mA | MAX30102 là nguồn dòng kéo: LED nhận `I_PA − I_Rp`. Đặt LED PA ≥ 2 mA (0x0A) |
| Cathode khi bật | VLED − Vf: đỏ ≈ VLED − 1.8 V, IR ≈ VLED − 1.4 V | Vf là giá trị điển hình ở vài mA, chưa đo |
| IN+ = cathode/2 | tắt ≈ 0.475·VLED; bật ≤ (VLED − 1.4)/2 | Chia đôi để giữ trong dải đồng pha LM393 (0 … Vcc − 1.5 V = 3.5 V) |
| V_REF | 0.405·VLED (100k/68k) | VLED = 3.3 V: tắt 1.57 V, ngưỡng 1.34 V, bật ≤ 0.95 V. VLED = 5 V: tắt 2.38 V, ngưỡng 2.03 V, bật ≤ 1.8 V |
| Trễ (R_hys 2.2 MΩ, nguồn 50 kΩ) | ≈ 5 V·50k/2.25M ≈ 0.11 V | Chống rung ở cạnh xung |

Nếu VLED của module khác 3.3–5 V, tính lại V_REF để ngưỡng nằm giữa hai mức đo được.

### 4.2 Cổng tại nút CMD

- Trở kháng Thevenin của CMD: 10k ‖ 10k = 5 kΩ.
- **Tụ C1a trên CMD phải để trống (DNP) hoặc ≤ 1 nF.** Với 100 nF, τ = 5k·100n = 0.5 ms, dài hơn
  cả xung 411 µs: LED mô phỏng sẽ không kịp lên. 1 nF → τ = 5 µs.
- 2N7002 R_DS(on) ≤ 7.5 Ω ở V_GS = 5 V (datasheet, giá trị max). Khi shunt, dòng từ DAC qua R1a là
  `V_DAC/10k` (70 µA ở 700 mV) → CMD dư ≈ 0.5 mV → dòng rò LED ≈ 0.5 mV/82 Ω ≈ 6 µA (≈ 0.15 % của
  4.3 mA). MCP4725 cấp 70 µA không vấn đề.
- Offset LM358 (tới 7 mV max) có thể giữ LED mô phỏng sáng nhẹ khi CMD = 0: tới 7 mV/82 Ω ≈ 85 µA
  (≈ 2 %). Phần này là hằng số trong cửa sổ môi trường nên chỉ làm giảm DC nhận được, không làm méo AC.
  Cần đo.

### 4.3 Ngân sách thời gian (ước tính, phải đo)

| Khâu | Bật (LED MAX bật → LED mô phỏng đủ dòng) | Tắt |
|---|---|---|
| LM393 phản hồi | ≈ 1.3 µs (datasheet, overdrive 100 mV) | ≈ 1.3 µs + R_pu·C_iss ≈ 4.7k·50 pF ≈ 0.25 µs |
| 2N7002 | < 0.1 µs | < 0.1 µs |
| LM358 + transistor | slew ≈ 0.3 V/µs từ ≈ 0 lên ≈ 0.65 V + CMD (≈ 1 V) → ≈ 3–4 µs, cộng thời gian ra khỏi bão hòa và xác lập: ước tính 5–10 µs | ≈ 2–4 µs |
| **Tổng** | **≈ 7–12 µs** | **≈ 4–6 µs** |

So với độ rộng xung MAX30102: đặt **LED_PW = 411 µs** (18 bit, firmware hiện đã dùng). Thời gian lên
chiếm ≈ 2–3 % cửa sổ; với 69 µs sẽ là 10–17 %, không nên dùng. Thời điểm MAX30102 lấy mẫu môi trường
so với cạnh xung LED không được datasheet cho chi tiết, nên phải đo xem LED mô phỏng đã tắt hẳn
trước khi cửa sổ môi trường bắt đầu chưa (mục 8, bước 3).

Nếu đo thấy cạnh lên quá chậm hoặc vọt lố: thay LM358 bằng op-amp nhanh hơn, ray-tới-ray, cùng sơ đồ
chân DIP-8 (ví dụ MCP6292, 10 MHz, 7 V/µs; kiểm tra nguồn hàng). Op-amp nhanh hơn trong vòng hồi tiếp
có transistor có thể dao động: giữ R_base 1 kΩ và lắp C2 (bù) khi cần.

### 4.4 Chu kỳ nhiệm vụ

Ở 200 sps, mỗi LED của MAX30102 sáng 411 µs mỗi 5 ms → **duty ≈ 8.2 %**. LED mô phỏng cũng chỉ sáng
8.2 % thời gian, nên công suất trung bình và nhiệt giảm mạnh. Có thể dùng dòng đỉnh cao hơn mức
liên tục hiện nay (giới hạn 600–750 mV DAC trong tài liệu 14/11 là cho chế độ liên tục) nếu cần thêm
tín hiệu, nhưng vẫn phải giữ trong định mức dòng đỉnh của LED và R_sense.

## 5. Linh kiện

| Ký hiệu | Linh kiện | Số lượng | Ghi chú |
|---|---|---|---|
| U_SYNC | LM393 (DIP-8), nguồn 5V0 | 1 | Hai comparator: A = đỏ, B = IR |
| Q_SH_RED, Q_SH_IR | 2N7002 (SOT-23 trên đế chuyển, hoặc BS170 TO-92) | 2 | BS170: R_DS(on) ≤ 5 Ω, chân D-G-S khác 2N7002, kiểm tra chân |
| Rp | 10 kΩ | 2 | cathode → VLED |
| R_d1, R_d2 | 100 kΩ 1 % | 4 | chia đôi cathode |
| R_ref1 / R_ref2 | 100 kΩ / 68 kΩ 1 % | 1 bộ (dùng chung hai kênh) | V_REF ≈ 0.405·VLED |
| R_hys | 2.2 MΩ | 2 | trễ |
| R_pu | 4.7 kΩ | 2 | kéo lên 5V0 |
| C | 100 nF | 1 | khử nhiễu nguồn LM393 |
| JP_SYNC | jumper 3 chân hoặc 2 chân | 2 | gate → GND = chế độ liên tục (OPT101) |

Nối GND chung giữa module MAX30102, ESP32-S3 và board driver (Pi). Dây RD/IRD ngắn, xoắn với GND.

## 6. Ảnh hưởng tới phần mềm và chế độ OPT101

- **OPT101 trong chế độ đồng bộ chỉ thấy ≈ 8 % ánh sáng trung bình** (băng thông OPT101 lấy trung bình
  các xung). Vòng cân bằng AC (`core/ac_balance.py`) và hiệu chuẩn SpO₂ RX dựa trên OPT101 sẽ hiểu sai
  và đẩy AC lên. Trong chế độ đồng bộ: dùng `pi_led_ppg.py` (không có vòng cân bằng) hoặc tắt cân bằng
  AC; không chạy hiệu chuẩn RX.
- JP_SYNC đặt về "liên tục" để trở lại hệ OPT101 như hiện nay mà không tháo mạch.
- Firmware ESP32: giữ `LED_PW = 411 µs`, 200 sps / trung bình 2. LED PA của MAX30102 ≥ 2 mA để cathode
  có mức rõ. Ánh sáng LED của chính MAX30102 phản xạ trong hộp quang chỉ cộng một DC không đổi; dùng
  bề mặt đen mờ hoặc che cửa sổ LED (không che photodiode) nếu DC này quá lớn.

## 7. Cần xác minh trước khi lắp

1. **RD/IRD có đúng là cathode LED không** trên module đang dùng: khi tắt nguồn, đo DMM thông mạch
   RD/IRD tới chân LED_DRV của MAX30102; khi chạy firmware (LED PA 7.2 mA), dao động ký trên RD phải
   thấy xung xuống khoảng `VLED − Vf` dài ≈ 411 µs, lặp mỗi 5 ms. Không dựa vào áp DC đo bằng DMM khi
   chưa có Rp: nút cathode khi tắt là trở kháng cao, DMM tự nó kéo dòng qua LED. Tài liệu module phổ
   biến ghi RD/IRD là cathode nhưng chưa kiểm trên module này.
2. **VLED** của module: đo tại anode LED hoặc chân VIN; chọn lại V_REF nếu khác 3.3 V.
3. Trên board driver: C1a hiện có lắp không, R_sense thực tế (82 Ω bản mẫu, 100 Ω bản v1.9).
4. LM393 nguồn 5V0 và GND chung; ngõ vào comparator không vượt 3.5 V.

## 8. Kế hoạch đo (trên nhánh test)

1. **Không có Pi chạy:** ESP32 chạy firmware, LED PA 7.2 mA. Dao động ký: kênh 1 = RD, kênh 2 = GATE_RED.
   Kiểm tra mỗi xung LED đỏ tạo đúng một xung GATE, độ trễ và độ rộng.
2. **Pi xuất DC cố định** (`pi_led_ppg.py --ac 0`, ví dụ 200/400/600 mV): kênh 3 = TP_RSENSE (dòng LED mô
   phỏng). Đo thời gian lên/xuống so với RD, mức rò khi gate đóng.
3. **So với cửa sổ môi trường:** quét DC như bước 2 và ghi số đếm MAX30102 (serial `S,…`). Nếu đồng bộ đúng,
   số đếm phải tăng gần tuyến tính theo DC (khác hẳn 23/11, khi nó gần như không đổi). Nếu tăng ít hoặc
   bão hòa sớm, ánh sáng mô phỏng còn tràn vào cửa sổ môi trường hoặc lên chậm.
4. **JP_SYNC = liên tục** với cùng DC: phải tái hiện kết quả 23/11 (đối chứng).
5. **PPG 60/75/90/120 bpm**, `--ac` vài mức: so HR của firmware (`R,…`) với HR đặt; ghi lại AC/DC nhận được.
   Đây là kiểm tra kỹ thuật của chuỗi mô phỏng, không phải kiểm định lâm sàng.
6. Kiểm tra cả hai kênh không lẫn nhau: chỉ bật kênh đỏ mô phỏng, kênh IR của MAX30102 không được đổi.

## 9. Rủi ro và điều chưa biết

- Thời điểm lấy mẫu môi trường của MAX30102 so với xung LED: chưa có số liệu, chỉ đo được.
- Đáp ứng thời gian thực của LM358 trong vòng hồi tiếp với transistor: ước tính, chưa đo.
- Vf thực tế của LED trong module và VLED: chưa đo.
- Phương án dự phòng nếu không lấy được RD/IRD: photodiode nhanh (ví dụ BPW34, có board `hardware/bpw34_receiver`)
  nhìn LED của MAX30102 + comparator. Cách này phức tạp hơn và phải tách quang để photodiode thời gian không
  thấy LED mô phỏng.
