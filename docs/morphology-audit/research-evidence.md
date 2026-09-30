# PPG morphology: evidence register

Tra cứu ngày 28/09/2026. Đây là rà soát có mục tiêu phục vụ quyết định thiết kế app,
không phải systematic review, không tuyên bố bao quát mọi paper/diễn đàn. Đã tìm trên
web và kiểm tra nguồn tại PubMed/PMC, Nature, Frontiers, IEEE Xplore, kho tác giả/
trường đại học, PhysioNet và cộng đồng mã nguồn. `parallel-cli` của workflow Research
Lookup không có trong môi trường; dùng tìm kiếm web và trang nguồn trực tiếp.

Các nhóm truy vấn đã dùng: PPG standard waveform/systolic peak/dicrotic notch;
age-related pulse shape/body sites; contact pressure/WF-PPG; digital filtering phase
distortion; Gaussian synthesis/PPGSynth; pyPPG fiducials; EMBC pulse morphology
quality; I2MTC dicrotic notch. Tìm ngược tài liệu dẫn trong bài Gaussian và tài liệu
pyPPG. Chọn nguồn có mô tả phép đo, thuật toán hoặc dữ liệu; không chọn theo việc
hình minh họa giống app. Không dùng số trích dẫn hay nội dung diễn đàn làm trọng số.

“Đoạn toàn văn được lập chỉ mục” nghĩa là đã đọc phần nội dung do công cụ tìm kiếm
trả về từ bài gốc, không đồng nghĩa đã truy cập/đọc toàn bộ PDF. Một số lần mở PMC/
Nature bị CAPTCHA hoặc timeout. Các giới hạn truy cập được ghi riêng dưới đây.

| ID | Nguồn đã xác minh | Mức truy cập | Kết quả liên quan và giới hạn áp dụng |
|---|---|---|---|
| R1 | Allen J, Murray A. (2003). *Age-related changes in the characteristics of the photoplethysmographic pulse shape at various body sites*. Physiological Measurement 24(2):297–307. [DOI 10.1088/0967-3334/24/2/306](https://doi.org/10.1088/0967-3334/24/2/306); [kho tác giả](https://pureportal.coventry.ac.uk/en/publications/age-related-changes-in-the-characteristics-of-the-photoplethysmog/) | Abstract đầy đủ + metadata ở kho trường | 116 người khỏe, 13–72 tuổi, tai/ngón tay/ngón chân. Sườn lên dài hơn và notch mờ hơn theo tuổi. Không suy ra một độ sâu notch chung cho mọi người. |
| R2 | Tang Q, Chen Z, Ward R, Elgendi M. (2020). *Synthetic photoplethysmogram generation using two Gaussian functions*. Scientific Reports 10:13883. [DOI 10.1038/s41598-020-69076-x](https://www.nature.com/articles/s41598-020-69076-x) | Toàn văn HTML, phương pháp/kết quả | Mô hình fit các template thực; dạng có đỉnh phụ rõ và dạng ít rõ đều được xét. Gaussian có thể hữu ích khi được fit; tên kiến trúc không bảo đảm tính thực. Chỉ một template mỗi lớp trong thí nghiệm hình thái, không phải chuẩn dân số. |
| R3 | Tang Q, Chen Z, Allen J, Alian A, Menon C, Ward R, Elgendi M. (2020). *PPGSynth: An Innovative Toolbox for Synthesizing Regular and Irregular Photoplethysmography Waveforms*. Frontiers in Medicine 7:597774. [DOI 10.3389/fmed.2020.597774](https://www.frontiersin.org/journals/medicine/articles/10.3389/fmed.2020.597774/full) | HTML bài gốc + metadata/PDF được lập chỉ mục | Công cụ tổng hợp cả nhịp đều và không đều; là mô hình mô phỏng, không là chứng nhận rằng một template duy nhất là bình thường. [Mã do tác giả công bố](https://github.com/Elgendi/PPG-Synthesis) là nguồn triển khai bổ sung. |
| R4 | Ho MY, Pham HM, Saeed A, Ma D. (2025). *WF-PPG: A Wrist-finger Dual-Channel Dataset for Studying the Impact of Contact Pressure on PPG Morphology*. Scientific Data 12:200. [DOI 10.1038/s41597-025-04453-7](https://www.nature.com/articles/s41597-025-04453-7); [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11790827/) | Các đoạn toàn văn Background/Methods/classification được lập chỉ mục; mở trực tiếp bị chặn | 27 người; wrist/finger đồng thời, thay đổi lực ép. Phân loại 1, 2E, 2L, 1L, 3. Type 2L có đỉnh trái nổi trội, notch và đỉnh phụ nhỏ hơn; là mục tiêu “ideal” trong bối cảnh nghiên cứu lực ép, không chuẩn cho mọi tuổi/vị trí/bệnh. Không đồng nhất mọi sóng thiếu notch với nhiễu. |
| R5 | Goda MÁ, Charlton PH, Behar JA. (2024). *pyPPG: a Python toolbox for comprehensive photoplethysmography signal analysis*. Physiological Measurement 45(4):045001. [DOI 10.1088/1361-6579/ad33a2](https://doi.org/10.1088/1361-6579/ad33a2); [PubMed](https://pubmed.ncbi.nlm.nih.gov/38478997/); [tài liệu tác giả](https://pyppg.readthedocs.io/en/latest/) | Metadata/abstract + đoạn toàn văn PMC + tài liệu chính thức | Chuẩn hóa định nghĩa các mốc và biomarker; không cung cấp một vector xung “chuẩn nhất”. Detector trong repo này không phải pyPPG, nên không được mượn độ chính xác công bố của pyPPG. |
| R6 | Lapitan DG, Rogatkin DA, Molchanova EA, Tarasov AP. (2024). *Estimation of phase distortions of the photoplethysmographic signal in digital IIR filtering*. Scientific Reports 14:6546. [DOI 10.1038/s41598-024-57297-3](https://www.nature.com/articles/s41598-024-57297-3) | Toàn văn HTML, phần kết quả bộ lọc | Loại bộ lọc/băng thông ảnh hưởng thời điểm đỉnh và hình dạng. Không áp dụng một ngưỡng phổ từ bài này cho mọi dataset. So sánh app cần công khai tiền xử lý, không lọc riêng một model cho đẹp rồi chấm ngang nhau. |
| R7 | Pal R, Rudas Á, Kim S, Chiang JN, Barney A, Cannesson M. (2024). *An algorithm to detect dicrotic notch in arterial blood pressure and photoplethysmography waveforms using the iterative envelope mean method*. Computer Methods and Programs in Biomedicine 254:108283. [DOI 10.1016/j.cmpb.2024.108283](https://doi.org/10.1016/j.cmpb.2024.108283); [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11323035/) | Đoạn toàn văn Introduction/Methods được lập chỉ mục | Xét cả notch ít rõ; định vị notch là bài toán riêng. Cực tiểu nhìn thấy trên PPG trong audit hiện tại không được coi là ground truth đóng van động mạch chủ. Không triển khai IEM trong lượt này. |
| R8 | Papini G, Fonseca P, Aubert X, Overeem S, Bergmans JWM, Vullings R. (2017). *Photoplethysmography beat detection and pulse morphology quality assessment for signal reliability estimation*. IEEE EMBC, pp.117–120. [DOI 10.1109/EMBC.2017.8036776](https://doi.org/10.1109/EMBC.2017.8036776); [kho tác giả](https://research.tue.nl/en/publications/photoplethysmography-beat-detection-and-pulse-morphology-quality-/) | Abstract + metadata đầy đủ | Đánh giá chất lượng bằng tương đồng với template từ các nhịp xung quanh. Ủng hộ mốc tham chiếu có ngữ cảnh; không đồng nghĩa template đó là chuẩn cho người khác. |
| R9 | Forster P, Laska B, Goubran R, Wallace B, Liu P, Sveistrup H. (2025). *Method for the Measurement of the Dicrotic Notch in the Photoplethysmography Signal*. IEEE I2MTC, 19–22 May 2025. [DOI 10.1109/I2MTC62753.2025.11079209](https://ieeexplore.ieee.org/document/11079209/); [mục lục proceedings](https://www.proceedings.com/content/081/081236webtoc.pdf) | Abstract IEEE; tác giả đối chiếu mục lục proceedings; chưa đọc toàn văn | Phân rã Gaussian và kiểm tra synthetic/MIMIC-III. Là bằng chứng về cách đo hình thái, không đủ để lấy một thông số notch cố định hay sao chép kết quả hiệu năng vào app. |
| R10 | Pimentel M, Johnson A, Charlton P, Clifton D. (2018). *BIDMC PPG and Respiration Dataset*, v1.0.0. [DOI 10.13026/C2208R](https://physionet.org/content/bidmc/1.0.0/) | Trang dữ liệu chính thức | 53 recording, mỗi recording 8 phút, các tín hiệu liên tục 125 Hz, bệnh nhân nặng tại BIDMC. Nhãn chuyên gia là nhịp thở; không phải nhãn notch. Dataset không phải cohort khỏe để lập khoảng bình thường. |
| R11 | Zahedi E, Chellappan K, Mohd Ali MA, Singh H. (2007). *Analysis of the effect of ageing on rising edge characteristics of the photoplethysmogram using a modified Windkessel model*. Cardiovascular Engineering 7(4):172–181. [DOI 10.1007/s10558-007-9037-5](https://doi.org/10.1007/s10558-007-9037-5); [PubMed](https://pubmed.ncbi.nlm.nih.gov/17992571/) | Abstract được lập chỉ mục | Thí nghiệm nhỏ 15 người, phù hợp với việc tuổi ảnh hưởng sườn lên. Không đủ quy định dải thời gian “chuẩn” cho dân số. |
| R12 | Pham HM, Ho MY, Zhang Y, Spathis D, Saeed A, Ma D. (2025). *Reliable wrist PPG monitoring by mitigating poor skin sensor contact*. Scientific Reports. [DOI 10.1038/s41598-025-31883-5](https://www.nature.com/articles/s41598-025-31883-5); [mã tác giả](https://github.com/manhph2211/CP-PPG) | Đoạn toàn văn data preparation/kết quả được lập chỉ mục + metadata tác giả | Dùng 22 người từ WF-PPG trong thí nghiệm học máy, không phải tổng số người của dataset gốc. “Ideal” dựa trên finger tham chiếu cùng thời điểm; không phải một template cố định cho mọi người. |

Diễn đàn/cộng đồng: đã tìm được đầu mối như [PulseVision trên Reddit](https://www.reddit.com/r/BiomedicalDataScience/comments/1w7nj1e/pulsevision_synthetic_ppg_waveform_visualizer/)
và kho PPG-Synthesis. Không đưa bài đăng diễn đàn vào bằng chứng xác định sinh lý
bình thường, không lấy hình không rõ nguồn làm nhãn real. Danh sách paper được
chấp nhận ở EMBC 2026 chỉ xác nhận tiêu đề xuất hiện, không thay thế toàn văn.

Điểm nhất quán: cần đối chiếu PPG theo vị trí, đối tượng, thiết bị, chất lượng và
tiền xử lý. Điểm dễ mâu thuẫn: “notch rõ là ideal” trong một nghiên cứu lực ép ở
người trẻ không suy ra “không notch là giả” ở bệnh nhân nặng hoặc người lớn tuổi.
Đây là lý do vẫn giữ hai biến thể có/không có notch trong cùng một generator.

Chưa xác minh: một cohort ngoài BIDMC, nhãn chuyên gia cho landmark của repo,
các thông số quang học IR/RED thực, khả năng tổng quát hóa sau khi chọn model.
Không có nguồn nào trong tập đã kiểm tra đủ để tuyên bố app đạt chuẩn thiết bị y tế.
