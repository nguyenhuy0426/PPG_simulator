# Vòng 11: PhysioFlow-2 (IR + đỏ) và nhịp theo khoảng

Ngày 2026-10-21. Nhánh `claude/model-benchmark-physioflow2`, tách từ `claude/model-benchmark-physioflow-wrist-e-stopfix`.
Mọi luật quyết định được ghi trong code và commit **trước khi** chạy phần tương ứng (xem commit log). Phần
đánh giá dùng validation; tập test chỉ dùng cho luật nhịp số 2 (chưa từng dùng cho câu hỏi về nhịp).

## 1. Dữ liệu 2 kênh (pack `ppg_physioflow2_v4`)

- IR giữ nguyên view v3, nên mọi tiêu chí cũ vẫn áp dụng được.
- Kênh đỏ được lưu **tương đối với IR**:
  - red = R·(red_view − mean), với R = (ptp(AC_đỏ)/DC_đỏ)/(ptp(AC_IR)/DC_IR) tính trên dữ liệu thô.
  - Vì ptp(IR) = 1 nên ptp(red) = R. Đây là tỉ số quang học của thiết bị, **không phải nhãn SpO₂**.
- **FINGER:** 2.518 cửa sổ có kênh đỏ (660/940 nm), R trung vị 0,69. Mọi cửa sổ IR dựng lại đều khớp hàng
  trong pack (tương quan > 0,99).
- **PTT** (PhysioNet 1.0.0, MAX30101, đốt xa):
  - Dựng lại thành 3 bối cảnh: `ptt_sit`, `ptt_walk`, `ptt_run`. Tổng 1.059 cửa sổ, chia theo người 16/3/3,
    R trung vị khoảng 0,45 (660/880 nm).
  - Thứ tự kênh IR/đỏ trong README tự mâu thuẫn. Mình suy ra IR = pleth_2, đỏ = pleth_1 vì R(pleth_1/pleth_2)
    nhỏ hơn 1 ở mọi bản ghi ngồi, đúng với SpO₂ 96–99% ghi trong header. Đây là suy luận kỹ thuật, chưa được
    tác giả xác nhận.
  - Dữ liệu tải từ bản sao `physionet-open` trên S3, kiểm tra SHA-256 theo danh sách chính thức (198/198 file).
- Các cửa sổ PTT cũ của v3 bị loại: thực ra đó là kênh pleth_1 (đỏ) nhưng đã bị dùng như IR.
- Các tập khác chỉ có IR (`red_known = False`).

## 2. Kiến trúc và quy trình (RULE_11)

- **Hai backbone:**
  - **U2:** U-Net 2 kênh, 6,93 M tham số, khoảng 0,79 s/strip trên một luồng CPU laptop.
  - **T2:** DiT-1D, 9,83 M tham số, khoảng 0,82 s/strip. Gồm 150 patch dài 8 mẫu, điều kiện adaLN-zero,
    cộng một lớp tích chập tinh chỉnh khởi tạo bằng 0.
- **Công thức F10 trên mỗi kênh:** thời gian flow đều, loss sai phân bậc 1 trọng số 1, loss stop-band trọng số 0,1.
  Loss kênh đỏ chỉ tính ở các cửa sổ có kênh đỏ.
- **Vector điều kiện:** 16 slot dataset dự phòng, để thêm tập mới mà không đổi kích thước đầu vào. Sau đó là
  R_known và R, rồi đến 5 trường v2 như cũ.
- **So sánh được với các vòng trước:** tiêu chí khoá (S_real, C, C2ST → S_arm) chỉ tính trên 6 tập gốc.
  Evaluator đã được kiểm tra giống hệt vòng 10 (chuẩn hoá, băng thông, pool tham chiếu, replay).
- **Chỉ số kênh đỏ:** sai số R, và C2ST 2 kênh so với baseline "copy IR" (đỏ = R·IR, cách ứng dụng đang làm).
- **Luật:** pilot với seed 42 chọn U2 hoặc T2, sau đó final 3 seed.
  - **D1:** thay PhysioFlow F6 ở chế độ nghiên cứu.
  - **D2:** thay PhysioMix R9 làm mặc định của ứng dụng.
  - Nội dung đầy đủ nằm trong `RULE_11` (`ml/kaggle_multidomain/experiment_dual.py`).
- **Kaggle:** kernel `halovie2412/ppg-physioflow2-dual-v1` (private, 2×T4), dataset
  `halovie2412/ppg-physioflow2-data-v4` (private).

### Kết quả vòng 11 (Kaggle 2×T4, 4,85 giờ; `docs/physioflow2/rules/`, `docs/physioflow2/round11/`)

| | S_arm | S_real | Wrist Q | Sai số R (trung vị) | C2ST 2 kênh: model / copy IR (%) |
|---|---|---|---|---|---|
| Pilot U2 (seed 42) | 0,531 | 0,390 | 0,80 | 0,028 | 24,2 / 19,6 |
| Pilot T2 – DiT (seed 42) | 1,032 | 0,763 | 1,99 | 0,024 | 47,7 / 35,2 |
| Final U2 (3 seed) | 0,564 ± 0,078 | 0,418 | 0,83 | khoảng 0,025 | 26,9 / 22,1 |
| *Đối chiếu: PhysioFlow F6* | *0,482* | *0,368* | *0,79* | — | — |
| *Đối chiếu: PhysioMix R9* | *0,530* | *0,344* | *0,53* | — | — |

**Quyết định:** D1 = không, D2 = không, nên không triển khai gì.

- **Lý do D1 không đạt:**
  - S_arm kém hơn F6 quá biên cho phép.
  - Wrist Q 0,83 lớn hơn ngưỡng 0,587.
  - Kênh đỏ hơn baseline "copy IR" 4,9 điểm, chưa đủ biên 8,4 điểm.
- **Điểm mạnh:** R được điều khiển rất chính xác (Spearman 0,91, sai số khoảng 0,025).
- **Chẩn đoán:** ở cả 4 lần chạy, checkpoint tốt nhất là bước cuối (20.000) và điểm vẫn đang giảm, tức là model
  chưa hội tụ. DiT học chậm hơn hẳn.

Vòng 12 (`RULE_12`, viết trước khi train): U2 train 32.000 bước, 3 seed, giữ nguyên D1/D2. Nếu D1 vẫn không đạt
thì **dừng tinh chỉnh trên tập validation này**; mọi thay đổi tiếp theo cần người validation mới.

### Kết quả vòng 12 (Kaggle 2×T4, 7,14 giờ; `docs/physioflow2/rules/DECISION_12.json`, `docs/physioflow2/round12/`)

| | S_arm | S_real | Wrist Q | Sai số R (trung vị) | R Spearman | C2ST 2 kênh: model / copy IR (%) |
|---|---|---|---|---|---|---|
| U2 seed 42 | 0,462 | 0,349 | 0,71 | 0,027 | 0,94 | 27,1 / 21,9 |
| U2 seed 123 | 0,519 | 0,404 | 0,85 | 0,024 | 0,93 | 30,6 / 28,5 |
| U2 seed 2026 | 0,490 | 0,355 | 0,59 | 0,020 | 0,89 | 24,4 / 20,6 |
| **Final U2 (3 seed)** | **0,491 ± 0,028** | 0,369 | 0,71 | khoảng 0,024 | — | 27,4 / 23,7 |
| *Vòng 11 U2 (20.000 bước)* | *0,564 ± 0,078* | *0,418* | *0,83* | *khoảng 0,025* | *0,91* | *26,9 / 22,1* |
| *Đối chiếu: PhysioFlow F6* | *0,482* | *0,368* | *0,79* | — | — | — |
| *Đối chiếu: PhysioMix R9* | *0,530* | *0,344* | *0,53* | — | — | — |

**Quyết định:** D1 = không, D2 = không, nên không triển khai gì.

- **Đạt:**
  - Mọi seed qua gate (finite, trace, latency).
  - Sai số R ≤ 0,05.
  - S_arm 0,491 nằm trong biên so với F6 (0,482 + 0,023).
  - Ba kiểm tra riêng của D2 cũng đạt. D2 vẫn là "không" vì D2 cần D1.
- **Không đạt:**
  - Wrist Q trung bình 0,71 lớn hơn ngưỡng 0,587. Seed 2026 đạt 0,587, nhưng luật tính trên trung bình 3 seed.
  - Kênh đỏ chỉ hơn baseline copy IR 3,7 điểm, cần hơn 8,5 điểm.
- **Train dài hơn có giúp không:**
  - S_arm giảm từ 0,564 xuống 0,491 và độ lệch giữa các seed giảm từ 0,078 xuống 0,028.
  - Hai seed có checkpoint tốt nhất ở bước 32.000 (seed 2026 ở bước 30.000). Điểm checkpoint gần như đã chững lại (seed 42: 0,378 ở bước 28k, 0,361 ở bước 32k).
  - Kênh đỏ không cải thiện so với baseline copy IR. Phần còn thiếu nằm ở kênh đỏ, không phải do model chưa hội tụ.
- **GPU:**
  - Seed 42 và 2026 chạy nối tiếp trên `cuda:0` (12.559 s + 12.515 s).
  - Seed 123 chạy trên `cuda:1` (13.138 s), nên `cuda:1` rảnh khoảng 3,4 giờ.

**Theo `RULE_12`:** vì D1 không đạt, **dừng tinh chỉnh PhysioFlow-2 trên tập validation này**. Ứng dụng giữ nguyên PhysioMix R9 (mặc định) và PhysioFlow F6 (chế độ nghiên cứu). Mọi thay đổi tiếp theo, ví dụ loss riêng cho kênh đỏ hay thêm dữ liệu đỏ, cần người validation mới.

### Chẩn đoán kênh đỏ sau vòng 12 (laptop, U2 seed 42, 256 cửa sổ validation có kênh đỏ; chỉ để định hướng)

- **C2ST 2 kênh đo chủ yếu IR.** AUC khi chỉ nhìn IR (đỏ = R·IR ở cả thật lẫn giả) là 0,856; với model là 0,877;
  với copy IR là 0,874. Đối chứng thật–thật là 0,50. Kênh đỏ chỉ đóng góp khoảng 0,02 AUC, nên điều kiện "đỏ hơn
  copy IR > 8,5 điểm" của D1 gần như không thể đạt bằng cách cải thiện kênh đỏ.
- **Trên view v3, đỏ thật ≈ R·IR + phần dư nhỏ:** phần dư bằng 3–6% độ lệch chuẩn của IR (1 − r² chỉ 0,005–0,026),
  phần lớn nằm ở dải nhịp tim. Probe chỉ nhìn phần dư phân biệt được model vòng 12 với thật hoàn toàn (AUC 1,0).
  - Phần dư dưới 0,5 Hz của model lớn gấp 2–8 lần thật.
  - Ở `ptt_run`, model thiếu thành phần 4–8 Hz.
  - Ở `ptt_walk`, phần dư của model quá nhỏ (0,029 so với 0,063).
- **Khối đỏ thử nghiệm** (`ml/kaggle_multidomain/red_head.py`, 2,8 M tham số, 6.000 bước, 69 phút trên CPU laptop).
  Khối này giữ nguyên IR, chỉ sinh phần dư từ (IR, R, dataset), và ptp(đỏ) = R chính xác.
  - Điểm phần dư (độ lớn và công suất 4 dải; 0 là khớp thật): khối đỏ 0,141; nhiễu màu 0,165; copy IR 9,09.
  - Probe nhìn cả (IR, phần dư), AUC: khối đỏ 0,73 (3 seed probe 0,65 / 0,82 / 0,73); nhiễu màu 1,00.
  - Điểm yếu nhất vẫn là `ptt_walk`.
  - Người validation này đã dùng ở vòng 11–12, nên đây chỉ là khám phá. Vòng 13 cần người validation mới
    (OpenOximetry, chỉ lưu trên laptop theo thỏa thuận dữ liệu PhysioNet).

## 3. Nhịp theo khoảng nhịp tim (RULE_RHYTHM, RULE_RHYTHM_2)

- **R0:** IBI log-normal độc lập (scaffold hiện tại). σ chọn sao cho 5–95% nhịp tức thời nằm trong [lo, hi].
- **R1:** AR(p ≤ 4) trên log-IBI, khớp riêng cho từng dataset từ các cửa sổ train.
- **R1c:** R1 có căn tâm lại trên các nhịp nằm trong cửa sổ 30 s.

| Luật | Tập | R0 | R1 / R1c | Sai số nhịp (R1/R1c) | Guard trên model triển khai | Quyết định |
|---|---|---|---|---|---|---|
| RULE_RHYTHM | validation | 0,431 | 0,311 (−28%) | 0,013 bpm | **Không đạt**: 1,38 / 1,52 bpm > 1 | Giữ R0 |
| RULE_RHYTHM_2 | test | 0,555 | 0,368 (−34%) | 0,009 bpm | Đạt (tương đối): PhysioMix 1,41 so với R0 2,08; PhysioFlow 0,95 so với R0 1,41 | **R1c** |

Chẩn đoán sau luật 1 (chỉ để hiểu nguyên nhân, không thay đổi quyết định):

- Chuỗi AR căn tâm trên 160 nhịp có trung bình trong cửa sổ trôi khỏi lệnh 0,25–2,2 bpm.
- Bộ đếm đỉnh đo sai khoảng 4,6 bpm trên strip cổ tay, bất kể dùng mô hình nhịp nào.

Luật 2 được viết sau chẩn đoán và **trước khi chạy**, trên tập test.

Ngoại lệ: trên MIMIC-AF, R0 tốt hơn (0,13 so với 0,23). Mô hình AR tuyến tính không mô tả được nhịp rung nhĩ;
cần một mô hình nhịp riêng cho AF.

Tích hợp:

- `PhysioMixGenerator.generate(..., hr_range=(lo, hi))` và `sequence_worker --hr-range LO HI`.
- Trang Neural có thêm thanh "HR ± / bpm".
- Không cần train lại: chuỗi IBI được ghi vào đúng các vị trí nhiễu mà model đang đọc (`core/rhythm_range.py`,
  `assets/neural/rhythm_r1c.json`).
- Bằng chứng: `docs/physioflow2/rhythm/`.

## Những gì chưa kiểm chứng

- Chưa chạy gì trên Raspberry Pi.
- R là tỉ số quang học của 2 thiết bị trên người khoẻ. Dải SpO₂ hẹp (khoảng 96–99%), nên model **chưa** dùng để
  kiểm thử SpO₂ được; cần OpenOximetry (PhysioNet, phải đăng ký) cho dải 70–100%.
- Mô hình nhịp học từ khoảng cách đỉnh PPG, không phải từ ECG.
