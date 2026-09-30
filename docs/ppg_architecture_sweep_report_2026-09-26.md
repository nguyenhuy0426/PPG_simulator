# Báo cáo chọn kiến trúc neural tái tạo xung PPG

## 1. Mục tiêu và phạm vi kết luận

Thí nghiệm này tìm kiến trúc phù hợp hơn cho **một xung PPG 256 điểm pha có
điều kiện**, phục vụ giao diện HR/SP/DN/DP của sản phẩm. “Tốt nhất” chỉ có
nghĩa là tốt nhất trong năm cấu hình, ba seed và ngân sách đã định trước;
không phải kiến trúc tốt nhất tuyệt đối hoặc chứng nhận lâm sàng.

Không thay bộ phát, clock, config, Gaussian fallback hoặc DAC. Dữ liệu vẫn là
BIDMC, chia theo bệnh nhân 32/7/7 từ pilot cũ. Nhãn notch là nhãn tự động theo
detector cố định, chưa có kiểm duyệt thủ công. Snapshot nguồn trước thay đổi:
`/home/huynn/final_project/ppg-pre-arch-sweep-AhDZaD/source.tar.gz`, SHA-256
`9914d344775c5b19914a198b58a1b8d9678cfb0087773b402bbc46158da065e5`.

## 2. Cơ sở chọn ứng viên

- ResNet giúp truyền gradient qua mạng sâu; ở đây dùng các block upsampling
  residual thay cho chuỗi convolution phẳng.
- FiLM biến đổi affine từng kênh đặc trưng theo điều kiện. Bài gốc chứng minh
  cơ chế conditioning tổng quát trên bài toán thị giác; việc áp dụng cho PPG
  là giả thuyết cần kiểm tra, không phải kết quả đã được bài gốc xác nhận:
  [Perez et al.](https://arxiv.org/abs/1709.07871).
- TCN dùng convolution dilation và residual để mở receptive field. So sánh
  tổng quát của [Bai et al.](https://arxiv.org/abs/1803.01271) cho thấy CNN là
  điểm khởi đầu hợp lý thay vì mặc định chọn LSTM; kết quả đó không trực tiếp
  xếp hạng generator PPG.
- Multi-scale dùng kernel 3/9/21/41 để đồng thời nhìn nét cục bộ và bao xung;
  đây là thiết kế của dự án, có liên hệ ý tưởng đa thang với LSM nhưng không
  phải kiến trúc LSM-GAN nguyên bản.
- Projection discriminator đưa điều kiện vào bằng tích vô hướng với đặc trưng
  waveform, theo nguyên lý của
  [Miyato và Koyama](https://openreview.net/forum?id=ByS1VpgRZ). Continuous
  morphology và auxiliary regression head là phần thích nghi của dự án.
- Loss thời gian và phổ được dùng cùng adversarial loss. Điều này phù hợp với
  nhận định PPG/rPPG có cấu trúc quasi-periodic và time-frequency trong
  [PulseGAN](https://arxiv.org/abs/2006.02699), nhưng PulseGAN là bài toán
  denoise có cặp đầu vào–đích, không phải noise-to-pulse như thí nghiệm này.
- WGAN-GP giữ cách regularize critic bằng gradient penalty từ
  [Gulrajani et al.](https://arxiv.org/abs/1704.00028).

Năm cấu hình:

| Tên | Generator | Critic |
|---|---|---|
| `upsample_projection` | Dense + upsample Conv1D của pilot | Projection + auxiliary head |
| `resnet_film_projection` | ResNet upsample + FiLM | Projection + auxiliary head |
| `tcn_film_projection` | Dilated residual TCN + FiLM | Projection + auxiliary head |
| `multiscale_film_projection` | Residual multi-kernel + FiLM | Projection + auxiliary head |
| `resnet_film_concat` | Cùng ResNet-FiLM | Concatenate feature/condition + auxiliary head |

Bốn dòng đầu giữ critic giống nhau để so generator. Hai dòng ResNet giữ
generator giống nhau để so cách condition critic.

## 3. Giao thức

- Dữ liệu prepared được khóa bằng SHA-256
  `25c830dc1613a0dbf9c3775fc87b95b966492fc0962a828c84543422fa278dcf`.
- Batch train cân bằng 50% notch phân giải được và 50% không notch phân giải được.
- Một waveform thật ghép với điều kiện của lớp đối diện là negative bổ sung
  cho critic; auxiliary head phải dự đoán điều kiện từ waveform, không được
  đọc lại condition input.
- Mỗi cấu hình chạy seed 41/42/43, 3.000 bước G; mỗi bước G có ba bước D.
- Cùng optimizer, learning rate, WGAN-GP, morphology/spectrum/derivative/
  boundary loss và ngân sách.
- Checkpoint của từng run chọn bằng validation cân bằng. Kiến trúc thắng chọn
  bằng median validation của ba seed. Test không tham gia hai quyết định này.

Primary morphology score gồm sai số SP, balanced notch error và sai số DN/DP
đã phạt trường hợp mất notch. Nhờ vậy mô hình không thể đạt điểm đẹp bằng cách
không tạo DN/DP rồi loại các ca đó khỏi mẫu số. RMSE log-spectrum được báo riêng
và chỉ có trọng số 10% trong selection score.

## 4. Kết quả Kaggle

Job riêng tư:
[PPG Conditional Architecture Sweep](https://www.kaggle.com/code/charlesday2612/ppg-conditional-architecture-sweep).

Job **COMPLETE** trên Tesla T4: 15/15 run, tổng thời gian script 3.489,8 giây
(58,2 phút). Kaggle quota tăng từ 0,29 lên 1,26 giờ, còn 28,74/30 giờ tuần
này. Source SHA-256 trong artifact và local cùng là
`f3ff4fb4a0e94bd5ac98696180d45dd044df35c102415b8848594c275fe824b1`.

### 4.1 Xếp hạng bằng validation

| Kiến trúc | G params | Median selection score validation ↓ |
|---|---:|---:|
| **TCN-FiLM + projection critic** | 911.553 | **0,08771** |
| Multi-scale-FiLM + projection critic | 1.011.649 | 0,11216 |
| ResNet-FiLM + concat critic | 601.633 | 0,11393 |
| ResNet-FiLM + projection critic | 601.633 | 0,13583 |
| Upsample baseline + projection critic | 284.321 | 0,16238 |

TCN thắng theo tiêu chí đã chốt trước khi xem test, thấp hơn baseline 46,0%
và thấp hơn ResNet-concat 23,0%. Median morphology-only validation cũng tốt
nhất: TCN 0,05098; ResNet-concat 0,06323; ResNet-projection 0,07294;
multi-scale 0,07790; baseline 0,10540.

### 4.2 Test cân bằng, trung bình ba seed

| Kiến trúc | Selection ↓ | Morphology ↓ | SP MAE ↓ | Notch sens. ↑ | Notch spec. ↑ | log-spectrum RMSE ↓ | Paired RMSE ↓ |
|---|---:|---:|---:|---:|---:|---:|---:|
| Upsample + projection | 0,16718 | 0,10166 | 0,04958 | 99,87% | 100% | 0,65512 | 0,17234 |
| ResNet-FiLM + projection | 0,14375 | 0,07893 | 0,03242 | 99,41% | 100% | 0,64820 | 0,13447 |
| **TCN-FiLM + projection** | **0,09563** | 0,05884 | 0,02521 | 99,80% | 100% | **0,36792** | **0,11442** |
| Multi-scale-FiLM + projection | 0,13763 | 0,09495 | 0,03691 | 98,18% | 100% | 0,42674 | 0,13885 |
| ResNet-FiLM + concat | 0,11093 | **0,05655** | **0,02188** | 100% | 100% | 0,54372 | 0,11989 |

Mỗi test run có 512 yêu cầu có notch và 512 không notch. TCN giảm so với
baseline: selection 42,8%, morphology 42,1%, SP MAE 49,2%, spectrum RMSE
43,8% và paired RMSE 33,6%. Ba seed TCN chọn checkpoint ở bước 3.000/2.800/
3.000; selection test lần lượt 0,09442/0,09331/0,09918.

So với pilot cWGAN cũ, sensitivity notch tăng từ 1,94% lên 99,80% và SP MAE
giảm từ 0,04778 xuống 0,02521, nhưng đây không phải ablation kiến trúc thuần
túy: sweep mới còn thay sampler cân bằng, critic conditioning, auxiliary head và
loss. So sánh có kiểm soát để quy phần cải thiện cho generator là TCN với
upsample-projection ngay trong bảng trên.

ResNet-concat nhỉnh hơn TCN rất nhẹ ở morphology-only và SP trên **test**,
nhưng không được đổi winner theo test. TCN đã thắng cả median morphology-only
validation và score tổng hợp, đồng thời phổ/toàn xung tốt hơn. Chênh test
morphology 0,00229 nhỏ hơn độ lệch chuẩn giữa seed của TCN (0,00463); không
có cơ sở nói ResNet tốt hơn về hình thái tổng quát.

Sai số TCN trên nhóm yêu cầu notch, đã phạt cả trường hợp mất notch:
DN phase 0,06938; DP phase 0,03537; DN level 0,02796; DP level 0,04160.
Theo trung bình đều bảy bệnh nhân test, selection score là 0,10992 cho TCN
và 0,11721 cho ResNet-concat; TCN tốt hơn ở 4/7 bệnh nhân. Bảy bệnh nhân quá
ít để ước lượng chắc chắn khoảng tin cậy hoặc tuyên bố ưu thế quần thể.

### 4.3 Độ đa dạng, độ mượt và artifact

TCN có pointwise diversity trên toàn tập điều kiện test 0,13355, gần dữ liệu
thật 0,12848; nhưng fixed-condition diversity chỉ 0,01376. Điều này cho thấy
đa dạng chủ yếu đến từ condition, còn latent noise có ảnh hưởng nhỏ. Với bộ
mô phỏng điều khiển gần xác định đây có thể chấp nhận được; với mục tiêu sinh
nhiều biến thể tự nhiên cho cùng condition thì chưa đủ.

Roughness trung bình TCN khoảng 0,000734, còn test thật khoảng 0,000417:
đầu ra vẫn gồ ghề hơn khoảng 1,76 lần. Nó tốt hơn rõ pilot cũ nhưng chưa phải
dạng sóng đã xác nhận bằng phần cứng/quang học. Detector dùng để tạo nhãn cũng
được dùng đánh giá, nên sensitivity/specificity cao có nguy cơ tối ưu đúng
quy tắc detector hơn là đúng định nghĩa sinh lý độc lập.

[Hình so sánh năm kiến trúc](../ml/runs/architecture-kaggle-v1/architecture_sweep/architecture_comparison.png)
và [review 16 xung TCN có đánh dấu SP/DN/DP](../ml/runs/architecture-kaggle-v1/architecture_sweep/winner_morphology_review.png)
cho thấy TCN tái tạo bao xung và hai chế độ notch hợp lý, nhưng một số vai/đuôi
vẫn khác xung thật. Các cặp không phải reconstruction pointwise bắt buộc;
generator lấy noise và condition của xung thật.

### 4.4 Quyết định kiến trúc

**Chốt cho vòng phát triển tiếp: TCN-FiLM generator + projection critic có
auxiliary condition head.** Generator nhận `z(32)` và bảy điều kiện, ánh xạ
sang 64×256, qua sáu residual TCN block kernel 3 với dilation
1/2/4/8/16/32, GroupNorm + FiLM, rồi Conv1D kernel 7 và envelope biên. Hai
convolution mỗi block cho receptive field lý thuyết 253 điểm, gần phủ toàn bộ
xung 256 điểm, trong khi vẫn xử lý được nét cục bộ.

Critic dùng backbone Conv1D 1→32→64→128→128, kernel 7/stride 2, global mean;
điểm WGAN gồm base score cộng projection condition. Auxiliary head dự đoán
sáu giá trị liên tục và cờ notch từ waveform feature. D chỉ dùng khi train/
audit; Pi phát tín hiệu chỉ cần G.

Artifact đại diện chọn hoàn toàn bằng validation là seed 42, bước 2.800:
[generator_cpu.ts](../ml/runs/architecture-kaggle-v1/architecture_sweep/tcn_film_projection/seed_42/generator_cpu.ts).
File khoảng 3,80 MB. Audit parity G/D pass cho 15/15 run; output hữu hạn,
chuẩn hóa [0,1], hai đầu bằng 0. Trên CPU x86_64 local một thread, median G
seed 42 khoảng 2,02 ms/xung; **không phải benchmark Raspberry Pi**.

Chưa thay engine bằng artifact này. Trước khi deploy cần review notch bằng
nhãn thủ công/thuật toán độc lập, kiểm tra cohort khác, đo trên Pi, đo đầu ra
DAC/quang học và quyết định có cần tăng fixed-condition diversity hay không.

## 5. Kiểm thử và artifact

- 11 test mới cho shape/bound, gradient, auxiliary-head isolation, loss hữu
  hạn, gradient penalty, cân bằng batch, checksum/chia tập và metric.
- Tổng nhóm ML hiện có: 42 test pass.
- Suite ứng dụng: 644 pass, 4 skip, 288 subtest pass. Các skip là dependency
  ML tùy chọn trong môi trường ứng dụng, không phải test ML bị thất bại.
- Smoke test đã chạy trọn cả năm cấu hình và smoke subset một cấu hình; chỉ
  xác nhận pipeline, không xác nhận chất lượng.
- Mỗi run chính lưu cả G/D, history, sample test, result và TorchScript CPU.
  [Audit script](../ml/audit_architecture_sweep.py) kiểm tra parity và benchmark
  sau khi tải kết quả. Benchmark local không được gọi là benchmark Pi.

Mã và hợp đồng tái lập: [README](../ml/kaggle_arch/README.md),
[train_architectures.py](../ml/kaggle_arch/train_architectures.py).

Kết quả đầy đủ: [summary.json](../ml/runs/architecture-kaggle-v1/architecture_sweep/summary.json),
[audit.json](../ml/runs/architecture-kaggle-v1/architecture_sweep/audit.json). Ví dụ
IR/RED offline của winner đã xuất ở [100 Hz](../ml/runs/architecture-kaggle-v1/architecture_sweep/tcn_film_projection/seed_42/winner_ir_red_100hz.csv)
và [1.000 Hz](../ml/runs/architecture-kaggle-v1/architecture_sweep/tcn_film_projection/seed_42/winner_ir_red_1000hz.csv),
dùng cùng shape, DC=1,5 V, AC_IR=45 mV, AC_RED=21,6 mV. Đây không phải hai
kênh quang học được học độc lập và chưa được gửi xuống DAC.
