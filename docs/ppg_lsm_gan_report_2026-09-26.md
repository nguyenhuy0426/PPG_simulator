# So sánh LSM-GAN và vai trò discriminator

Cập nhật 28/09: đã tải lại, xác minh v2 và thêm trang Neural để xem thử hai
generator trong app; xem [báo cáo tích hợp và kiểm chứng mới](ppg_neural_preview_report_2026-09-28.md).
Phần dưới giữ giao thức và kết quả thí nghiệm ngày 26/09.

## 1. Discriminator của hệ thống hiện tại

cWGAN-GP v1 đã huấn luyện **hai mạng**, không chỉ generator. Critic hiện có
12.753 tham số: đầu vào một xung và bảy điều kiện, Conv1D
8→16→32→32 (kernel 7, stride 2, LeakyReLU), flatten rồi Linear 1024→1.
Không dùng sigmoid hoặc BatchNorm. Đầu ra là điểm Wasserstein, không phải
xác suất nhịp PPG “đúng chuẩn”. Gradient penalty tác động lên critic;
gradient qua critic hướng dẫn generator cải thiện.

V1 chỉ lưu/export generator. Không thể khôi phục trọng số critic v1 từ file
generator để phân tích lại. Điều đó không có nghĩa critic chưa được train.
Các thí nghiệm LSM mới lưu cả G, D, optimizer và RNG state, và xuất cả hai
mạng sang TorchScript CPU để kiểm tra. Chạy phát tín hiệu trên Pi chỉ cần G;
D có thể dùng để nghiên cứu chất lượng, nhưng không phải bộ kiểm định sinh lý.

CNN 1D là lựa chọn hợp lý ban đầu cho D vì nó học các đặc trưng cục bộ của
dạng sóng; không bắt buộc đổi sang LSTM chỉ vì đầu vào là chuỗi thời gian.
Không thể quy toàn bộ lỗi notch v1 cho D: nhãn, mất cân bằng điều kiện, loss,
generator và tiêu chí chọn checkpoint đều có thể góp phần.

## 2. Đọc bài báo và lựa chọn cách tái triển khai

Nguồn: [Ding et al., LSM-GAN, arXiv:2108.05272v2](https://arxiv.org/abs/2108.05272v2)
và [mã tác giả, commit d2d01fe](https://github.com/chengding0713/Log-Spectral-matching-GAN/tree/d2d01feab0cec7c129bae0b63c56277adc4f48cc).
Mô hình gốc hướng tới tăng cường dữ liệu cho phân loại AF, sinh đoạn nhiều
nhịp, không có mục tiêu điều khiển trực tiếp notch của một chu kỳ.

Mã tham khảo và bài báo có khác biệt về objective và cách ghép block. Vì vậy
triển khai ba nhánh trên cùng topology thay vì gọi một bản duy nhất là tái
hiện nguyên vẹn:

| Nhánh | Adversarial loss | Ghép phổ | Trọng số match/self |
|---|---|---|---|
| `lsm_paper` | Least squares | Các block cùng vị trí | 1 / 1 |
| `lsm_repo_corrected` | BCE | Mọi cặp block | 1 / 1 |
| `dcgan1200_no_spectral` | BCE | Bỏ spectral loss | 0 / 0 |

“Paper” ở đây là biến thể theo objective, không phải tái lập toàn bộ thực
nghiệm bài báo. Không có dữ liệu AF được gán nhãn của tác giả, không train
classifier AF và không tái lập grid search lớn. Không áp dụng kết quả AF
trong bài để tuyên bố chất lượng hình thái của sản phẩm này.

LSM generator mới có 117.940 tham số, dùng ba nhánh Conv1D kernel 5/21/61,
không upsample; nhận noise 1.200 điểm, xuất đoạn 1.200 điểm. Discriminator
có 692.370 tham số: CNN 1→64→128→256→512, BatchNorm từ tầng 2, rồi Conv
512→1, Linear 72→2 và sigmoid. **Hai output cùng được huấn luyện real/fake,
không phải hai nhãn AF/không AF.**

Loss phổ dùng cửa sổ Hann 400 điểm, overlap 200, log-power và chuẩn hóa theo
tần số cho từng mẫu/block; so khoảng cách giữa tín hiệu thật/giả và giữa các
block giả. Đã sửa trường hợp trộn batch khi reshape trong mã tham khảo,
chặn log(0), mẫu số bằng 0, và chuyển `torch.rfft` sang `torch.fft.rfft`.
Do các sửa đổi này, nhánh code cũng được ghi rõ `corrected`, không tuyên bố
tương đương số học từng bit với mã tác giả.

Discriminator LSM vẫn chỉ là CNN miền thời gian. Loss phổ được cộng vào
loss **generator**, không có discriminator FFT thứ hai. Với nhánh least
squares: D tối thiểu hóa `MSE(D(real),1)+MSE(D(fake),0)`; G tối thiểu hóa
`MSE(D(fake),1)+matching+self_consistency`. Nhánh BCE thay MSE bằng BCE.
Phương trình 3 của bài nêu objective G; việc chọn MSE đối ứng cho D ở nhánh
`lsm_paper` là lựa chọn triển khai đã công bố, không khẳng định đó là vòng
train nguyên bản đầy đủ của tác giả (mã công bố dùng BCE).
Các điểm D gần 0,5 có thể do cân bằng hoặc D yếu; điểm phân biệt rất tốt có
thể do G vẫn kém. Không dùng riêng loss/AUC của D để xác nhận tín hiệu tốt.

## 3. Dữ liệu, giao thức và giới hạn so sánh

Giữ nguyên [BIDMC](https://physionet.org/content/bidmc/1.0.0/) và nhóm bệnh
nhân v1: 32 train, 7 validation, 7 test. Nguồn 125 Hz được resample về 40 Hz,
FIR 161 tap zero-phase 0,9–5 Hz, minmax từng đoạn 30 s không chồng lấn:
624 train, 112 validation, 112 test. Thông số FIR chi tiết là lựa chọn kỹ
thuật của dự án, không phải thông số đầy đủ trích từ bài. Ghi công dữ liệu:
Pimentel et al., BIDMC 1.0.0, ODC Attribution 1.0.

Mỗi nhánh: seed 42, batch 64, 1.500 bước G và D, Adam 5e-4,
betas=(0,5;0,999). Cùng khởi tạo, thứ tự lấy batch, noise, ngân sách và tiêu
chí chọn checkpoint. Chọn bằng tổng MMD² của ACF và log-PSD trên validation;
băng thông kernel được ước lượng từ **train**. Không chọn checkpoint bằng test.
Chạy thử CPU hai bước chỉ kiểm tra pipeline; không đưa kết quả smoke vào
kết luận chất lượng.

Đối chứng bổ sung: cWGAN v1 phát xung lặp ở HR lấy từ train, replay xung train
theo cùng cách, và replay nguyên đoạn 30 s của train. Hai bộ phát theo xung
được lọc qua cùng FIR view; điều này áp sẵn tính tuần hoàn và giới hạn băng
tần mà raw LSM phải học. Vì vậy đây là đối chiếu khả năng sử dụng thực tế,
**không phải phép thử ngang bằng để xếp hạng tổng quát mọi loại GAN**.

Test đã được xem ở pilot v1; lần này là so sánh thăm dò. Chỉ một seed, số
bệnh nhân test nhỏ, số bản ghi mỗi người không đều, chưa có khoảng tin cậy
theo bệnh nhân hoặc cohort độc lập. Thay đổi giữa hai nhánh LSM đồng thời
gồm objective và pairing; chỉ cặp BCE có/bỏ spectral loss là ablation khớp.

## 4. Kết quả Kaggle

Job riêng tư:
[PPG LSM GAN BIDMC Comparison](https://www.kaggle.com/code/charlesday2612/ppg-lsm-gan-bidmc-comparison),
**phiên bản 2 đã COMPLETE**, tải đủ artifact và kiểm chứng tại local ngày
26/09/2026. Chạy trên Tesla T4, Python 3.12.13, PyTorch 2.10.0+cu128;
ba nhánh đều hoàn thành 1.500 bước. Thời gian train từng nhánh lần lượt
101,3 / 107,4 / 106,7 giây, chưa tính tải dữ liệu và chuẩn bị môi trường.
Quota tài khoản sau chạy: đã dùng 0,29 giờ GPU, còn 29,71/30 giờ tuần này
(đây là số tổng của tài khoản, không phải riêng thời gian train của một nhánh).

### Kết quả chính — phiên bản 2

Đánh giá trên 112 đoạn test; ba cột sai số càng thấp càng tốt. Checkpoint
được chọn trên validation, không phải bước cuối hoặc checkpoint có test tốt nhất.

| Mô hình | Bước được chọn | ACF MMD² | log-PSD MMD² | RMSE phổ log trung bình |
|---|---:|---:|---:|---:|
| LSM theo objective bài báo | 1.000 | 0,10431 | 1,52702 | 1,91876 |
| LSM BCE, code đã sửa | 800 | 0,10571 | 1,49764 | 1,73491 |
| Cùng G/D, BCE, bỏ spectral loss | 1.400 | 0,10521 | 1,52457 | 2,03235 |
| cWGAN v1 + adapter xung tuần hoàn | — | 0,06104 | 0,51492 | 0,83114 |
| Replay xung train + adapter tuần hoàn | — | 0,05607 | 0,63970 | 1,02756 |
| Replay đoạn thật 30 s từ train | — | 0,07473 | 0,04378 | 0,16673 |

Trong **cặp BCE khớp kiến trúc**, spectral loss giảm RMSE phổ log khoảng
14,6% và log-PSD MMD² khoảng 1,77%; ACF MMD² không cải thiện (tăng khoảng
0,47%). Đây là kết quả một seed, chưa chứng minh khác biệt có ý nghĩa thống kê.
LSM BCE có tỷ lệ công suất trên 5 Hz là 0,01978%, so với 0,04159% ở nhánh
không spectral loss và 0,002089% ở dữ liệu test thật. Tỷ lệ này nhỏ về tuyệt
đối nhưng nền phổ ngoài dải vẫn cao hơn dữ liệu thật khoảng 9,5 lần. Vì
metric log-PSD nhạy với nền phổ nhỏ, không nên diễn giải nó thành phần trăm
“độ chính xác PPG” hay điểm chất lượng hình thái.

Quan sát [dạng sóng và phổ](../ml/runs/lsm-kaggle-v2/lsm_comparison/comparison.png):
đã có cấu trúc nhịp rõ hơn bản lỗi, nhưng còn biến thiên hình dạng, vai/đỉnh
phụ và phổ khác dữ liệu thật. Đây là các mẫu minh họa không ghép cặp, không
phải phép xác nhận notch. Chưa có đánh giá SP/DN/DP riêng cho đầu ra LSM.
Không kết luận cWGAN thắng mọi mặt: adapter của nó đã áp đặt tuần hoàn và
lọc băng, và cWGAN v1 vẫn có kết quả notch kém trong báo cáo trước.

### Kiểm tra discriminator và artifact

| Nhánh | D(real) trung bình | D(fake) trung bình | AUC real/fake của chính D |
|---|---:|---:|---:|
| LSM theo bài báo | 0,8232 | 0,0293 | 0,9978 |
| LSM BCE đã sửa | 0,8224 | 0,0044 | 0,9931 |
| BCE không spectral loss | 0,5070 | 0,0755 | 0,9448 |

AUC cao ở đây nghĩa là D **vẫn phân biệt dễ** dữ liệu thật với đầu ra của G,
không phải G đạt chất lượng cao hay D phát hiện bệnh chính xác. Đây cũng
không phải evaluator độc lập vì D đã tham gia huấn luyện G. Probe BatchNorm
32 mẫu vẫn khác giữa train/eval như dự kiến ở các chế độ khác nhau; lỗi dùng
hai chế độ không nhất quán trong objective đã được sửa, không có tuyên bố
running statistics đã được hiệu chuẩn hoàn hảo.

Đã tải và kiểm tra cả sáu TorchScript G/D: đầu ra khớp mạng dựng lại từ
`best.pt` ở batch 3 (`atol=1e-6`, `rtol=1e-5`), hữu hạn, đúng kích thước.
Generator khoảng 0,51 MB, discriminator khoảng 2,81 MB. Đo CPU **x86_64
local**, một thread/batch 1, 100 lần sau warm-up: median G khoảng 3,09–3,14 ms
cho đoạn 30 s, D khoảng 1,51–1,53 ms. Đây **không phải benchmark Raspberry Pi**.
PyTorch local cảnh báo TorchScript không được hỗ trợ trên Python 3.14+;
phép kiểm tra hiện chạy được nhưng cần chốt runtime được hỗ trợ hoặc định
dạng export khác trước triển khai.

Kiểm thử hoàn tất: 31 test ML pass; suite môi trường ứng dụng 644 pass,
3 skip, 288 subtest pass. Các test gồm shape/gradient, cập nhật D độc lập,
BatchNorm khi cập nhật G, loss so với NumPy và tính độc lập giữa các mẫu.
`git diff --check` sạch. Dữ liệu cửa sổ v1/v2 giống hoàn toàn và hash nguồn
huấn luyện/G cWGAN đã được đối chiếu với cấu hình tải từ Kaggle.

### Kiểm tra và sửa ở phiên bản 1

Ở bản đầu, D được đặt `eval()` trong bước cập nhật G để đóng băng running
statistics. Đây là khác biệt không phù hợp với vòng train tham khảo: D học
với batch statistics nhưng G tối ưu qua running statistics. Với checkpoint
LSM-paper bước 400 và cùng 32 mẫu, D(real)/D(fake) là 0,9971/0,0027 ở train
mode nhưng 0,4815/0,7075 ở eval mode. Không thể gọi generator tốt chỉ vì nó
đánh lừa D trong một chế độ khác.

Phiên bản 2 giữ D ở train mode khi cập nhật G, chỉ đóng băng gradient của
tham số D; eval chỉ dùng khi đánh giá/export. Có regression test cho hành
vi BatchNorm này. Chạy lại **cả ba nhánh**, không chỉ nhánh có kết quả xấu,
giữ nguyên dữ liệu, seed, loss, ngân sách, criterion và protocol đánh giá.
Sửa này xuất phát từ kiểm tra vòng huấn luyện và mã tham khảo, không phải
grid search theo test. Vì test đã được nhìn thấy, toàn bộ báo cáo vẫn chỉ
là kết quả thăm dò.

V1 được giữ trong `ml/runs/lsm-kaggle-v1/`, cùng source snapshot
`/home/huynn/final_project/ppg-pre-lsm-yBoBvK/lsm-v1-source-before-bn-fix.tar.gz`.
V1 không phải bảng kết quả chính. Chưa dùng số smoke để kết luận chất lượng.

## 5. Tác động lên sản phẩm

LSM hiện là mạng **không điều kiện**, chưa có nút HR/SP/DN/DP. Đầu ra là
30 s ở 40 Hz; không phải một template theo pha 256 điểm. Không lấy loss
self-consistency của nhiều nhịp để ép phần tâm thu và tâm trương của một
nhịp có cùng phổ. Muốn điều khiển tham số phải thiết kế và kiểm tra biến thể
conditional riêng, hoặc tách một ngân hàng xung đã kiểm duyệt từ đầu ra.
Hai đầu đoạn LSM không được ràng buộc liên tục/đúng chân xung, nên chưa được
nối các đoạn 30 s hoặc lặp chúng trực tiếp trong vòng DAC. Kiểm tra phổ tốt
không thay thế kiểm tra mốc SP/DN/DP, cực tính và độ liên tục khi ghép đoạn.

Không có dữ liệu paired IR/RED mới; hai kênh vẫn phải dùng phần AC/DC và
hiệu chuẩn của hệ thống. Không thay clock, config, waveform mặc định hay DAC.
Không có phép đo trên Pi hoặc xác nhận SpO2 quang học trong lượt này.

Đã xuất CSV offline 1.200 dòng/30 s cho mỗi nhánh, `time_s` cách nhau 0,025 s:
`IR = 1,5 + 0,045*x`, `RED = 1,5 + 0,0216*x` (volt), cùng một shape `x`.
Tỷ số AC_RED/AC_IR = 0,48 ứng với ví dụ hiệu chuẩn danh định A=110, B=25,
SpO2=98 và DC bằng nhau; không phải SpO2 đã đo/đã học. Fs=40 Hz là hợp đồng
dữ liệu và metadata của mô hình, **không phải một output scalar GAN tự dự đoán**.
Muốn phát bằng clock DAC khác phải resample có kiểm soát; chỉ đổi tốc độ phát
1.200 mẫu sẽ đổi cả thời lượng và nhịp. Các CSV không được gửi xuống phần cứng.

Đề xuất cho kiến trúc sản phẩm: giữ giao diện **conditional single-pulse**
cho các nút điều khiển hiện có; xem LSM là nhánh nghiên cứu sinh đoạn dài.
Nếu lấy ý tưởng spectral loss đưa vào cWGAN, dùng phổ toàn xung hoặc các
đoạn nhiều nhịp được dựng có kiểm soát, không gắn self-consistency giữa các
pha khác nhau một cách tùy ý. Đó sẽ là một biến thể mới cần thí nghiệm riêng,
không được gọi là mô hình gốc đã chứng minh trong bài.

## 6. Tệp và khả năng tái lập

- Mã độc lập: [train_lsm.py](../ml/kaggle_lsm/train_lsm.py).
- Giao thức và các khác biệt đầy đủ: [README](../ml/kaggle_lsm/README.md).
- Audit model/discriminator: [audit_lsm_run.py](../ml/audit_lsm_run.py).
- Kiểm thử: [test_lsm_gan.py](../tests/test_lsm_gan.py).
- Số liệu đầy đủ: [comparison.json](../ml/runs/lsm-kaggle-v2/lsm_comparison/comparison.json).
- Audit và benchmark: [audit.json](../ml/runs/lsm-kaggle-v2/lsm_comparison/audit.json),
  [biểu đồ D và validation](../ml/runs/lsm-kaggle-v2/lsm_comparison/discriminator_audit.png).
- Ví dụ hai kênh: [LSM BCE IR/RED CSV](../ml/runs/lsm-kaggle-v2/lsm_comparison/lsm_repo_corrected/example_ir_red_40hz.csv).
- Bản cWGAN v1 và báo cáo trước được giữ nguyên.

Source SHA-256 phiên bản 2:
`a0ff8319a281285768b34a290065ee1dc3ac112dcda7b8d54a40d013c6ddf47b`.
Các artifact lớn nằm trong `ml/runs/` (gitignored) và output Kaggle, không
được coi là đã lưu trong Git. File cấu hình chứa hash dữ liệu và G cWGAN để
kiểm tra truy xuất nguồn gốc. Hướng dẫn CLI trong README chạy lại thí nghiệm,
nhưng không bảo đảm tái lập từng bit giữa các phiên bản CUDA/PyTorch.

Trước thay đổi đã sao lưu nguồn vào
`/home/huynn/final_project/ppg-pre-lsm-yBoBvK/source.tar.gz`, SHA-256
`901f3fec7a5ba2c17812ffb844484508f08b9c4933785c25c441c7e67b94197f`.
Snapshot này không chứa các artifact lớn `ml/runs/`; các artifact v1 vẫn
ở local và Kaggle. Không tự commit các thay đổi chung của người dùng.
