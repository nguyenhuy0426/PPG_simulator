# Hướng phát triển generator PPG (2026-10-19)

Tài liệu này tóm tắt các hướng tiếp cận và model tạo sinh khác có thể cải thiện hệ thống, xếp theo mức
lợi ích dự kiến. Thứ tự này là đánh giá kỹ thuật của nhóm, chưa có thí nghiệm nào trong repo kiểm chứng.
Mỗi tài liệu đều đã được kiểm tra trên Crossref, arXiv hoặc trang của hội nghị; phần mô tả nội dung lấy
từ abstract, chưa đọc toàn văn.

## Điều kết quả hiện tại cho thấy

- Nhịp được điều khiển chính xác nhờ scaffold dựng sẵn. Đây là điểm mạnh nên giữ cho mọi model sau này.
- Hai thứ còn thiếu là texture 5–8 Hz và chuyển động: probe phát hiện PhysioMix trên GalaxyPPG ở dải
  5–8 Hz, và bộ phát hiện nhịp thấy tín hiệu tổng hợp *dễ hơn* tín hiệu thật (Bảng 8 của bài báo).
- PhysioFlow cần 31 lần chạy mạng cho một strip, chậm khoảng 140 lần so với PhysioMix; chưa đo trên Pi.
- Dữ liệu ít người (MIMIC-AF, WRIST-EX, MIMIC-nonAF) gây học thuộc ở PhysioFlow.

## 1. Đưa chuyển động và nhiễu cảm biến thành đầu vào điều khiển (ưu tiên cao nhất)

Làm giống cách scaffold đã làm với nhịp: chuyển động được *áp đặt* chứ không để model học như một thành
phần tuần hoàn tự do (`m(t)` hiện nay). Có hai cách:

- **Dùng gia tốc kế làm điều kiện.** WRIST-EX và GalaxyPPG đều có dữ liệu gia tốc kế. Model nhận tín hiệu
  gia tốc kế và sinh PPG bị nhiễu tương ứng, nên độ khó của strip trở thành một tham số người dùng chọn được.
- **Thư viện nhiễu đo thật.** Tách artefact từ bản ghi thật rồi cộng vào strip sạch theo mức SNR chọn trước.
  Cách này đơn giản, dễ kiểm chứng và không cần train lại model lớn.

Cách đo tiến bộ: dùng chính thử nghiệm bộ phát hiện nhịp của bài báo. Mục tiêu là tỉ lệ "trong 5 bpm" trên
tín hiệu tổng hợp tiến gần tỉ lệ trên tín hiệu thật ở cùng bối cảnh.

## 2. Giảm số bước sampling của PhysioFlow để chạy được trên Pi

- **Reflow** của rectified flow ([Liu et al., ICLR 2023](https://arxiv.org/abs/2209.03003)): làm thẳng
  quỹ đạo để giảm số bước Heun.
- **Consistency models** ([Song et al., ICML 2023, PMLR 202](https://proceedings.mlr.press/v202/song23a.html)):
  chưng cất (distill) thành 1–2 bước.
- **MeanFlow** ([Geng et al., arXiv 2505.13447, 2025](https://arxiv.org/abs/2505.13447)): sinh mẫu trong một
  bước. Đây mới là preprint; mình chưa kiểm tra nó đã được bình duyệt hay chưa.

Mục tiêu đặt ra (chưa đo): một strip 30 s mất dưới 1 s trên Cortex-A72. Phải đo bằng
`scripts/verify_generators_on_pi.py`.

## 3. Thử các kiến trúc sinh tín hiệu bên ngoài làm baseline

Reviewer Q1 sẽ hỏi vì sao không so với model bên ngoài. Điều kiện bắt buộc: model ngoài phải nhận cùng
scaffold nhịp, nếu không sẽ mất khả năng điều khiển nhịp.

- **Diffusion-TS** ([Yuan & Qiao, ICLR 2024](https://arxiv.org/abs/2403.01742)): diffusion dựa trên
  transformer, tách trend và seasonal; có code công khai.
- **UniCardio** ([Chen et al., *Nature Machine Intelligence* 8:6–19, 2026](https://doi.org/10.1038/s42256-025-01147-y)):
  diffusion transformer hợp nhất cho nhiều loại tín hiệu tim mạch (PPG, ECG, BP).
- **BG-Diff** ([Kang et al., *IEEE Sensors J.* 24(20), 2024](https://doi.org/10.1109/JSEN.2024.3451453)):
  diffusion có dẫn hướng để sinh PPG từ ít mẫu, hợp với các tập nhỏ như MIMIC-AF.
- **TimeGAN** ([Yoon et al., NeurIPS 2019](https://papers.nips.cc/paper/2019/hash/c9efe5f26cd17ba6216bbe2a7d26d490-Abstract.html)):
  baseline GAN chuỗi thời gian kinh điển, đã có sẵn trong `refs.bib`.

## 4. Mô hình lai vật lý và học máy cho hai kênh IR và đỏ

View hiện tại chỉ có một kênh đã chuẩn hoá, nên không dùng để kiểm thử SpO₂ được.

- **PPGen / hybrid amortized inference** ([Behrmann et al., arXiv 2510.02073, 2025](https://arxiv.org/abs/2510.02073)):
  ghép mô phỏng truyền ánh sáng trong mô với phần sửa sai do học máy.
- **Cơ sở dữ liệu sóng mạch** ([Charlton et al., 2019](https://doi.org/10.1152/ajpheart.00218.2019)):
  mô phỏng huyết động, có thể làm "lõi vật lý" cho morphology.

Hướng này lâu dài và cần đường quang đã được kiểm chứng (phần (1) của bạn) trước khi có ý nghĩa.

## 5. Mô hình nhịp tốt hơn log-normal độc lập

Scaffold hiện nay vẽ các IBI log-normal **độc lập**, nên không có cấu trúc tuần tự của rung nhĩ (AF) hay
ngoại tâm thu.

- Thay bằng mô hình nhịp có tương quan dài hạn, như framework tham số hoá ECG/PPG của
  [Karhinoja et al., *CMPB* 287:109639, 2026](https://doi.org/10.1016/j.cmpb.2026.109639).
- Hoặc dùng mô hình AF của Sološenko et al. (đã có trong `refs.bib`) cho chế độ loạn nhịp.

Scaffold vẫn tách khỏi phần sinh dạng sóng, nên đổi mô hình nhịp không cần train lại generator.

## 6. Dữ liệu và đánh giá

- **Thêm người để giảm học thuộc**, ưu tiên các tập có ECG tham chiếu.
- **Phép thử mới trên cổ tay đời thường.** PPG-DaLiA và WESAD đều dùng Empatica E4 (mình nhớ vậy nhưng chưa
  kiểm tra lại). Đây là dữ liệu chưa dùng lần nào, đúng thứ phần Discussion của bài nói là cần để thử luật
  quyết định ghép cặp.
- **Thử nghiệm bộ phát hiện ở mức từng nhịp** (sai số thời điểm đỉnh), không chỉ ở mức nhịp tim trung bình.

## Không nên làm cho bài báo hiện tại

Không nên train thêm hay finetune trên tập test đã dùng. Tập test đã được báo cáo, nên mọi vòng mới cần
luật mới (viết trước khi train) và người thử mới.
