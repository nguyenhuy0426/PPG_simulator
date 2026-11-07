# PSF-GAN FP32 FT v1 — bản mô phỏng thử nghiệm

Nguồn: [Kaggle version 1 / script 365965110](https://www.kaggle.com/code/charlesday2612/ppg-physigpt-psf-gan-fp32-ft-v1).
Checkpoint EMA được chọn ở bước 500; train dừng vì patience ở 4.500 bước, không có bước lỗi số học hoặc rollback.

| Phép kiểm tra | Kết quả |
|---|---:|
| Selection trên dữ liệu train | 94,17% |
| Test: trung bình 22 × (1−KS) | 93,54% |
| Thật so với thật | 95,83% |
| Tree accuracy thật/giả | 94,25% |
| Strict judge AUC | 0,99999875 |

Người dùng chấp nhận tiếp tục thử nghiệm từ điểm selection 94,17%. Báo cáo tự động vẫn là **fail** theo tiêu chí cũ, được giữ nguyên trong `evaluation.json`. Model chưa tạo được phân bố không phân biệt với dữ liệu thật; chưa kiểm định lâm sàng.

## Runtime

- `generator.ts`: TorchScript CPU, 7.218.900 tham số; chỉ generator, không cần discriminator để sinh sóng.
- Input: z float32 `[1,128]`, HR yêu cầu float32 `[1]` trong 40–180 bpm, noise float32 `[1,6,1600]`.
- Output: float32 `[1,1200]`, 40 Hz, 30 giây, chuẩn hóa [0,1]. Batch runtime cố định là 1; không dùng trace này cho batch khác.
- `core.psf_preview.PSFSequenceGenerator` kiểm tra checksum, seed, HR và đầu ra; không truy cập I2C/DAC/sensor. UI sinh sóng trong tiến trình riêng, chỉ phát khi người dùng nhấn nút.
- HR là điều kiện yêu cầu, không bảo đảm HR đo từ sóng bằng đúng giá trị đó. Không có điều khiển notch, chẩn đoán bệnh lý hoặc SpO₂.
- IR/RED trong ứng dụng được suy từ cùng một sóng với biên độ danh định; không phải hai kênh sinh lý đo thật hoặc mô hình quang học đã hiệu chuẩn.
- `real_train_strip.json`: một đoạn MIMIC-III Waveform Database thuộc split train, 0,5–8 Hz và min-max; chỉ để tham khảo, không ghép cặp với sóng sinh. Nguồn dữ liệu: https://physionet.org/content/mimic3wdb/1.0/ .

## Kiểm chứng và triển khai

Đã so sánh exporter với generator gốc bằng đúng noise: khớp chính xác trên CPU. Trace/eager khớp ở HR 40/75/120/180. Runtime local x86_64 PyTorch 2.10.0 đã kiểm tra 8 trường hợp HR/seed, tính lặp lại, miền giá trị, cấu trúc JSON worker và chuyển sang clip 30 giây. Xem `runtime-checks.json`.

Trong app: Neural → **PSF-GAN · thử nghiệm** → chọn HR → **Sinh đoạn mới**. Đổi HR yêu cầu sinh lại; đổi DC/AC chỉ đổi điện áp, giữ nguyên hình dạng. Gaussian và LSM vẫn có lựa chọn riêng.

Pi 4 ARM64 RAM4 GB, PyTorch2.5.1 đã nạp TorchScript và sinh đủ1.200 mẫu trong UI (staged smoke khoảng8,6s gồm nạp model). GUI được kiểm tra bằng dry-run. Bản UI Pi đã được ghép theo code riêng của Pi, giữ Gaussian/LSM. Xem pi-deployment.json và báo cáo triển khai để biết kiểm tra sau cài và vị trí sao lưu.

Chưa đo DAC, LED, OPT101 hoặc đường quang bằng model này. Deployment-manifest.json cũ mô tả gói delta trên laptop, không đại diện hash các file UI đã ghép riêng cho Pi.
