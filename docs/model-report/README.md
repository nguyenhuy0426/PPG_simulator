# Báo cáo mô hình (trang web chạy local)

Trang tĩnh giải thích các mô hình tạo tín hiệu PPG trong hệ thống: kiến trúc, nguyên lý, đầu vào/đầu ra,
dữ liệu train, kết quả, kèm sơ đồ và đồ thị tương tác. Không cần Internet, không dùng thư viện ngoài.

`index.html` là bản tóm tắt dễ hiểu (viết tay, số liệu lấy từ `ml/runs/realism-v1/realism_round10.json` và
`docs/physioflow/loop`); `trinh-bay.html` là trang trình bày cho khách hàng (mạng nơ-ron vẽ sóng từng bước, GAN và giám
khảo, PhysioFlow từ nhiễu ra sóng, video train, bước C, D và E); `chi-tiet.html` là báo cáo kỹ thuật đầy đủ, vẽ từ `data.js`
(riêng mục 9, bài thi GalaxyPPG và các bước A–E, viết tay từ file bằng chứng; xem cuối trang này).

Mở trực tiếp `index.html` bằng trình duyệt, hoặc chạy:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory docs/model-report
```

rồi vào http://127.0.0.1:8765.

## Cập nhật số liệu

`data.js` được tạo bởi `scripts/build_model_report.py` từ PhysioMix và PhysioFlow khi hai model này còn trong app. Hai model
đã được gỡ khỏi app (strict judge vẫn tách được chúng ở AUC 0,99–1,00), nên script tạo dữ liệu cũng đã gỡ theo; `data.js`
được giữ nguyên làm số liệu lịch sử. Muốn tạo lại thì lấy script và model từ lịch sử git.

Ảnh
`img/app-rx-rate-synthetic.png` chụp app với luồng RX tổng hợp để kiểm tra hiển thị, không phải đo phần cứng.

## Trang trình bày (`trinh-bay.html`)

Hình tương tác đọc `media/presentation.js`; video MP4 và hình PNG nằm trong `media/`. Tất cả được tạo từ checkpoint
thật (mã băm khớp `assets/neural/manifest.json`) và dữ liệu thật bởi:

```bash
.venv/bin/python scripts/build_presentation_media.py --snapshots PhysioMix=ml/runs/galaxy-d-pilot-result-v1/daily_d/physiomix_d_seed42 --snapshots PhysioFlow=ml/runs/galaxy-d-pilot-result-v1/daily_d/physioflow_d_seed42
```

Cần `ffmpeg` (libx264) và các thư mục `ml/runs` tương ứng. Số liệu bước C/D/E trên trang viết tay từ
`docs/physioflow/loop/judges_c.json`, `galaxy_d_pilot.json` và `galaxy_e.json`.

## Mục 9 của `chi-tiet.html` (GalaxyPPG, bước A–E)

Số liệu viết tay, không qua `data.js`: bước A từ `ml/runs/fresh-galaxy-result-v1/fresh_galaxy.json` (không nằm trong git),
bước B, B-LSM, C, D, E từ `docs/physioflow/loop/galaxy_b_pilot.json`, `lsm_galaxy.json`, `judges_c.json`,
`galaxy_d_pilot.json`, `galaxy_e.json`; luật ở `docs/physioflow/rules/`. Khi có bước mới, cập nhật mục này cùng
`index.html`, `trinh-bay.html` và `docs/physioflow/REPORT_VI.md`.

## Giám khảo nghiêm và PhysioFlow-GAN (`gan-report.html`)

Bố cục theo bài LSM-GAN (Ding et al., IEEE JBHI 27(3), 2023): Bảng I–IV, Hình 1–9, Thuật toán 1–3. `gan-data.js` được tạo bởi `scripts/build_gan_report.py`
từ các vòng giám khảo nghiêm, các vòng train (`ml/runs/strict-*-result-v1`) và vòng PhysioFlow-GAN. Các model của những
vòng đó không cải thiện (AUC 0,95–1,00) nên đã gỡ cùng script tạo dữ liệu. `gan-data.js` và hình được giữ nguyên làm số
liệu; mục P5 và bảng model giữ/loại trên trang được viết tay.

Tỷ lệ artifact là luật SQI tự viết (`ml/kaggle_multidomain/artifact_sqi.py`), không phải nhãn chuyên gia. Hình 1, 4, 5 và
các thuật toán viết tay từ mã nguồn (mỗi số có ghi file:line trong trang).
