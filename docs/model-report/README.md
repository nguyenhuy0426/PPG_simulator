# Báo cáo mô hình (trang web chạy local)

Trang tĩnh giải thích các mô hình tạo tín hiệu PPG trong hệ thống: kiến trúc, nguyên lý, đầu vào/đầu ra,
dữ liệu train, kết quả, kèm sơ đồ và đồ thị tương tác. Không cần Internet, không dùng thư viện ngoài.

`index.html` là bản tóm tắt dễ hiểu (viết tay, số liệu lấy từ `ml/runs/realism-v1/realism_round10.json` và
`docs/physioflow/loop`); `trinh-bay.html` là trang trình bày cho khách hàng (mạng nơ-ron vẽ sóng từng bước, GAN và giám
khảo, PhysioFlow từ nhiễu ra sóng, video train, bước C và D); `chi-tiet.html` là báo cáo kỹ thuật đầy đủ, vẽ từ `data.js`.

Mở trực tiếp `index.html` bằng trình duyệt, hoặc chạy:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory docs/model-report
```

rồi vào http://127.0.0.1:8765.

## Cập nhật số liệu

`data.js` được tạo bởi `scripts/build_model_report.py` từ các model đang nằm trong `assets/neural` (PhysioMix và
PhysioFlow), kết quả đánh giá (`ml/runs/realism-v1/realism_round10.json`: PhysioMix, PhysioFlow, LSM-GAN, Gaussian;
`realism_lsm_narrow.json`: phép đo công bằng cho LSM-GAN), lịch sử train của vòng đang dùng, các vòng lặp PhysioFlow
(`ml/runs/physioflow10*-result-v1`, `physioflow10c-resume-local-v1`) và dữ liệu đã xử lý (`ml/runs/physio3-data-v1`).
Bằng chứng từng vòng PhysioFlow cũng được lưu trong git ở `docs/physioflow/`. Các thư mục `ml/runs` không nằm trong git; cần có chúng trên máy để tạo lại:

```bash
.venv/bin/python scripts/build_model_report.py
```

Khi model trong app đổi vòng, truyền `--run` (lịch sử train), `--realism` và `--app-source` (tên run của model trong app trong file realism) tương ứng. Ảnh
`img/app-rx-rate-synthetic.png` chụp app với luồng RX tổng hợp để kiểm tra hiển thị, không phải đo phần cứng.

## Trang trình bày (`trinh-bay.html`)

Hình tương tác đọc `media/presentation.js`; video MP4 và hình PNG nằm trong `media/`. Tất cả được tạo từ checkpoint
thật (mã băm khớp `assets/neural/manifest.json`) và dữ liệu thật bởi:

```bash
.venv/bin/python scripts/build_presentation_media.py --snapshots PhysioMix=ml/runs/galaxy-d-pilot-result-v1/daily_d/physiomix_d_seed42 --snapshots PhysioFlow=ml/runs/galaxy-d-pilot-result-v1/daily_d/physioflow_d_seed42
```

Cần `ffmpeg` (libx264) và các thư mục `ml/runs` tương ứng. Số liệu bước C/D trên trang viết tay từ
`docs/physioflow/loop/judges_c.json` và `galaxy_d_pilot.json`.
