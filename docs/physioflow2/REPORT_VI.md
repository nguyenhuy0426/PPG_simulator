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

Kết quả: *đang chạy; sẽ cập nhật khi kernel xong.*

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
