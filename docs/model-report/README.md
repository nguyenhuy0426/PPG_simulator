# Báo cáo mô hình (trang web chạy local)

Hai trang tĩnh, không cần Internet, không dùng thư viện ngoài:

| Trang | Dành cho | Nội dung |
|---|---|---|
| `trinh-bay.html` | Khách hàng | Ít chữ, nhiều hình: hệ thống, cách tạo sóng, điều khiển nhịp tim, độ giống thật, video train, PPG-physiGPT V1 (tiêu chí đạt mới và bảng bốn mô hình), lộ trình, giới hạn |
| `gan-report.html` | Kỹ thuật | Giám khảo nghiêm, PhysioFlow-GAN và PPG-physiGPT theo bố cục bài LSM-GAN (Ding et al., IEEE JBHI 27(3), 2023) |

Trang khách hàng lấy hình từ `../paper/figures` và `../system_3d/out`, nên cần phục vụ cả thư mục `docs`:

```bash
python3 -m http.server 8766 --bind 127.0.0.1 --directory docs
```

rồi vào http://127.0.0.1:8766/model-report/trinh-bay.html.

Các trang cũ `index.html` (tóm tắt) và `chi-tiet.html` (báo cáo kỹ thuật đầy đủ, kèm `data.js`, `compare75.js`,
`report.js`) đã được gỡ ngày 01/11/2026. Chúng vẫn còn trong lịch sử git.

## Trang khách hàng (`trinh-bay.html`)

- Hình 01–05 là hình của bài báo (`docs/paper/figures`, tạo bởi `docs/paper/make_figures.py` từ bản ghi đánh giá),
  ảnh app (`docs/ui`) và bản dựng 3D (`docs/system_3d/out`).
- `physioflow-tu-nhieu-thanh-song.mp4` được tạo bởi `scripts/build_presentation_media.py` từ checkpoint của app.
  `train-PhysioMix.mp4` và `train-PhysioFlow.mp4` lấy từ `snapshots.npz` của bản thử nghiệm bước D (seed 42), KHÔNG phải
  model trong app (hai lần train của app không lưu snapshot). Mỗi video dừng ở bước được chọn (3 500 và 12 000, điểm
  `checkpoint_score` thấp nhất), có vài khung cuối ghi rõ là không dùng, cạnh là đoạn thật đầu tiên của người
  validation (bỏ `external` và `test`; hàng `wrist_daily` bỏ vì không có sóng thật trong `windows.npz`). Tạo lại bằng
  `--clips-only --snapshots Tên=thư mục`. Script đó còn ghi `media/presentation.js` và
  `media/physiomix-7-buoc.png` cho trang cũ, trang mới không dùng hai file này.
- Mục PPG-physiGPT V1 vẽ bằng `trinh-bay.js` từ `media/report-data.js`, tạo bởi `scripts/build_customer_report.py`
  từ `docs/physigpt/results.json`. Biểu đồ bốn mô hình (khối `benchmark`) dùng cùng 180 người MIMIC và 22 đặc trưng; tiêu chí đạt là trung bình 22 đặc trưng ≥ 0,95, từng đặc trưng ≥ 0,90 (hoặc mức thật-vs-thật nếu thấp hơn), cây ≤ 0,60, và cả bốn mô hình đều chưa đạt. Giám khảo nghiêm không còn là tiêu chí đạt. Số 98,1 % cũ là ngưỡng tương đối trên 14 đặc trưng, nên đã bỏ khỏi trang khách hàng và bản ghi kernel trong `docs/physigpt/evidence/`. Video
  `media/physigpt-hoc-tung-patch.mp4` tạo bởi `scripts/build_physigpt_media.py`.

- Mục đặc trưng sóng, bước train và học vẹt vẽ bằng `trinh-bay-anatomy.js` từ `media/ppg-anatomy.js`, tạo bởi
  `scripts/build_ppg_anatomy.py` bằng chính code chấm điểm (`ml/kaggle_physigpt/judge_physigpt.py`). Script cần `ml/runs`
  và `generated.npy` của kernel sinh mẫu APFT-GAN; bản ghi train nằm ở `docs/physigpt/evidence/ppg-physigpt-apft-gan-v1/`.

## Báo cáo kỹ thuật (`gan-report.html`)

`gan-data.js` được tạo bởi `scripts/build_gan_report.py` từ các vòng giám khảo nghiêm, các vòng train
(`ml/runs/strict-*-result-v1`) và vòng PhysioFlow-GAN. Các model của những vòng đó không cải thiện (AUC 0,95–1,00) nên đã
gỡ cùng script tạo dữ liệu. `gan-data.js` và hình được giữ nguyên làm số liệu; mục P5 và bảng model giữ/loại trên trang
được viết tay.

Tỷ lệ artifact là luật SQI tự viết (`ml/kaggle_multidomain/artifact_sqi.py`), không phải nhãn chuyên gia. Hình 1, 4, 5 và
các thuật toán viết tay từ mã nguồn (mỗi số có ghi file:line trong trang).

Mục PPG-physiGPT viết tay từ `docs/physigpt/results.json` (tạo bởi `docs/physigpt/build_results.py` từ bản ghi kernel
Kaggle trong `docs/physigpt/evidence/`): giám khảo nghiêm (AUC, d′ từ điểm thô) và tầng đặc trưng (1 − KS, bộ phân loại
chỉ nhìn đặc trưng; tiêu chí hiện tại là tuyệt đối trên 22 đặc trưng, ngưỡng tương đối V1 chỉ còn cho các biến thể cũ). Bảng bốn mô hình thêm bằng `benchmark()` trong `build_results.py` từ `evidence/ppg-physigpt-judge-benchmark-generated-v1-fid/`; RSR-FlowGAN ở `evidence/ppg-rsr-flowgan-v1/`. Khi có lần chạy mới, chép bản ghi vào
`evidence/`, thêm biến thể vào `build_results.py`, chạy lại `build_customer_report.py` rồi cập nhật mục này.

Đây là đánh giá kỹ thuật về dáng sóng PPG đã chuẩn hoá, không phải kiểm định lâm sàng, và chưa đo trên Pi/DAC/OPT101.
