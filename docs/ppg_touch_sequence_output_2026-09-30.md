# Điều khiển cảm ứng, lựa chọn GAN sinh chuỗi và phát DAC

Ngày 30/09/2026. Yêu cầu hiện tại cho phép phát MCP4725/LED từ mục 4, thay cho giới hạn preview ở vòng trước. A0 đã gắn OPT101; A2 chưa gắn và bị tắt trong runtime.

## Thay đổi ứng dụng

- Classic dùng slider và nhãn giá trị; giữ bộ sinh Gaussian gốc.
- Settings và Calibration thay ô nhập số bằng slider, nút −/+ và giá trị hiện tại. Auto thay ô trống cho AC RED suy ra từ SpO₂ và seed ngẫu nhiên. Chỉnh Settings được giữ cho đến Apply, không bị cập nhật định kỳ ghi đè.
- Mục 4 có Gaussian fitted và LSM-GAN. Gaussian có HR/notch; GAN giữ thời gian native, không nhận HR/notch giả. Nút sinh đoạn mới lấy seed mới và xuất seed trong metadata.
- GAN suy luận ở tiến trình riêng, chỉ tải G 117.940 tham số; không tải D trong runtime. Không gọi PyTorch trong luồng DAC hoặc Tk. Tiến trình bị dừng nếu quá 120 s hoặc khi thoát app.
- Đối chiếu Gaussian với nhịp train đã xử lý/lặp; đối chiếu GAN với **đoạn train real 30 s** ở 40 Hz, không lặp một nhịp. Có thể chuyển khung phải sang OPT101 A0 thật.
- Phát đoạn hữu hạn 30 s qua một SignalEngine/DAC writer chung. Nội suy 40→100→1000 Hz không tạo thêm băng thông. Hết đoạn, nhấn Dừng, rời mục 4, hoặc đổi nguồn/tham số đều dừng clip và đưa DAC về 0 V. Không nối vòng đoạn GAN gây bước nhảy ở biên.
- Mục 4 có DC 0–1500 mV và AC IR 0–1500 mV. RED dùng cùng hình dạng với AC bằng 0,48×IR; đây là ánh xạ danh định, không phải mô hình PPG IR/RED độc lập được học hoặc SpO₂ đã hiệu chuẩn.
- `RX_ENABLED_CHANNELS=(0,)`: đọc Grove 0x08/A0; A2 có trạng thái disabled, không tạo mẫu/giá trị thay thế. Constructor RX vẫn cho phép explicit `(0,2)` khi có đủ cảm biến.
- Classic recording không dùng cho clip GAN vì HR/SpO₂ setpoint của Classic không mô tả chuỗi GAN. Dùng xuất CSV waveform kèm metadata; script bench lưu TX commanded và RX A0 riêng.

## Lựa chọn kiến trúc

**Chọn LSM-GAN làm nền sinh chuỗi trong ứng dụng hiện tại**, không tuyên bố đó là kiến trúc tối ưu trên mọi dataset. Lý do là mục tiêu sinh đoạn PPG nhiều nhịp với timing/biên độ biến thiên, đã có checkpoint tái lập, G nhỏ và đường suy luận ARM64. Đây là lựa chọn theo nhiệm vụ và khả năng triển khai, không phải thắng mọi metric.

| Hướng | Phù hợp với yêu cầu này | Quyết định |
|---|---|---|
| LSM-GAN | Noise dài → chuỗi PPG, kết hợp loss phổ; nghiên cứu gốc nhắm augmentation cho AF | Chọn làm nền, v2 vẫn thăm dò |
| TimeGAN | Học embedding và động học thời gian bằng mục tiêu giám sát + adversarial | Đối chứng phù hợp nếu triển khai thí nghiệm mới; chưa có kết quả PPG local để kết luận tốt hơn |
| cWGAN/TCN-FiLM một nhịp hiện tại | Chuẩn hóa pha 256 điểm rồi lặp làm mất chuỗi khoảng nhịp tự nhiên | Giữ backend nghiên cứu, không chọn làm nguồn chuỗi |
| PulseGAN / CardioGAN | Lần lượt tái tạo rPPG từ tín hiệu đầu vào và chuyển PPG→ECG | Không đúng tác vụ noise→PPG tự do |
| PPG-CAGAN 2026 | Chủ đề PPG CAD có liên quan | Chỉ truy cập được tóm tắt; không đủ căn cứ để thay mô hình đã có |

Nguồn gốc đã kiểm tra: [LSM-GAN, arXiv v2/full text](https://arxiv.org/html/2108.05272v2), [mã tác giả](https://github.com/chengding0713/Log-Spectral-matching-GAN), [TimeGAN, NeurIPS 2019](https://papers.neurips.cc/paper_files/paper/2019/hash/c9efe5f26cd17ba6216bbe2a7d26d490-Abstract.html), [mã TimeGAN](https://github.com/jsyoon0823/TimeGAN), [PulseGAN](https://arxiv.org/abs/2006.02699), [CardioGAN](https://arxiv.org/abs/2010.00104), [PPG-CAGAN, trang nhà xuất bản](https://www.sciencedirect.com/science/article/pii/S1746809426005185). Đây là rà soát có giới hạn, không bao quát mọi công trình. Parallel CLI không có sẵn; sử dụng truy cập web trực tiếp đến nguồn sơ cấp.

## Dữ liệu và đo bổ sung thực tế

Checkpoint v2 đã học từ **624 cửa sổ train 30 s thuộc 32 người**; validation 112 cửa sổ/7 người; test 112 cửa sổ/7 người. Không train gộp test: “học toàn dataset” phải được hiểu là khai thác phân bố các đoạn trong tập train, giữ người độc lập để đánh giá. Chưa có checkpoint mới huấn luyện lại trong lượt này.

Dataset BIDMC có 53 bản ghi nhưng 46 ID người trong split hiện tại. Không phải cohort người khỏe mạnh, không có nhãn AF được dùng để train. Tiền xử lý v2 resample 125→40 Hz, FIR 0,9–5 Hz, chuẩn hóa toàn cửa sổ. Điều này hạn chế khả năng học hô hấp/baseline chậm và chi tiết notch cao tần; không được gọi là học nguyên vẹn PPG raw.

Audit bổ sung dùng checkpoint cố định, 64 seed 1000–1063 so với toàn validation. Không lựa chọn checkpoint hoặc seed theo hình đẹp. Kết quả ở [metrics.json](sequence-audit/metrics.json), tái lập bằng `.venv/bin/python -m ml.sequence_audit`.

| Phép đo | Real validation | LSM v2 | Gaussian cố định 75 bpm |
|---|---:|---:|---:|
| RMSE ACF trung bình | tham chiếu | 0,25732 | 0,56195 |
| RMSE log-PSD trung bình | tham chiếu | 1,76778 | 2,06725 |
| Năng lượng >5 Hz (%) | 0,000316 | 0,019227 | 0,274651 |
| Trung vị CV khoảng đỉnh | 0,05940 | 0,20241 | ≈0 |
| Trung vị CV biên độ đỉnh | 0,08146 | 0,15599 | 0 |

GAN có biến thiên thật trong đầu ra số, nhưng khoảng nhịp biến thiên quá nhiều so với trung vị validation. Năng lượng cao tần vẫn lệch đáng kể. **Chưa đủ bằng chứng để gọi v2 là PPG người trung thực nhất.** Gaussian 75 bpm là control cố định, không được ghép phân bố HR với dataset; bảng không phải xếp hạng GAN toàn diện. Phát hiện đỉnh dùng khoảng cách ≥250 ms và prominence 0,15 trên tín hiệu chuẩn hóa, là phép đo heuristic; 30 s không đại diện HRV dài hạn.

Ba tiêu chí đã chốt vẫn là **độ giống phổ, tự tương quan, năng lượng tần số cao**. CV khoảng nhịp/biên độ chỉ bổ sung cho mục tiêu mới. Không chọn bằng loss hoặc D. So sánh **thăm dò vì test đã được xem**; kết quả cWGAN một nhịp và LSM đoạn dài ở các vòng trước không hoàn toàn ngang bằng.

Muốn tiến tới mô phỏng người tốt hơn cần vòng train mới trên các đoạn liên tiếp, split theo người, tiền xử lý giữ thành phần hô hấp và notch cần thiết, đánh giá phân bố khoảng nhịp/biên độ/hình thái và kiểm tra sao chép train. Có thể bổ sung conditioning HR/rhythm khi có nhãn đáng tin, nhưng phải train lại; không giả lập conditioning bằng kéo giãn tùy ý đầu ra hiện tại. Không có nhãn bệnh thì không gán nút “AF/bình thường” cho các seed.

## Kiểm thử và triển khai

- Pytest tại laptop: 734 passed, 1 skipped, 288 subtests trước bổ sung kiểm thử tham chiếu chuỗi; kết quả cuối xem log triển khai.
- GUI dry-run đã kiểm tra 1024×600 và 1280×800, vi/en, slider/Auto, sửa Settings không bị ghi đè, suy luận LSM tiến trình riêng, phát/dừng và rời trang, tham số Classic được giữ nguyên.
- I²C scan Pi thấy 0x08, 0x60, 0x61. ACK chỉ chứng minh thiết bị trên bus.
- Script `scripts/verify_waveform_hardware.py` phát 30 s và thu A0 trước/trong/sau; luôn park DAC trong finally. CSV TX là điện áp lệnh, không phải điện áp/LED đã đo bằng oscilloscope.
- Runtime: `.venv/bin/python main.py --page Neural`; không tự phát khi mở.
- Đo phần cứng và trạng thái triển khai được cập nhật riêng sau khi chuyển bản commit sang Pi.
