# Tài liệu tham khảo của toàn dự án PPG Simulator

Tổng hợp ngày 2026-11-04 từ các nguồn mà chính repo đã trích dẫn (tài liệu `.md`, `docs/effect_HR_SpO2_RR_to_PPG.docx`, các PDF trong `docs/`, comment trong thư mục `hardware/`). Tiêu đề và tác giả lấy theo cách repo ghi; mục nào repo không ghi tác giả thì ở đây cũng để trống, không tự điền.

Lưu ý khi đưa vào báo cáo:
- Chưa mở lại từng đường link để kiểm tra còn truy cập được; hãy đối chiếu trước khi nộp.
- Nhóm D: tiêu đề tôi điền theo mã arXiv/OpenReview/NeurIPS mà repo trích (repo chỉ ghi tên tắt); nên đối chiếu lại trên trang gốc.
- Nhóm G gồm một số nguồn không phải bài báo bình duyệt (Wikipedia, ResearchGate, Reddit, YouTube, Emergent Mind). Nên thay bằng bản gốc hoặc bỏ nếu báo cáo yêu cầu nguồn học thuật.
- Nội dung hình dạng sóng, mô phỏng và độ chính xác SpO2 trong dự án không phải xác nhận lâm sàng; không viết như vậy trong báo cáo.

---

## A. Datasheet và tài liệu linh kiện phần cứng

1. Microchip. *MCP4725: 12-Bit Digital-to-Analog Converter with EEPROM Memory in SOT-23-6* (DS22039). https://ww1.microchip.com/downloads/aemDocuments/documents/MSLD/ProductDocuments/DataSheets/MCP4725-Data-Sheet-20002039E.pdf. Bản nội bộ: `docs/ds_linhkien/MCP4725-Data-Sheet.pdf`.
2. Texas Instruments. *OPT101 datasheet*. https://www.ti.com/lit/ds/symlink/opt101.pdf. Bản nội bộ: `docs/ds_linhkien/opt101.pdf`. Bản vẽ vỏ: NTC (R-PDIP-T8), MPDI059, tháng 4/2001.
3. Texas Instruments. *LM358 datasheet*. https://www.ti.com/lit/ds/symlink/lm358.pdf. Bản nội bộ: `docs/ds_linhkien/lm358ba.pdf`.
4. onsemi. *2N4401 datasheet*. https://www.onsemi.com/pdf/datasheet/2n4401-d.pdf.
5. *2SC1815L-GR datasheet* (dùng để so thứ tự chân E-B-C với 2N4401). `docs/ds_linhkien/2SC1815L-GR.PDF`.
6. Texas Instruments. *OPA333 datasheet*. https://www.ti.com/lit/ds/symlink/opa333.pdf.
7. Texas Instruments. *ADS1115 datasheet*. https://www.ti.com/lit/ds/symlink/ads1115.pdf.
8. Vishay. *BPW34 datasheet*. https://www.vishay.com/docs/81521/bpw34.pdf.
9. Datasheet LED đỏ 3,3 mm và LED hồng ngoại 3,3 mm. `docs/ds_linhkien/red_led_3.3mm_datasheet.pdf`, `docs/ds_linhkien/IR_led_3.3mm_datasheet.pdf`.
10. Raspberry Pi. *Raspberry Pi 4 datasheet*. `docs/ds_linhkien/raspberry-pi-4-datasheet.pdf`. Và [tài liệu GPIO](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html) (GPIO2/3 có pull-up cố định).
11. Seeed Studio. *Grove Base Hat for Raspberry Pi*: https://wiki.seeedstudio.com/Grove_Base_Hat_for_Raspberry_Pi/ (giới hạn 3,3 V), https://wiki.seeedstudio.com/Grove_System/; bản nội bộ `docs/ds_linhkien/grove_base_hat.pdf`. Thư viện: https://github.com/Seeed-Studio/grove.py.git.
12. SparkFun. *MCP4725 Digital-to-Analog Converter Hookup Guide*. https://learn.sparkfun.com/tutorials/mcp4725-digital-to-analog-converter-hookup-guide/board-overview-.
13. Electrokit. *MCP4725 1ch 12-bit DAC I2C* (kích thước module 15,24 × 15,24 mm). https://www.electrokit.com/en/mcp4725-1ch-12-bit-dac-i2c.
14. srituhobby. *CJMCU-101 OPT101 analog light sensor with Arduino*. https://srituhobby.com/cjmcu-101-opt101-analog-light-sensor-with-arduino/.

## B. Thiết kế và chế tạo PCB

15. KiCad. *KiCad Library License*. https://www.kicad.org/libraries/license/.
16. JLCPCB. *PCB panelization*. https://jlcpcb.com/help/article/pcb-panelization.
17. NextPCB. *PCB panelization design guide: V-score, tab routing*. https://www.nextpcb.com/blog/pcb-panelization-design-guide-v-score-tab-routing.
18. DIY Hideout (video về panel V-cut). https://www.youtube.com/watch?v=ph2jV5HMxfQ.
19. IPC-SM-782A, Amendment 1 và 2 (tham chiếu footprint 0805). https://www.pcb-3d.com/wordpress/wp-content/uploads/ipc-sm-782a_amendment_1_and_2.pdf.

## C. Mô hình hình dạng sóng PPG và dữ liệu

Các mục R1–R12 theo `docs/morphology-audit/research-evidence.md`.

20. (R1) Allen J, Murray A. (2003). *Age-related changes in the characteristics of the photoplethysmographic pulse shape at various body sites*. Physiological Measurement 24(2):297–307. https://doi.org/10.1088/0967-3334/24/2/306.
21. (R2) Tang Q, Chen Z, Ward R, Elgendi M. (2020). *Synthetic photoplethysmogram generation using two Gaussian functions*. Scientific Reports 10:13883. https://www.nature.com/articles/s41598-020-69076-x.
22. (R3) Tang Q, Chen Z, Allen J, Alian A, Menon C, Ward R, Elgendi M. (2020). *PPGSynth: An Innovative Toolbox for Synthesizing Regular and Irregular Photoplethysmography Waveforms*. Frontiers in Medicine 7:597774. https://www.frontiersin.org/journals/medicine/articles/10.3389/fmed.2020.597774/full. Mã: https://github.com/Elgendi/PPG-Synthesis.
23. (R4) Ho MY, Pham HM, Saeed A, Ma D. (2025). *WF-PPG: A Wrist-finger Dual-Channel Dataset for Studying the Impact of Contact Pressure on PPG Morphology*. Scientific Data 12:200. https://www.nature.com/articles/s41597-025-04453-7.
24. (R5) Goda MÁ, Charlton PH, Behar JA. (2024). *pyPPG: a Python toolbox for comprehensive photoplethysmography signal analysis*. Physiological Measurement 45(4):045001. https://doi.org/10.1088/1361-6579/ad33a2. Tài liệu: https://pyppg.readthedocs.io/en/latest/.
25. (R6) Lapitan DG, Rogatkin DA, Molchanova EA, Tarasov AP. (2024). *Estimation of phase distortions of the photoplethysmographic signal in digital IIR filtering*. Scientific Reports 14:6546. https://www.nature.com/articles/s41598-024-57297-3.
26. (R7) Pal R, Rudas Á, Kim S, Chiang JN, Barney A, Cannesson M. (2024). *An algorithm to detect dicrotic notch in arterial blood pressure and photoplethysmography waveforms using the iterative envelope mean method*. Computer Methods and Programs in Biomedicine 254:108283. https://doi.org/10.1016/j.cmpb.2024.108283.
27. (R8) Papini G, Fonseca P, Aubert X, Overeem S, Bergmans JWM, Vullings R. (2017). *Photoplethysmography beat detection and pulse morphology quality assessment for signal reliability estimation*. IEEE EMBC, pp. 117–120. https://doi.org/10.1109/EMBC.2017.8036776.
28. (R9) Forster P, Laska B, Goubran R, Wallace B, Liu P, Sveistrup H. (2025). *Method for the Measurement of the Dicrotic Notch in the Photoplethysmography Signal*. IEEE I2MTC, 19–22/5/2025. https://ieeexplore.ieee.org/document/11079209/.
29. (R10) Pimentel M, Johnson A, Charlton P, Clifton D. (2018). *BIDMC PPG and Respiration Dataset*, v1.0.0. https://physionet.org/content/bidmc/1.0.0/ (DOI 10.13026/C2208R).
30. (R11) Zahedi E, Chellappan K, Mohd Ali MA, Singh H. (2007). *Analysis of the effect of ageing on rising edge characteristics of the photoplethysmogram using a modified Windkessel model*. Cardiovascular Engineering 7(4):172–181. https://doi.org/10.1007/s10558-007-9037-5.
31. (R12) Pham HM, Ho MY, Zhang Y, Spathis D, Saeed A, Ma D. (2025). *Reliable wrist PPG monitoring by mitigating poor skin sensor contact*. Scientific Reports. https://www.nature.com/articles/s41598-025-31883-5. Mã: https://github.com/manhph2211/CP-PPG.

## D. Mạng sinh và học máy

32. Gulrajani I và cộng sự (2017). *Improved Training of Wasserstein GANs*. https://arxiv.org/abs/1704.00028.
33. Perez E và cộng sự. *FiLM: Visual Reasoning with a General Conditioning Layer*. https://arxiv.org/abs/1709.07871.
34. Bai S và cộng sự. *An Empirical Evaluation of Generic Convolutional and Recurrent Networks for Sequence Modeling*. https://arxiv.org/abs/1803.01271.
35. Miyato T, Koyama M. *cGANs with Projection Discriminator*. ICLR 2018. https://openreview.net/forum?id=ByS1VpgRZ.
36. *PulseGAN*. https://arxiv.org/abs/2006.02699.
37. *CardioGAN*. https://arxiv.org/abs/2010.00104.
38. Ding C và cộng sự. *Log-Spectral Matching GAN (LSM-GAN)*. arXiv:2108.05272v2. https://arxiv.org/abs/2108.05272v2. Mã tác giả (commit d2d01fe): https://github.com/chengding0713/Log-Spectral-matching-GAN.
39. Yoon J, Jarrett D, van der Schaar M. *Time-series Generative Adversarial Networks (TimeGAN)*. NeurIPS 2019. https://papers.neurips.cc/paper_files/paper/2019/hash/c9efe5f26cd17ba6216bbe2a7d26d490-Abstract.html. Mã: https://github.com/jsyoon0823/TimeGAN.
40. *PPG-CAGAN* (trang nhà xuất bản). https://www.sciencedirect.com/science/article/pii/S1746809426005185.
41. Issue PyTorch về lỗi ARMv8.1 LSE trên Raspberry Pi (SIGILL). https://github.com/pytorch/pytorch/issues/174344.
42. Notebook Kaggle của dự án: [Conditional Architecture Sweep](https://www.kaggle.com/code/charlesday2612/ppg-conditional-architecture-sweep), [cWGAN-GP BIDMC Pilot](https://www.kaggle.com/code/charlesday2612/ppg-cwgan-gp-bidmc-pilot), [LSM-GAN BIDMC Comparison](https://www.kaggle.com/code/charlesday2612/ppg-lsm-gan-bidmc-comparison). Dữ liệu huấn luyện: https://physionet.org/files/bidmc/1.0.0/bidmc_data.mat.

## E. Bài báo và tài liệu lưu trong `docs/`

43. Elgendi M. (2012). *On the Analysis of Fingertip Photoplethysmogram Signals*. Current Cardiology Reviews 8:14–25. `docs/005-Mohamed_new.pdf`.
44. *Opening the envelope: Efficient envelope-based PPG denoising algorithm*. Biomedical Signal Processing and Control 88 (2024) 105693. `docs/1-s2.0-S1746809423011266-main.pdf`.
45. *A Self-Supervised Algorithm for Denoising Photoplethysmography Signals for Heart Rate Estimation From Wearables*. Harvard Data Science Review, Issue 6.3, Summer 2024. `docs/1vmoqb4wv271y4m2ulnt4i5vwj7so8by.pdf`.
46. *Breathing Rate Estimation From the Electrocardiogram and Photoplethysmogram: A Review*. IEEE Reviews in Biomedical Engineering, vol. 11, 2018. `docs/2018 Breathing rate estimation from the ECG and PPG A review.pdf`.
47. *An Embedded Auto-Calibrated Offset Current Compensation Technique for PPG/fNIRS System*. IEEE Embedded Systems Letters (arXiv:2307.07414v1). `docs/2307.07414v1.pdf`.
48. *14.85 µW Analog Front-End for Photoplethysmography Acquisition with 142-dBΩ Gain and 64.2-pArms Noise*. Sensors. `docs/b7862f6475958be20fe047754abd818da9c0.pdf`.
49. Bugtai N, Munsayac FE III, Alonzo L, Saflor CS. *Simulation and Real-Time Testing of Photoplethysmogram Signal-Based Biometric Recognition System*. Engineering Proceedings 128. `docs/engproc-128-00047.pdf`.
50. Charlton P và cộng sự (2021). *Photoplethysmography Signal Processing and Synthesis* (chương sách). `docs/PPG_sig_proc_Chapter_20210612.pdf`; bản gốc: https://peterhcharlton.github.io/publication/ppg_sig_proc_chapter/PPG_sig_proc_Chapter_20210612.pdf.
51. Benkert A, Bludau J, Boborzi L, Prueckner S, Schniepp R. *Impact of Helicopter Vibrations on In-Ear PPG Monitoring for Vital Signs—Mountain Rescue Technology Study (MoReTech)*. Sensors, 2026. `docs/sensors-26-00324-v2.pdf`.
52. *Respiratory Quality Index Design and Validation for ECG and PPG Derived Respiratory Data* (báo cáo chuyển trạng thái, tác giả không rõ trong file). `docs/transfer_db.pdf`.
53. `docs/CVv391S182016022.pdf` (bản quét, không đọc được tiêu đề; cần mở tay để ghi nguồn).

## F. Thiết bị tham chiếu

54. WhaleTeq. *AECG100 ECG, PPG and PWTT Multifunction Tester: datasheet* (v2.1, 2024-04-17) và *User Manual* (v1.9.0, 2025-12-08). `docs/whale_device/whale_device.pdf`, `docs/whale_device/user_manual.pdf`, `docs/whale_device/version_sdk_app_whale.pdf`.

## G. Tổng quan văn bản `docs/effect_HR_SpO2_RR_to_PPG.docx`

Danh sách "Nguồn trích dẫn" của bản tổng quan này (đã bỏ trùng; tiêu đề theo file). Nên kiểm tra lại từng nguồn trước khi dùng làm tài liệu chính.

55. Photoplethysmogram Analysis and Applications: An Integrative Review. Frontiers in Physiology. https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2021.808451/full
56. Advancements in Remote Photoplethysmography. MDPI Electronics. https://www.mdpi.com/2079-9292/14/5/1015
57. Sources of Inaccuracy in Photoplethysmography for Continuous Cardiovascular Monitoring. https://pmc.ncbi.nlm.nih.gov/articles/PMC8073123/
58. Current progress of photoplethysmography and SPO2 for health monitoring. https://pmc.ncbi.nlm.nih.gov/articles/PMC6431353/
59. Analysis of the Effect of Skin Pigmentation and Oxygen Saturation on Monte Carlo-Simulated Reflectance Photoplethysmography Signals. MDPI Sensors. https://www.mdpi.com/1424-8220/25/2/372
60. Real-Time Subject-Specific Predictive Modeling of PPG Signals for Artifact-Resilient SpO2 Estimation Under Hypoxia. MDPI Sensors. https://www.mdpi.com/1424-8220/25/23/7176 (bản PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC12694438/)
61. Remote photoplethysmography for health assessment: a review informed by IntelliProve technology. https://pmc.ncbi.nlm.nih.gov/articles/PMC12812591/
62. Clinical validation of comprehensive time- and frequency-domain photoplethysmography features from a single-sensor system for non-invasive assessment of vascular load and systolic blood pressure. https://pmc.ncbi.nlm.nih.gov/articles/PMC12605234/
63. A Dataset and Toolkit for Multiparameter Cardiovascular Physiology Sensing on Rings. arXiv. https://arxiv.org/html/2505.04172v2
64. Quality Assessment and Morphological Analysis of Photoplethysmography in Daily Life. https://pmc.ncbi.nlm.nih.gov/articles/PMC9300860/
65. Analysis on Four Derivative Waveforms of Photoplethysmogram (PPG) for Fiducial Point Detection. https://pmc.ncbi.nlm.nih.gov/articles/PMC9280335/
66. Assessing hemodynamics from the photoplethysmogram to gain insights into vascular age: a review from VascAgeNet. Am J Physiol Heart. https://journals.physiology.org/doi/10.1152/ajpheart.00392.2021
67. Effect of posture on photoplethysmography signals from the posterior tibial artery in adults with and without type 2 diabetes. https://pmc.ncbi.nlm.nih.gov/articles/PMC12701066/
68. Characterising the Photoplethysmography Pulse Waveform for Use in Human Neuroscience: The Hybrid Excess and Decay (HED) Model. bioRxiv. https://www.biorxiv.org/content/10.1101/2021.08.19.456935v1.full-text
69. Quantitative Comparison of Photoplethysmographic Waveform Characteristics: Effect of Measurement Site. Frontiers in Physiology. https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2019.00198/full
70. Effect of increasing heart rate on finger photoplethysmography. https://pmc.ncbi.nlm.nih.gov/articles/PMC6261569/
71. Photoplethysmography-Based Respiratory Rate Estimation Algorithm for Health Monitoring Applications. https://pmc.ncbi.nlm.nih.gov/articles/PMC9056464/
72. Pulse rate variability is not the same as heart rate variability: findings from a large, diverse clinical population study. Frontiers in Physiology. https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2025.1630032/full
73. Breathing Rate Estimation from Head-Worn Photoplethysmography Sensor Data Using Machine Learning. MDPI Sensors. https://www.mdpi.com/1424-8220/22/6/2079
74. Determining respiratory rate from photoplethysmogram and electrocardiogram signals using respiratory quality indices and neural networks. https://pmc.ncbi.nlm.nih.gov/articles/PMC8031461/ (PDF: https://researchonline.jcu.edu.au/67705/1/journal.pone.0249843.pdf)
75. Extracting Instantaneous Respiratory Rate From Multiple Photoplethysmogram Respiratory-Induced Variations. Frontiers in Physiology. https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2018.00948/full
76. Toward Accurate Extraction of Respiratory Frequency From the Photoplethysmogram: Effect of Measurement Site. Frontiers in Physiology. https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2019.00732/full
77. Comparison of different modulations of photoplethysmography in extracting respiratory rate: from a physiological perspective. PubMed. https://pubmed.ncbi.nlm.nih.gov/32731213/
78. Photoplethysmogram Analysis and Applications: An Integrative Review (bản PMC). https://pmc.ncbi.nlm.nih.gov/articles/PMC8920970/
79. Personalized Modeling of Blood Pressure with Photoplethysmography: an Error-Feedback Incremental Support Vector Regression Model. IEEE. https://ieeexplore.ieee.org/iel7/6488907/6702522/10168193.pdf
80. Effect of Oxygen Concentration Reduction on Photoplethysmographic Waveform Characteristics. https://ieeexplore.ieee.org/document/10081762/ và https://cinc.org/2022/Program/accepted/120_Preprint.pdf (Computing in Cardiology 2022)
81. Morphological features of the photoplethysmographic signal: a new approach to characterize the microcirculatory response to photobiomodulation. https://pmc.ncbi.nlm.nih.gov/articles/PMC10561251/
82. Summit Vitals: Multi-Camera and Multi-Signal Biosensing at High Altitudes. arXiv. https://arxiv.org/html/2409.19223v1. Mã: https://github.com/thuhci/SUMS. Liên quan: https://github.com/McJackTang/FusionVitals.
83. Continuous Patient-Independent Estimation of Respiratory Rate and Blood Pressure Using Robust Spectro-Temporal Features Derived From Photoplethysmogram Only. https://pmc.ncbi.nlm.nih.gov/articles/PMC11342923/
84. Evaluation of Photoplethysmography-Based Monitoring of Respiration Rate During High-Intensity Interval Training: Implications for Healthcare Monitoring. MDPI Biosensors. https://www.mdpi.com/2079-6374/14/12/631
85. Influence of Photoplethysmogram Signal Quality on Pulse Arrival Time during Polysomnography. MDPI Sensors. https://www.mdpi.com/1424-8220/23/4/2220
86. Heart rate variability analysis in pediatric obstructive sleep apnea: automated signal processing (luận án, UVaDOC). https://uvadoc.uva.es/bitstream/handle/10324/66849/TESIS-2278-240320.pdf?sequence=1
87. Diagnostic Features and Potential Applications of PPG Signal in Healthcare: A Systematic Review. https://pmc.ncbi.nlm.nih.gov/articles/PMC8950880/
88. Automated Lightweight Model for Asthma Detection Using Respiratory and Cough Sound Signals. MDPI Diagnostics. https://www.mdpi.com/2075-4418/15/9/1155
89. A Review of Deep Learning Methods for Photoplethysmography Data. arXiv. https://arxiv.org/html/2401.12783v2
90. Reliability of pulse photoplethysmography sensors: Coverage using different setups and body locations. Frontiers in Electronics. https://www.frontiersin.org/journals/electronics/articles/10.3389/felec.2022.906324/full
91. The Effect of Device-Controlled Breathing on the Pulse Arrival Time and the Heart Rate Asymmetry Parameters in Healthy Volunteers. MDPI Applied Sciences. https://www.mdpi.com/2076-3417/13/9/5642
92. Emotion Recognition from rPPG via Physiologically-Inspired Temporal Encoding and Attention-Based Curriculum Learning. Preprints.org. https://www.preprints.org/manuscript/202505.1435
93. Innovative measurement of routine physiological variables (heart rate, respiratory rate and oxygen saturation) using a remote photoplethysmography imaging system: a prospective comparative trial protocol. BMJ Open 11(8). https://bmjopen.bmj.com/content/11/8/e047896
94. PPG as a Bridge: Cross-Device Authentication for Smart Wearables with Photoplethysmography. arXiv. https://arxiv.org/html/2602.08972v1
95. Accuracy of heart rate, pulse oxygen saturation, and blood pressure using a non-contact photoplethysmography-based mobile application: A potential tool for wellness monitoring. https://pmc.ncbi.nlm.nih.gov/articles/PMC12227916/
96. Feasibility of a Noncontact Photoplethysmography–Based Mobile App for Noninvasive Hemoglobin Monitoring: Exploratory Observational Study. JMIR Formative Research. https://formative.jmir.org/2026/1/e78820
97. Pulse-PPG: An Open-Source Field-Trained PPG Foundation Model for Wearable Applications Across Lab and Field Settings. arXiv. https://arxiv.org/html/2502.01108v2
98. Không phải bài báo bình duyệt, nên cân nhắc bỏ: [Photoplethysmogram, Wikipedia](https://en.wikipedia.org/wiki/Photoplethysmogram); [Emergent Mind, Pulse-PPG](https://www.emergentmind.com/topics/pulse-ppg-foundation-model); các trang ResearchGate (hình/bản PDF trùng với mục đã có ở trên); [PulseVision, Reddit](https://www.reddit.com/r/BiomedicalDataScience/comments/1w7nj1e/pulsevision_synthetic_ppg_waveform_visualizer/).

## H. Môi trường phần mềm (hệ điều hành Raspberry Pi)

99. Ubuntu. *Raspberry Pi installation matrix*. https://documentation.ubuntu.com/hardware-support/boards/how-to/ubuntu_supported/raspberry-pi/.
100. Ubuntu. *Ubuntu 26.04 LTS: summary for LTS users*. https://documentation.ubuntu.com/release-notes/26.04/summary-for-lts-users/.

## I. Tài liệu nội bộ của dự án (tự viết, không phải nguồn bên ngoài)

- `docs/architecture/PHASE_1_REFERENCE_AUDIT_AND_MASTER_DESIGN.md`: kiểm toán tham chiếu so với WhaleTeq AECG100 và thiết kế tổng thể.
- `docs/morphology-audit/research-evidence.md`, `docs/ppg_morphology.md`: bằng chứng hình dạng sóng PPG.
- `docs/ppg_*_report_*.md`: báo cáo GAN, LSM-GAN, Gaussian fit, neural preview, round 2, touch sequence.
- `docs/opt101-a0-diagnostic-2026-10-01.md`, `docs/rx-monitor-2026-10-01.md`: chẩn đoán đường nhận OPT101.
- `hardware/led_ir_driver/` (README, ELECTRICAL_AUDIT, DESIGN_BRIEF, COMPONENT_RATIONALE, PIN_MAP, CONNECTIVITY_REVIEW), `hardware/opt101_receiver_kicad/opt101_receiver/README.md`, `hardware/ppg_panel/` (ELECTRICAL_REVIEW, LAYOUT_REVIEW): thiết kế và kiểm tra phần cứng. Các kết quả này là kiểm tra trên file CAD, chưa phải đo trên mạch thật.
