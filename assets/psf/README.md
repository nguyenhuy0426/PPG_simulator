# PSF J3 — baseline chính thức của dự án (2026-11-12)

J3 là lựa chọn mặc định chính thức của dự án theo yêu cầu người dùng và quy tắc thay thế đã khóa: không giảm trung bình similarity. Đây vẫn là **mô phỏng thử nghiệm**, không phải model đạt toàn bộ tiêu chí realism hay đã kiểm định lâm sàng.

- Generator: `generator.ts`, checkpoint EMA bước **5500**, SHA256 `cc550e4a0e4279ab0b93aa19b920d488e9fa0402c148764691e38aa7f28941b4`.
- Nguồn: https://www.kaggle.com/code/halovie2412/ppg-physigpt-psf-j3-v1 .
- Held-out: mean 22 × (1−KS) **94,94%**, LogisticRegression real/fake accuracy **53,8%**, AUC **0,5562395**; Trees accuracy **66,625%**, AUC **0,73839225**. Các chỉ số classifier này là kết quả lịch sử từ `target.json`, dùng rank AUC cũ có xử lý điểm hòa khác evaluator sklearn hiện tại; mục tiêu phân biệt ở mức ngẫu nhiên là accuracy 50% và AUC 0,5. Similarity không phải accuracy của thiết bị.
- Verdict **fail**, `accepted_global_target=false`, `clinical_validation=false` được giữ nguyên. Mean chưa đạt 95%; tree vượt mức tối đa 60%.
- J4/J5 có tree thấp hơn nhưng mean 94,91% giảm so với J3. J6 chọn bước 0, có 84 tensor generator trùng J4/J5 và HR bank khác; mean 95,44% không chứng minh cải thiện trọng số, tree 64,05% vẫn fail. Không có model thắng mọi tiêu chí.

`manifest.json`, `evaluation.json`, `target.json` và `official_selection.json` mô tả J3. Báo cáo model cũ đã được giữ trong bản sao lưu, không dùng để xác nhận J3. Lịch sử đánh giá và phân tích so sánh nằm tại `runs/pi-models-20261111/RELEASE_AUDIT.md` trong checkout nguồn.

## Runtime và giới hạn

TorchScript CPU: z float32 `[1,128]`, HR float32 `[1]` trong 40–180 bpm, noise float32 `[1,6,1600]`; output `[1,1200]` tại 40 Hz (30 giây), chuẩn hóa [0,1]. Batch runtime là 1. HR là điều kiện yêu cầu, không bảo đảm HR đo bằng đúng giá trị đó. `core.psf_preview.PSFSequenceGenerator` kiểm tra checksum và dữ liệu trước khi tạo clip; app chỉ phát khi người dùng yêu cầu.

IR/RED được suy từ cùng một sóng với biên độ danh định; không phải hai kênh sinh lý đo thật hay mô hình quang học đã hiệu chuẩn. `real_train_strip.json` là tham khảo MIMIC-III thuộc split train, không ghép cặp với tín hiệu sinh.

Kiểm tra Pi ARM64 trước đăng ký đã nạp J3 và so sánh bốn HR 40/75/120/180: sai số cực đại 1,3232231e-5 so với fixture host, dưới 1e-4. Range worker 10 cửa sổ hoàn thành 12,42 s. GUI dry-run đã pass; các kết quả này không xác nhận DAC/LED/OPT101, chất lượng quang học hoặc hiệu năng lâm sàng. Chi tiết và thời điểm đo nằm trong `docs/hardware-validation/2026-11-12-pi-range/README.md`.

Chính sách đánh giá mới chỉ dùng classifier trên feature; raw waveform strict judge bị vô hiệu hóa cho các lần đánh giá sau. Việc bỏ phép đo không cải thiện model: J3 vẫn fail tiêu chí toàn cục, trong đó tree accuracy vượt ngưỡng 60%. Báo cáo và dữ liệu nghiên cứu lịch sử được giữ nguyên.
