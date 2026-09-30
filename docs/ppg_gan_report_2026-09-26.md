# Báo cáo mở rộng PPG bằng cWGAN-GP

## Phạm vi và bảo toàn phiên bản

Thực hiện ngày 25–26/09/2026. Phần ML được tách khỏi ứng dụng chạy thật.
Không thay bộ phát mặc định, không đổi config người dùng, PCB, BLE hay lịch DAC.
Các sửa đổi notch đã có từ lượt trước được giữ nguyên và chạy lại kiểm thử.

HEAD vẫn là `74aac32` — `feat: add PPG receiver and LED driver PCB designs`.
Working tree còn thay đổi chưa commit; **không coi HEAD là bản chứa toàn bộ
hiện trạng**, và không tự commit lẫn các thay đổi của người dùng.

Sao lưu toàn bộ trước chỉnh notch:
`/home/huynn/final_project/PPG_simulator_raspi-backup-20260925-143036.tar.gz`.

Sao lưu mã nguồn trước phần ML, bao gồm phần notch đã sửa:
`/home/huynn/final_project/ppg-pre-kaggle-RVDSI6/source.tar.gz`.
SHA-256: `dc3a3c9c572a03b45ef80a63053a9d94a60adaf73bf77e1078f9751e91bdf824`.
Bản thứ hai là snapshot các thư mục mã nguồn, không thay thế bản sao lưu đầy
đủ phần cứng ở trên.

## 1. Định nghĩa hình thái đã triển khai

Với cực tính xung hướng lên:

- SP: đỉnh tâm thu, lấy cực đại chính của xung.
- DN: cực tiểu cục bộ trên nhánh xuống giữa SP và đỉnh thứ hai.
- DP: đỉnh thứ hai sau DN, khi phân giải được.
- Không có DN/DP rõ là trạng thái được phép. Điểm uốn/shoulder chưa được bộ
  phát hiện hiện tại coi là notch phân giải được.

Mốc đo từ dạng sóng khác với tâm thành phần Gaussian. `dicrotic_depth=0.25`
trong mã đã sửa nghĩa là giảm 25% **bao tín hiệu tại tâm notch trước chuẩn
hóa**, không phải DN/SP=0.25, cũng không phải mức giảm 25% tính từ SP.
Chi tiết và nguồn nghiên cứu: [ppg_morphology.md](ppg_morphology.md).

Preset Gaussian mặc định, đo trên lưới pha 256 điểm:

| Đại lượng | Giá trị |
|---|---:|
| SP / chu kỳ | 0,15294 |
| DN / chu kỳ | 0,29412 |
| DP / chu kỳ | 0,40000 |
| DN/SP | 0,19484 |
| DP/SP | 0,39316 |

Preset này tạo được thứ tự cực trị đúng với bộ đo hiện tại, không cần đáy
âm bị cắt phẳng. Điều đó chứng minh tính chất toán học của preset, **chưa
chứng minh “đạt chuẩn PPG lâm sàng”**. Không có một khoảng thời gian/độ sâu
notch duy nhất được áp dụng cho mọi tuổi, vị trí đo, nhịp tim và bệnh lý.
Các giá trị trên không phải kiểm tra config đang lưu của người dùng.

## 2. Dữ liệu thật và chia tập

Nguồn: [BIDMC PPG and Respiration Dataset 1.0.0](https://physionet.org/content/bidmc/1.0.0/),
53 bản ghi từ bệnh nhân chăm sóc tích cực. File MAT đã xác minh SHA-256:
`91865c2fffff70868875545f897542003d376a53262c7c0ead5b6e9109e884db`.
Ghi công: Pimentel et al., IEEE TBME 2017,
DOI:10.1109/TBME.2016.2613126; giấy phép ODC Attribution 1.0.

Có **46 mã bệnh nhân duy nhất**, không phải 53 người độc lập. Chia theo mã
MIMIC gốc, seed 42, trước huấn luyện:

| Tập | Bệnh nhân | Xung được giữ |
|---|---:|---:|
| Train | 32 | 25.684 |
| Validation | 7 | 5.113 |
| Test | 7 | 4.756 |
| Tổng | 46 | 35.553 |

Nguồn PPG có Fs=125 Hz. NeuroKit2/Elgendi dùng để phát hiện nhịp; hình thái
lấy từ tín hiệu lowpass 12 Hz riêng, tách chân–chân, loại đường nền tuyến
tính, chuẩn hóa đỉnh và nội suy PCHIP sang 256 điểm pha. Loại 320 đoạn vì
thời lượng, 627 vì đường nền/biên độ và 603 vì vị trí SP. Đây là bộ lọc kỹ
thuật ban đầu, chưa phải bộ đánh giá chất lượng tín hiệu toàn diện.

13,11% xung train có notch rõ theo detector cố định. Với **riêng nhóm này**,
phân vị 5% / 50% / 95% đo được:

| Đại lượng | P5 | P50 | P95 |
|---|---:|---:|---:|
| SP / chu kỳ | 0,1843 | 0,2353 | 0,4549 |
| DN / chu kỳ | 0,4353 | 0,5804 | 0,7255 |
| DP / chu kỳ | 0,5333 | 0,7137 | 0,8275 |
| DN/SP | 0,0397 | 0,1562 | 0,5092 |
| DP/SP | 0,1026 | 0,2331 | 0,6234 |

Đây là thống kê mô tả của dữ liệu bệnh nhân sau xử lý và nhãn tự động, **không
phải khoảng chuẩn khỏe mạnh hoặc giới hạn để sửa Gaussian theo một cách máy
móc**. Cần kiểm duyệt nhãn notch, đặc biệt các xung có nhiều sóng phản xạ hoặc
nhiễu. HR train có P5/P50/P95 khoảng 64,1/88,2/125 BPM.

## 3. Mô hình và thiết kế đánh giá

Chọn conditional WGAN-GP 1D nhẹ: generator 284.321 tham số, latent 32 chiều,
7 điều kiện: HR/200, pha SP/DN/DP, DN/SP, DP/SP và cờ có notch. Đầu ra là
một xung 256 điểm chuẩn hóa. Critic không dùng BatchNorm. Cơ sở gradient
penalty: [Gulrajani et al. (2017)](https://arxiv.org/abs/1704.00028).

Pilot: batch 64, Adam 1e-4, 5 bước critic/1 bước generator, GP=10,
1.500 bước generator; thêm loss mốc hình thái trọng số 10. Loss bổ sung
là thiết kế thử nghiệm của dự án, không phải tiêu chuẩn sinh lý.

Chọn checkpoint theo validation; chỉ đánh giá checkpoint được chọn trên
512 xung test. So sánh với Gaussian **preset mặc định, chưa fit** và replay
nhịp train gần nhất theo điều kiện. Replay không dùng nhịp test làm kho mẫu.
Không dùng kết quả test để chọn lại checkpoint hoặc tuyên bố đã tối ưu mạng.

Mã và cách chạy: [ml/README.md](../ml/README.md).
Job riêng tư: [PPG cWGAN GP BIDMC Pilot](https://www.kaggle.com/code/charlesday2612/ppg-cwgan-gp-bidmc-pilot).

## 4. Kết quả thực thi

**Kaggle phiên bản 1 đã COMPLETE, nhưng mô hình chưa đạt yêu cầu để thay bộ
phát.** Đã tải đủ artifact, kiểm tra hash mã nguồn và chạy lại suy luận CPU.
Không đổi checkpoint dựa trên test và không train lại để làm đẹp báo cáo.

- GPU thực tế: Tesla T4. Python 3.12.13, PyTorch 2.10.0+cu128, NumPy 2.0.2.
- Đã chạy đủ 1.500 bước; training và đánh giá khoảng 55 giây. Toàn script
  khoảng 270 giây, phần lớn thời gian là tải dữ liệu/chuẩn bị môi trường.
- Kaggle quota sau job: đã dùng 0,08 giờ GPU, còn 29,92 giờ tại lần kiểm tra.
- Checkpoint được chọn ở bước **100**, validation condition L1=0,09438;
  bước 1.500 là 0,17750. Mô hình không cải thiện đều theo số bước.
- Hash mã train khớp artifact:
  `0894f5aa8b2b37d117c188170c2c460c49f3fd0ec1aaa22aa226a46b103ff60b`.
- Toàn bộ xung đã xử lý và mã chia bệnh nhân trên máy/Kaggle khớp nhau;
  sai khác tối đa của mảng pulse là 0 trong lần kiểm tra này.

### So sánh trên 512 xung test

Trong test đánh giá có 103 điều kiện có notch và 409 không có notch rõ.
Sai số pha tính theo phần của một chu kỳ, không phải giây:

| Chỉ số | GAN | Gaussian mặc định | Replay train |
|---|---:|---:|---:|
| MAE pha SP, theo xung | 0,04778 | 0,11525 | 0,00306 |
| MAE pha SP, trung bình đều theo bệnh nhân | 0,05229 | 0,10864 | 0,00273 |
| Đúng trạng thái có/không notch | 77,93% | 20,12% | 100% |
| Độ nhạy khi yêu cầu có notch | **1,94%** | 100% | 100% |
| Độ đặc hiệu khi yêu cầu không có notch | 97,07% | 0% | 100% |
| Mean pointwise std | 0,04880 | ≈0 | 0,13069 |
| Mean absolute second difference | 0,001426 | 0,000844 | 0,000417 |

GAN: TP=2, FN=101, FP=12, TN=397. Chỉ 14/512 xung đầu ra có notch, trong
đó 12 xung xuất hiện notch khi không được yêu cầu. MAE pha DN=0,04706 và
DP=0,16275 **chỉ tính trên 2 trường hợp cùng có notch**; không thể dùng hai
con số này để kết luận khả năng tái tạo DN/DP tốt. Độ chính xác 77,93% còn
thấp hơn việc luôn dự đoán không notch (409/512=79,88%).

Replay là đối chứng có điều kiện, lựa chọn trực tiếp từ các xung train nên
khả năng khớp mốc cao không đồng nghĩa đã giải được bài toán sinh mẫu mới.
Gaussian đối chứng cố định luôn có notch nên độ đặc hiệu bằng 0 là hệ quả
của preset; chưa so sánh GAN với một Gaussian được tối ưu theo điều kiện.

Hình kiểm tra cho thấy GAN học được bao xung chính nhưng thường bỏ notch,
có gợn giả ở pha sát 0 và 1, và độ đa dạng tổng thể thấp hơn nhịp thật.
Roughness của GAN khoảng 3,61 lần nhịp test thật (0,000395). Độ đa dạng với
cùng một điều kiện là 0,04148, chưa đủ để chứng minh không mode collapse.
Khoảng cách RMSE nhỏ nhất tới 2.048 xung train được lấy mẫu là 0,03465;
đây không phải kiểm tra ghi nhớ trên toàn bộ train hay bảo đảm riêng tư.

**Kết luận:** pipeline huấn luyện/xuất mô hình hoạt động, nhưng pilot thất bại
ở mục tiêu điều khiển notch và độ sạch hình thái. Không triển khai bản này
vào vòng phát DAC. cWGAN-GP vẫn là hướng thử nghiệm hợp lý; kết quả chưa
chứng minh kiến trúc/loss hiện tại là lựa chọn cuối cùng.

### Artifact và kiểm thử

- [Metrics gốc](../ml/runs/kaggle-v1/ppg_run/metrics.json),
  [audit thêm](../ml/runs/kaggle-v1/ppg_run/audit.json),
  [lịch sử train](../ml/runs/kaggle-v1/ppg_run/history.json).
- [Hình so sánh](../ml/runs/kaggle-v1/ppg_run/comparison.png),
  [hình có đánh dấu mốc, gồm nhóm có/không notch](../ml/runs/kaggle-v1/ppg_run/morphology_review.png).
- [CPU TorchScript](../ml/runs/kaggle-v1/ppg_run/generator_cpu.ts): 1.163.059
  byte, khoảng 1,11 MiB; đã kiểm tra batch 1 và batch 3, đầu ra hữu hạn và
  hai đầu chu kỳ bằng 0.
- Suy luận trên máy **x86_64 hiện tại**, 1 thread, batch 1, 200 lượt sau
  warm-up: median 0,0935 ms, P95 0,1087 ms. **Không phải benchmark Pi.**
  PyTorch local 2.14/Python 3.14 cảnh báo TorchScript chưa được hỗ trợ chính
  thức trên Python 3.14; lần thử đã chạy được nhưng nên dùng môi trường
  tương thích và benchmark lại trước triển khai.
- [CSV 100 Hz](../ml/runs/kaggle-v1/ppg_run/ir_red_100hz.csv) có 400 mẫu/4 s;
  [CSV 1000 Hz](../ml/runs/kaggle-v1/ppg_run/ir_red_1000hz.csv) có 4000 mẫu/4 s.
  Đã kiểm tra bước thời gian 1/Fs, rail và AC_RED/AC_IR=0,48.
- Bộ test ứng dụng: **644 passed, 2 skipped, 288 subtests passed**. Một skip
  là nhóm ML trong môi trường ứng dụng không cài dependency ML; bộ ML được
  chạy riêng đầy đủ: **18 passed**. `git diff --check` đạt.
- Skill NeuroKit2 giúp tách phát hiện nhịp khỏi xử lý hình thái; hướng dẫn
  Kaggle CLI được dùng để chạy job riêng tư có giới hạn thời gian; bộ kiểm
  thử Python kiểm tra mốc, chia bệnh nhân, Gaussian và xuất hai kênh.

Kết quả smoke test hai bước trên CPU chỉ xác minh pipeline, không được đưa
vào bảng chất lượng trên. Artifact lớn nằm trong `ml/runs/` đã gitignore;
cần giữ bản trên Kaggle hoặc sao lưu riêng khi chuyển máy.

## 5. Fs và xuất IR/RED

GAN **không tự sinh đồng hồ lấy mẫu**. `256` là số điểm mô tả một chu kỳ
theo pha. Fs nguồn được giữ trong manifest; Fs đầu ra do bộ phát quyết định:

```text
t[n] = n/Fs
phase[n] = (t[n] * HR/60) mod 1
p[n] = nội suy xung GAN tại phase[n]
Số mẫu/chu kỳ = Fs * 60/HR
IR[n]  = DC_IR  ± AC_IR  * p[n]
RED[n] = DC_RED ± AC_RED * p[n]
AC_RED = R * AC_IR * DC_RED/DC_IR
R = max(0, (A - SpO2)/B)
```

Ví dụ HR=75: 100 Hz cho 80 mẫu/nhịp, 1000 Hz cho 800 mẫu/nhịp. Với A=110,
B=25, SpO2=98%, DC hai kênh=1,5 V và AC_IR=45 mV: R=0,48 và AC_RED=21,6 mV.
DC ở đây theo quy ước pedestal của hệ thống, không phải trung bình của toàn
chu kỳ. Quan hệ SpO2 dùng hệ số hiệu chuẩn của bộ mô phỏng, chưa xác nhận
đúng với thiết bị quang học bất kỳ.

BIDMC không có cặp raw IR/RED nên hai kênh này dùng **cùng hình dạng học được**,
khác biên độ/DC; không được mô tả là GAN đã học phổ hấp thụ hai bước sóng.
Muốn học khác biệt hình dạng/độ trễ IR–RED phải có dữ liệu đo đồng bộ hai kênh.

Renderer đã xuất đường dẫn phần mềm cho CSV 100/1000 Hz và kiểm tra rail DAC
0–3,28 V. Xuất 1000 Hz không bổ sung thông tin sinh lý bị mất ở nguồn 125 Hz.
Hệ thống hiện cấu hình mô hình 100 Hz và timer 1000 Hz; **chưa đo Fs thực
trên phần cứng**. Không đổi đường nội suy và clock hiện tại trong lượt này.

## 6. Điều kiện trước khi đưa lên Pi

Không chuyển engine mặc định chỉ vì loss giảm hoặc Kaggle báo hoàn thành.
Cần kiểm duyệt hình thái/nhãn trên nhịp thật, độ nhạy notch theo điều kiện,
khả năng điều khiển mốc, độ đa dạng và hiện tượng lặp mẫu; so với Gaussian
đã fit và replay; lặp nhiều seed và kiểm tra ngoài BIDMC. Không suy diễn
dạng sóng bệnh lý từ tên preset hiện có.

Thứ tự cải thiện được đề xuất từ lỗi quan sát được, chưa thực hiện trong
pilot này:

1. Kiểm duyệt nhãn thật, cân bằng nhóm có/không notch trong train và tính
   validation riêng theo nhóm. Không ép tạo notch cho mọi xung.
2. Sửa ràng buộc biên để giảm gợn giả đầu/cuối chu kỳ; thử loss đạo hàm và
   ràng buộc cực trị DN/DP có mask, điều chỉnh trọng số bằng validation.
3. Thử critic điều kiện mạnh hơn và cặp điều kiện sai để kiểm tra việc mạng
   thực sự sử dụng condition; chạy nhiều seed, theo dõi collapse.
4. So sánh với Gaussian được fit theo cùng mốc và replay. Giữ kết quả pilot
   v1 làm mốc, không dùng test đã xem làm tập tuning. Một vòng cải tiến dựa
   trên báo cáo này cần test/cohort ngoài mới trước tuyên bố tổng quát hóa.

Sau khi mô hình đủ tốt: cache xung ngoài vòng DAC, giữ phần HR/AC/DC/SpO2,
polarity, noise và respiration hiện tại, có fallback Gaussian. Benchmark
trên đúng Pi/OS trước khi chọn runtime; kiểm tra jitter, tốc độ, bộ nhớ,
rail và đo quang thực. Artifact CPU không đồng nghĩa đã triển khai lên Pi.
