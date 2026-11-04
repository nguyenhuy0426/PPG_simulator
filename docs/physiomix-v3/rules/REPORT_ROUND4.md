# PhysioMix round 4: learning rate thấp hơn, train lâu hơn, sửa trôi nhịp và nhịp AF

Chọn bằng validation: **L3_rel_beat_lr**; vượt round-3 v2 và đưa vào app: **False** (chênh S_arm 0.008, SD gộp 0.028).

| Arm | S_arm (↓) | S_real | C (HR) | C2ST đạo hàm | MAE HR ngoài | CV đo ở σ=0.2 | Q gxu_finger | Q perform_large | Q bidmc | Q perform_cohort | Q wrist | GXU test Q |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L1_v2_lr | 0.637 ± 0.026 | 0.385 ± 0.014 | 0.078 ± 0.016 | 0.925 ± 0.014 | 1.2 ± 0.7 | 0.157 ± 0.007 | 0.254 ± 0.012 | 0.244 ± 0.021 | 0.693 ± 0.047 | 0.418 ± 0.039 | 0.602 ± 0.112 | 0.305 ± 0.087 |
| L2_rel_lr | 0.652 ± 0.030 | 0.408 ± 0.041 | 0.045 ± 0.034 | 0.944 ± 0.029 | 0.3 ± 0.0 | 0.161 ± 0.006 | 0.224 ± 0.055 | 0.263 ± 0.030 | 0.740 ± 0.075 | 0.459 ± 0.018 | 0.711 ± 0.153 | 0.223 ± 0.011 |
| L3_rel_beat_lr | 0.588 ± 0.029 | 0.367 ± 0.016 | 0.035 ± 0.014 | 0.906 ± 0.039 | 0.3 ± 0.2 | 0.186 ± 0.006 | 0.213 ± 0.027 | 0.239 ± 0.007 | 0.616 ± 0.023 | 0.373 ± 0.036 | 0.680 ± 0.050 | 0.228 ± 0.033 |
| L4_rel_beat_dom_lr | 0.606 ± 0.020 | 0.378 ± 0.004 | 0.027 ± 0.006 | 0.928 ± 0.035 | 0.3 ± 0.1 | 0.187 ± 0.004 | 0.216 ± 0.019 | 0.229 ± 0.028 | 0.718 ± 0.080 | 0.426 ± 0.032 | 0.666 ± 0.114 | 0.211 ± 0.057 |

Round-3 physiomix_v2: S_arm 0.596 ± 0.026, S_real 0.366 ± 0.023.
GXU test đã mở một lần ở round 3: ở đây chỉ báo cáo, không dùng để chọn.

![Control](control_and_fresh_test.png)
![Waveforms](waveforms_gxu.png)
