# Điều khiển cảm ứng, lựa chọn GAN sinh chuỗi và phát DAC

Ngày 30/09/2026. Yêu cầu hiện tại cho phép phát MCP4725/LED từ mục 4, thay cho giới hạn preview ở vòng trước. A0 đã gắn OPT101; A2 chưa gắn và bị tắt trong runtime.

## Thay đổi ứng dụng

- Classic dùng slider và nhãn giá trị; giữ bộ sinh Gaussian gốc.
- Settings và Calibration thay ô nhập số bằng slider, nút −/+ và giá trị hiện tại. Auto thay ô trống cho AC RED suy ra từ SpO₂ và seed ngẫu nhiên. Chỉnh Settings được giữ cho đến Apply, không bị cập nhật định kỳ ghi đè.
- Mục 4 có Gaussian fitted và LSM-GAN. Gaussian có HR/notch; GAN giữ thời gian native, không nhận HR/notch giả. Nút sinh đoạn mới lấy seed mới và xuất seed trong metadata.
- GAN suy luận ở tiến trình riêng, chỉ tải G 117.940 tham số; không tải D trong runtime. Không gọi PyTorch trong luồng DAC hoặc Tk. Tiến trình bị dừng nếu quá 120 s hoặc khi thoát app.
- Đối chiếu Gaussian với nhịp train đã xử lý/lặp; đối chiếu GAN với **đoạn train real 30 s** ở 40 Hz, không lặp một nhịp. Có thể chuyển khung phải sang OPT101 A0 thật.
- Phát đoạn hữu hạn 30 s qua một SignalEngine/DAC writer chung. Bản Pi dùng nội suy 40→100→500 Hz; nội suy không tạo thêm băng thông. Hết đoạn, nhấn Dừng, rời mục 4, hoặc đổi nguồn/tham số đều dừng clip và đưa DAC về 0 V. Không nối vòng đoạn GAN gây bước nhảy ở biên.
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

Audit bổ sung dùng checkpoint cố định, 64 seed 1000–1063 so với toàn validation. Không lựa chọn checkpoint hoặc seed theo hình đẹp. Kết quả ở [metrics.json](sequence-audit/metrics.json), [hình so sánh](sequence-audit/comparison.png) và [PDF](sequence-audit/comparison.pdf), tái lập bằng `.venv/bin/python -m ml.sequence_audit` trong môi trường `requirements/ml.txt`.

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

- Pytest cuối tại laptop: **736 passed, 1 skipped, 288 subtests**; [log](hardware-validation/2026-09-30/pytest.txt).
- GUI dry-run đã kiểm tra 1024×600 và 1280×800, vi/en, slider/Auto, sửa Settings không bị ghi đè, suy luận LSM tiến trình riêng, phát/dừng và rời trang, tham số Classic được giữ nguyên.
- I²C scan Pi thấy 0x08, 0x60, 0x61. ACK chỉ chứng minh thiết bị trên bus.
- Script `scripts/verify_waveform_hardware.py` phát 30 s và thu A0 trước/trong/sau; luôn park DAC trong finally. CSV TX là điện áp lệnh, không phải điện áp/LED đã đo bằng oscilloscope.
- Runtime: `.venv/bin/python main.py --page Neural`; không tự phát khi mở.

## Kết quả chạy thật trên Raspberry Pi 4

Đã chuyển mã nguồn và G sang `huy@10.42.0.193:/home/huy/final_project/PPG_simulator_raspi`, giữ nguyên `config.json` và môi trường ARM của Pi. Bản cũ được sao lưu vào `/home/huy/ppg-backups/pre-427e6f8`. App chạy trên desktop `:0`, mở mục 4 bằng user service `ppg-simulator`, không tự phát khi khởi động. Đây là phiên chạy hiện tại, không phải thay đổi chế độ tự khởi động sau reboot. [Ảnh cửa sổ thật trên Pi](hardware-validation/2026-09-30/app-pi.png).

PyTorch 2.10.0 aarch64 crash `SIGILL` tại `_mi_options_init`/`libc10.so`, lệnh `ldaddal` không được Cortex-A72 hỗ trợ. Trùng [regression ARMv8.1 LSE của PyTorch](https://github.com/pytorch/pytorch/issues/174344). Đã dùng **PyTorch 2.5.1**, Python 3.12.3, NumPy 2.5.3 và thêm pin theo kiến trúc trong `requirements/neural.txt`. Generator TorchScript hiện tại tải và chạy được. Seed 42 tạo đủ 1200 mẫu/30 s; sai khác lớn nhất với laptop là **2,414×10⁻⁸ V** (5,364×10⁻⁷ theo biên độ chuẩn hóa). Hash G khớp; [biên bản ARM](hardware-validation/2026-09-30/arm-inference.json). Thời gian cold import + load + generate khoảng 5,09 s.

Phép đo đầu phát hiện sleep cố định sau hai lần ghi I²C khiến writer không theo kịp mục tiêu 1 kHz: 802 mẫu bị bỏ, 713 overruns trong 30 s. Đã sửa để chỉ sleep trong phần ngân sách còn lại trước deadline, vẫn nhường CPU khi đã trễ. Kết quả đo lại cùng seed:

| Chỉ số Pi, 30 s LSM | Trước sửa | Sau sửa |
|---|---:|---:|
| Mẫu nội suy được sinh | 30.000 | 30.000 |
| Mẫu bị bỏ vì đầy bộ đệm | 802 | **0** |
| Overruns | 713 | **0** |
| Đọc bộ đệm rỗng (underruns) | 9 | 9 |
| Mẫu còn trong buffer lúc kết thúc | 1012 | 2 |
| Lỗi ghi IR / RED | 0 / 0 | 0 / 0 |
| Lỗi ADC | 0 | 0 |
| A0 trong cửa sổ ghi 31 s | 3103 mẫu | 3103 mẫu |
| A2 | disabled / 0 mẫu | disabled / 0 mẫu |
| Mã DAC cuối IR / RED | 0 / 0 | 0 / 0 |

**Kiểm tra bổ sung có GUI thật + BLE:** kết quả headless 1 kHz ở trên không đại diện tải desktop. Khi vẽ GUI, 1 kHz vẫn bỏ 1169 mẫu; bỏ redraw tab ẩn và giới hạn đồ thị GAN 10 fps giảm còn 729 nhưng chưa đạt. Vì vậy bản triển khai đặt **500 Hz mặc định trên aarch64**, giữ model 100 Hz và ADC 100 Hz. Có thể đặt `PPG_DAC_RATE_HZ` thành 100/200/500/1000; footer hiển thị đúng tốc độ đích. Với GUI + BLE + A0 ở 500 Hz, lượt 30 s sinh 15.000 mẫu, **0 overrun, 0 mẫu bị bỏ, 0 lỗi DAC**, 5 underruns và 22 mẫu còn trong buffer lúc kết thúc. App tự dừng clip. [Log kết quả GUI 500 Hz](hardware-validation/2026-09-30/gui-bench.json); [log 1 kHz trước giảm tải UI](hardware-validation/2026-09-30/gui-bench-before.json); [1 kHz sau giảm tải UI](hardware-validation/2026-09-30/gui-bench-throttled.json). `a0_count=1024` trong GUI bench là số mẫu còn trong deque giới hạn, không phải tổng mẫu đã thu.

Underruns là số lần reader gặp buffer rỗng, không phải kết quả đo tần số bằng oscilloscope. TX CSV lưu điện áp lệnh ở 100 Hz; số mẫu nội suy là mẫu do phần mềm sinh, không phải điện áp vật lý đã được đo. Phép đo headless 1 kHz và GUI 500 Hz được lưu riêng, không trộn điều kiện.

**Đường quang chưa đạt xác minh hình dạng.** A0 có giá trị thật, nhưng trong lần đo lại có đoạn nhảy lên plateau khoảng 3300 raw và không bám theo PPG TX. Tương quan lớn nhất chỉ |r|=0,04546 khi detrend đoạn 2–28 s và dò lag ±250 ms. Đây là mô tả dữ liệu, không phải kiểm định thống kê; chưa xác định nguyên nhân từ xa. Không kết luận LED, OPT101 hoặc SpO₂ đã được hiệu chuẩn. Cần kiểm tra hướng/ghép LED IR–OPT101, ánh sáng ngoài, GND và mạch driver rồi đo lại.

Lưu đầy đủ [lần đầu](hardware-validation/2026-09-30/initial/summary.json), [lần sau sửa](hardware-validation/2026-09-30/timing-fixed/summary.json), CSV IR/RED commanded, CSV A0 và [hình đo](hardware-validation/2026-09-30/timing-fixed/capture.png). Tái lập hình/phép đo tương quan: `.venv/bin/python -m ml.analyze_hardware_capture docs/hardware-validation/2026-09-30/timing-fixed`.
