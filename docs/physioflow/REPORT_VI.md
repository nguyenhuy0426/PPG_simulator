# PhysioFlow: mô hình mới cho PPG simulator (vòng 10)

Ngày 2026-10-12. Cùng dữ liệu v3 (SHA-256 `5036fb64…6433`), cùng tiêu chí khoá trước như PhysioMix (`813c4dd1…`):
S_arm = S_real + 0,5·C + 0,5·max(0, AUC_C2ST đạo hàm − 0,5), chỉ dùng validation. Trang web `docs/model-report`
mục 4 trình bày lại phần này kèm sơ đồ.

## Vì sao một mô hình mới

PhysioMix (GAN) điều khiển nhịp tốt, nhưng một CNN chuyên tách thật/giả vẫn nhận ra mẫu sinh qua đạo hàm dạng sóng
(AUC 0,80–0,84 ở vòng 9), và 9 vòng GAN chủ yếu là chỉnh độ ổn định (R1, ngưỡng cắt gradient). Các công trình gần đây
về tín hiệu sinh lý dùng họ diffusion / flow matching
([FlowECG](https://arxiv.org/abs/2509.10491), [VAMP-Diff](https://arxiv.org/pdf/2605.22851)): không có mạng đối kháng,
một loss hồi quy, phủ phân bố tốt hơn. Mô hình khuếch tán thuần trong v2 lại điều khiển HR sai 4,3 bpm, nên PhysioFlow
giữ phần mạnh nhất của PhysioMix: **nhịp dựng sẵn**.

## Kiến trúc (`ml/kaggle_multidomain/flow.py`)

- **Khung nhịp**: đỉnh tâm thu từ HR và độ bất thường (khoảng nhịp log-normal), mã hoá thành pha sin/cos + cờ có khung.
  Lúc train, khung lấy từ đỉnh phát hiện được của chính cửa sổ thật (sửa đỉnh bị sót/trùng); cửa sổ có nhãn HR bị che
  (87% cổ tay, ~1/3 AF) không có khung, và lúc sinh cũng chỉ thêm khung khi điều kiện có cờ “đã biết HR”.
- **U-Net 1D** 6,9 triệu tham số: 5 tầng 1 200 → 75 mẫu, attention ở 150 và 75 mẫu, FiLM theo thời điểm t và điều kiện
  (tập dữ liệu, cờ nhãn, HR, độ bất thường, độ lớn), classifier-free guidance (bỏ điều kiện 10% lúc train).
- **Rectified flow**: x_t = (1 − t)·x + t·ε, mạng đoán vận tốc v = ε − x; loss MSE + loss sai lệch đạo hàm bậc một của
  ước lượng x (trọng số (1 − t)²); t chọn **đều** trong (0, 1).
- **Sinh**: 16 bước Heun từ nhiễu (t = 1) tới t = 0 (31 lần gọi U-Net), chuẩn hoá 0–1; không lọc ở đầu ra, không critic.
  TorchScript: U-Net trace một lần, vòng lặp lấy mẫu dạng script (khớp tuyệt đối với bản Python).
- Thời gian sinh 30 s: ~1,4 s trên 1 luồng CPU laptop, ~1,8 s trên CPU Kaggle. Pi chưa đo.

## Vòng lặp kỹ thuật (pilot = seed 42, validation)

Bằng chứng từng vòng: `docs/physioflow/loop/pilot{1,2,3}.json`, thử nghiệm bộ lấy mẫu `probe_loop2_samplers.json`.

| Vòng | Thay đổi | S_arm | S_real | AUC đạo hàm | Q cổ tay | Kết luận |
|---|---|---|---|---|---|---|
| 1 | Khung nhịp luôn bật; có/không loss đạo hàm | 0,610 | 0,468 | 0,750 | 1,180 | Cổ tay rất kém: khung bị ép lên cửa sổ vốn không đo được nhịp |
| 2 | Khung theo cờ “đã biết HR”; loss đạo hàm 1 / 0,3 | 0,537 | 0,391 | 0,696 | 0,974 | Gần PhysioMix; phần thua nằm ở phổ log |
| 3 | t đều / trộn; thử “dừng ở t = 0,04 + lọc” | **0,470** | 0,348 | 0,697 | 0,755 | t đều thắng; “dừng + lọc” bị CNN bắt (AUC 0,99), loại |
| PhysioMix vòng 9 | (mốc, 3 seed) | 0,530 ± 0,029 | 0,344 | 0,827 | 0,527 | |

Chẩn đoán giữa vòng 2 và 3 (trên laptop, checkpoint vòng 2): phổ log thay đổi mạnh theo vài bước lấy mẫu cuối (lưới
bước mịn ở cuối làm GXU 0,075 → 1,04), trong khi khi train logit-normal chỉ cho dưới 0,2% số lần t < 0,05. Mô hình
nhiễu nền khớp từ dữ liệu train làm mọi tập kém đi (phần > 10 Hz của dữ liệu thật chủ yếu là hài còn sót sau bộ lọc,
không phải nhiễu) nên bị bỏ. Pilot 1 dừng khi trace bộ lấy mẫu 16 bước (đồ thị trải mọi bước); đã thay bằng xuất script.

## Vòng 4: 3 seed, quy tắc khoá trước

Quy tắc (`rules/FROZEN_ROUND10.json`, ghi trước khi train 3 seed; viết từ vòng 1, trước mọi lần train PhysioFlow):
PhysioFlow thay PhysioMix chỉ khi mọi seed qua cổng, S_arm tốt hơn quá SD gộp, S_real không kém quá 0,05 **và Q cổ tay
không kém quá SD gộp** (giữ thành quả cổ tay của vòng 9). Cổng thời gian cho flow: < 5 s / cửa sổ 30 s trên 1 luồng CPU.

| Seed | S_arm | S_real | C | AUC đạo hàm | Q cổ tay | Bước tốt nhất | Chấm trên |
|---|---|---|---|---|---|---|---|
| 42 | **0,472** | 0,370 | 0,027 | 0,678 | 0,857 | 8 000 | CPU laptop |
| 123 | 0,475 | 0,356 | 0,022 | 0,715 | 0,827 | 14 000 | GPU Kaggle |
| 2026 | 0,500 | 0,379 | 0,026 | 0,716 | 0,694 | 8 000 | CPU laptop |
| **Trung bình** | **0,482 ± 0,015** | 0,368 | | 0,703 | 0,793 | | |
| PhysioMix vòng 9 | 0,530 ± 0,029 | 0,344 | 0,045 | 0,827 | 0,527 | | |

**Quyết định: PhysioMix vẫn là model mặc định của app.** S_arm tốt hơn rõ (chênh 0,048 > SD gộp 0,023), S_real đạt
(0,368 ≤ 0,394), mọi seed qua cổng, nhưng Q cổ tay 0,793 > 0,527 + 0,074. PhysioFlow seed 42 (S_arm thấp nhất) được
đóng gói vào app như chế độ nghiên cứu “PhysioFlow · flow matching” để so sánh trực tiếp (commit `9999bf22`).

Ghi chú: trong vòng cuối, ba seed chạy song song (hai seed chung một GPU); cả ba train xong 20 000 bước, seed 123 chấm
xong trên Kaggle rồi tiến trình chết khi chấm hai seed còn lại (lần chạy lại trên Kaggle không gắn được output của kernel
lỗi). Seed 42 và 2026 được chấm trên CPU laptop bằng đúng `score_arm` (`--resume-from`); bộ đếm ổn định khi train của hai
seed này mất cùng tiến trình.

GXU test (niêm phong tới vòng 3, chỉ báo cáo; `rules/GXU_TEST_seed42.json`): seed 42 Q 0,130 (độ phủ 95%, độ giống 94%)
so với PhysioMix vòng 9 trung bình 0,194; sàn dữ liệu thật (train replay) 0,078. Chỉ seed 42 được chấm trên CPU laptop:
tiến trình dừng trước hai seed còn lại (nhiều khả năng do bộ nhớ khi chạy song song), nên số này là một seed.

## Vòng 5: nhắm riêng vào cổ tay (sau quyết định vòng 4)

Bằng chứng: `loop/probe_loop5_wrist.json` (chẩn đoán và thử trên laptop), `loop/pilot5.json`,
`rules/PILOT_SELECTION_LOOP5.json`.

**Chẩn đoán** (laptop CPU, checkpoint seed 42 đang có trong app, validation, cùng nhiễu như `score_arm`; Q cổ tay tái
lập đúng 0,857):

- 75% MMD phổ log cổ tay (0,287 / 0,385) nằm ở dải 12–20 Hz. Ở đó mẫu sinh cao hơn dữ liệu thật 0,86 bậc log10. Dữ liệu
  thật nằm đúng sàn 1e-8 sau bộ lọc 0,5–8 Hz, còn mẫu sinh vẫn sót nhiễu nền trải đều theo thời gian. Trong dải 0,5–8 Hz
  phổ log khớp tốt. Năng lượng 0,5–1 Hz cao gấp đôi nếu tính tuyến tính, nhưng gần như không góp vào MMD.
- Khử nhiễu một bước từ x_t đúng phân bố train chỉ dư 0,25 bậc (GXU 0,17). Phần dư lớn của cổ tay (0,72–0,77) sinh ra
  trên quỹ đạo lấy mẫu ở t 0,75–1: nếu bắt đầu từ x_0,75 thật thì phần dư chỉ còn 0,46. Đây là lệch train/sinh của một
  tập chỉ có 83 cửa sổ.
- Loại: lấy mẫu cổ tay nhiều hơn (cổ tay đã chiếm 1/6 mỗi batch, gấp ~12 lần tỉ lệ thật, và Q cổ tay xấu dần khi train
  lâu); đổi khung nhịp cho cổ tay (ép tắt khung, phổ log vẫn 0,34); lọc ở đầu ra (đã bị C2ST bắt ở vòng 3).

**Thử trên laptop** (fine-tune 400 bước, chỉ để xem cơ chế, so với đối chứng cùng điều kiện): loss phổ log toàn dải
làm cổ tay và GXU xấu đi (0,50 → 0,77; 0,07 → 0,14). Nhiễu đầu vào chống exposure bias (γ 0,1 / 0,3) cũng làm cổ tay
xấu đi. Chỉ loss phổ log **dải chặn** (0,1–0,5 Hz và > 8 Hz) giúp, và ít (Q cổ tay 0,88 → 0,81).

**Pilot** (Kaggle 2 × T4, seed 42, 20 000 bước): F6 + loss phổ log dải chặn trên ước lượng x0 ở t < 0,25, trọng số 1
(F7) và 3 (F8). Ngưỡng đi tiếp được ghi trong code trước khi chạy (commit `40c9d1b0`): Q cổ tay ≤ 0,601 **và**
S_arm ≤ 0,487.

| | S_arm | S_real | C | AUC đạo hàm | Q cổ tay | log-PSD cổ tay |
|---|---|---|---|---|---|---|
| Vòng 4, seed 42 (F6) | 0,472 | 0,370 | 0,027 | 0,678 | 0,857 | 0,385 |
| F7 (dải chặn, 1) | 0,505 | **0,297** | 0,199 | 0,718 | **0,524** | 0,112 |
| F8 (dải chặn, 3) | 0,517 | 0,305 | 0,213 | 0,712 | 0,560 | 0,122 |
| PhysioMix vòng 9 (3 seed) | 0,530 | 0,344 | 0,045 | 0,827 | 0,527 | |

Train từ đầu, loss dải chặn sửa được cổ tay (Q 0,857 → 0,524, ngang PhysioMix) và cải thiện S_real ở mọi tập trừ
PERform Large. Nhưng ở cổ tay, mạng không còn bám khung nhịp chậm: lệnh 40–80 bpm cho ra 67–131 bpm (Spearman cổ tay
0,83 / 0,80; năm tập còn lại vẫn 1,0). Vì vậy C tăng từ 0,027 lên 0,199 và S_arm vượt ngưỡng.

**Quyết định: theo ngưỡng khoá trước, không chạy final 3 seed. PhysioMix vòng 9 vẫn là model của app; PhysioFlow
trong app vẫn là seed 42 của vòng 4.** Hướng tiếp theo nếu làm: giữ loss dải chặn và sửa riêng việc bám nhịp chậm của
cổ tay. Dữ liệu cổ tay khi vận động gần như không có nhịp < 80 bpm, nên việc bám nhịp chậm ở đây là ngoại suy.

## Giống người thật đến đâu (người chưa dùng để train)

`ml/runs/realism-v1/realism_round10.json` (laptop CPU; số của PhysioMix trùng khớp với lần đo vòng 9). Mỗi ô: độ giống ·
độ phủ · không phân biệt được (CNN đạo hàm, chia theo người, 3 lần lặp).

| Tập | PhysioFlow (seed 42, app) | PhysioMix vòng 9 (app) | LSM-GAN | Thật · người khác (trần) |
|---|---|---|---|---|
| GXU ngón tay, 44 người | 96 · **92** · **50%** | 95 · 76 · 9% | 12 · 0 · 0% | 98 · 99 · 94% |
| PERform Large, 191 người | 97 · **88** · **91%** | 98 · 63 · 36% | 97 · 1 · 0% | 98 · 95 · 97% |
| BIDMC, 14 người | **57** · **84** · **67%** | 49 · 67 · 45% | 79 · 2 · 0% | 51 · 88 · 96% |
| PERform AF, 4 người | 57 · **95** · **82%** | 51 · 46 · 7% | 27 · 1 · 0% | 55 · 83 · 56% |
| PERform không AF, 2 người | 11 · 41 · 39% | 10 · 94 · 80% | 5 · 0 · 0% | 11 · 18 · 59% |
| Cổ tay vận động, 4 người | 65 · 61 · 52% | **92** · 56 · 52% | 0 · 0 · 0% | 77 · 54 · 92% |

- Bám lệnh trạng thái (CNN 7 trạng thái chỉ học trên dữ liệu thật, đoán mò 14%): PhysioFlow 68%, PhysioMix 54%, dữ liệu
  thật 51%; “cùng nhiễu, đổi lệnh” 71% so với 49%. Lệnh “cổ tay vận động” được nhận đúng 94% (thật 86%). Cao hơn cả dữ
  liệu thật nghĩa là mẫu PhysioFlow “đúng kiểu” trạng thái hơn người thật, tức đa dạng ít hơn (rho validation 0,87–0,89).
- Kiểm tra chép dữ liệu (tương quan lớn nhất với cửa sổ train cùng tập, thử mọi độ dịch; trung vị · % > 0,99): ngang
  người thật ở mọi tập trừ cổ tay (0,46 so với 0,28; không cửa sổ nào > 0,99). BIDMC 1% và không AF 2% số cửa sổ > 0,99
  (PhysioMix: 0%): có dấu hiệu nhớ một ít cửa sổ ở tập rất nhỏ.
- LSM-GAN (để so sánh, theo yêu cầu): ở BIDMC — tập nó được train — 79 · 2 · 0% trong dải chung 0,5–8 Hz và 88 · 2 · 37%
  khi chấm trong chính dải 0,9–5 Hz của nó (`realism_lsm_narrow.json`): gần như luôn sinh một kiểu sóng (mode collapse),
  không nhận điều kiện (bám lệnh 14% = đoán mò).


## Giới hạn

- Đây là độ giống phân bố của PPG đã lọc 0,5–8 Hz và độ chính xác điều khiển nhịp; không phải SpO₂, không có cặp IR/RED
  thật, không phải kiểm chứng lâm sàng. Validation đã dùng qua nhiều vòng (PhysioMix và PhysioFlow), nên điểm validation
  hơi lạc quan; GXU test đã mở từ vòng 3 và chỉ để báo cáo.
- Cổ tay chỉ có 4 người, 83 cửa sổ train: PhysioFlow bám sát các cửa sổ train cổ tay hơn mức người thật (kiểm tra chép
  dữ liệu), và phổ cổ tay vẫn khác thật, chủ yếu do nhiễu sót ở 12–20 Hz (vòng 5).
- Chạy chậm hơn PhysioMix ~100 lần (giây so với mili giây); app chạy nó trong tiến trình riêng, không chặn DAC. Chưa đo
  trên Pi/DAC/OPT101.
