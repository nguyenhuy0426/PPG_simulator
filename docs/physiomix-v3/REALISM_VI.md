## Giống thật đến đâu, trên từng tập dữ liệu

| Tập dữ liệu (người chưa dùng để train) | Nguồn | Độ giống (fidelity) | Độ phủ (coverage) | Không phân biệt được (C2ST) |
|---|---|---|---|---|
| GXU ngón tay (khỏe) · 44 người | Dữ liệu thật của người khác | 98% | 99% | 94% (AUC 0.53) |
|  | v2_round3 | 94% | 69% | 5% (AUC 0.97) |
|  | round6 | 93% | 70% | 7% (AUC 0.97) |
|  | round7 | 96% | 70% | 21% (AUC 0.89) |
|  | gaussian_shaper | 1% | 1% | 0% (AUC 1.00) |
| MIMIC PERform Large (ICU) · 191 người | Dữ liệu thật của người khác | 98% | 95% | 97% (AUC 0.48) |
|  | v2_round3 | 95% | 65% | 37% (AUC 0.82) |
|  | round6 | 99% | 64% | 39% (AUC 0.80) |
|  | round7 | 98% | 73% | 57% (AUC 0.71) |
|  | gaussian_shaper | 70% | 0% | 0% (AUC 1.00) |
| BIDMC (ICU) · 14 người | Dữ liệu thật của người khác | 51% | 88% | 96% (AUC 0.48) |
|  | v2_round3 | 53% | 64% | 44% (AUC 0.78) |
|  | round6 | 55% | 51% | 36% (AUC 0.82) |
|  | round7 | 61% | 71% | 57% (AUC 0.72) |
|  | gaussian_shaper | 0% | 60% | 0% (AUC 1.00) |
| MIMIC PERform AF · 4 người | Dữ liệu thật của người khác | 55% | 83% | 56% (AUC 0.28) |
|  | v2_round3 | 62% | 34% | 5% (AUC 0.97) |
|  | round6 | 50% | 66% | 12% (AUC 0.94) |
|  | round7 | 58% | 68% | 18% (AUC 0.91) |
|  | gaussian_shaper | 1% | 0% | 0% (AUC 1.00) |
| MIMIC PERform không AF · 2 người | Dữ liệu thật của người khác | 11% | 18% | 59% (AUC 0.70) |
|  | v2_round3 | 12% | 72% | 81% (AUC 0.48) |
|  | round6 | 18% | 86% | 87% (AUC 0.48) |
|  | round7 | 14% | 94% | 76% (AUC 0.38) |
|  | gaussian_shaper | 0% | 0% | 0% (AUC 1.00) |
| Cổ tay khi vận động · 4 người | Dữ liệu thật của người khác | 77% | 54% | 92% (AUC 0.49) |
|  | v2_round3 | 87% | 45% | 39% (AUC 0.81) |
|  | round6 | 89% | 40% | 40% (AUC 0.80) |
|  | round7 | 82% | 18% | 42% (AUC 0.79) |
|  | gaussian_shaper | 0% | 0% | 0% (AUC 1.00) |

## Có làm theo lệnh trạng thái không

| Trạng thái yêu cầu | Dữ liệu thật: nhận đúng | v2_round3: nhận đúng · P(vận động) | round6: nhận đúng · P(vận động) | round7: nhận đúng · P(vận động) | gaussian_shaper: nhận đúng · P(vận động) |
|---|---|---|---|---|---|
| BIDMC | 23% · 0.00 | 48% · 0.02 | 41% · 0.01 | 35% · 0.00 | 0% · 0.00 |
| AF | 89% · 0.00 | 41% · 0.08 | 60% · 0.06 | 53% · 0.00 | 0% · 0.00 |
| không AF | 0% · 0.00 | 49% · 0.03 | 47% · 0.03 | 49% · 0.00 | 20% · 0.02 |
| PERform Large | 36% · 0.04 | 35% · 0.05 | 26% · 0.03 | 35% · 0.00 | 36% · 0.00 |
| GXU nghỉ | 84% · 0.00 | 83% · 0.00 | 73% · 0.01 | 73% · 0.00 | 38% · 0.00 |
| GXU sau gắng sức | 36% · 0.00 | 18% · 0.02 | 38% · 0.01 | 46% · 0.00 | 37% · 0.00 |
| Cổ tay vận động | 86% · 0.74 | 91% · 0.88 | 91% · 0.88 | 100% · 0.96 | 8% · 0.07 |
| **Trung bình (đoán mò = 14%)** | 51% | 52% | 54% | 56% | 20% |
| **Cùng nhiễu, đổi lệnh: tỉ lệ theo lệnh** | — | 48% | 53% | 55% | 17% |

## Thống kê sinh lý theo trạng thái

| Trạng thái | Nguồn | HR trung vị | CV khoảng nhịp | Đo được nhịp | Độ tuần hoàn (ACF) |
|---|---|---|---|---|---|
| BIDMC | Thật · người chưa dùng | 91 | 0.029 | 100% | 0.91 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 87 | 0.124 | 99% | 0.84 |
|  | v2_round3 | 85 | 0.088 | 97% | 0.69 |
|  | round6 | 87 | 0.100 | 97% | 0.70 |
|  | round7 | 86 | 0.094 | 95% | 0.70 |
|  | gaussian_shaper | 87 | 0.001 | 100% | 0.97 |
| AF | Thật · người chưa dùng | 94 | 0.224 | 89% | 0.26 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 87 | 0.235 | 76% | 0.24 |
|  | v2_round3 | 86 | 0.184 | 87% | 0.35 |
|  | round6 | 90 | 0.200 | 91% | 0.36 |
|  | round7 | 87 | 0.195 | 94% | 0.34 |
|  | gaussian_shaper | 88 | 0.000 | 100% | 0.97 |
| không AF | Thật · người chưa dùng | 93 | 0.030 | 100% | 0.92 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 71 | 0.030 | 97% | 0.91 |
|  | v2_round3 | 70 | 0.027 | 96% | 0.93 |
|  | round6 | 70 | 0.027 | 99% | 0.92 |
|  | round7 | 71 | 0.026 | 98% | 0.92 |
|  | gaussian_shaper | 71 | 0.000 | 100% | 0.97 |
| PERform Large | Thật · người chưa dùng | 83 | 0.052 | 98% | 0.87 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 80 | 0.066 | 95% | 0.82 |
|  | v2_round3 | 78 | 0.046 | 95% | 0.80 |
|  | round6 | 80 | 0.045 | 95% | 0.79 |
|  | round7 | 80 | 0.044 | 95% | 0.77 |
|  | gaussian_shaper | 82 | 0.000 | 100% | 0.97 |
| GXU nghỉ | Thật · người chưa dùng | 79 | 0.065 | 100% | 0.85 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 80 | 0.059 | 100% | 0.84 |
|  | v2_round3 | 80 | 0.063 | 100% | 0.87 |
|  | round6 | 80 | 0.073 | 100% | 0.89 |
|  | round7 | 80 | 0.069 | 99% | 0.88 |
|  | gaussian_shaper | 79 | 0.000 | 100% | 0.97 |
| GXU sau gắng sức | Thật · người chưa dùng | 86 | 0.054 | 99% | 0.86 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 87 | 0.055 | 100% | 0.85 |
|  | v2_round3 | 87 | 0.057 | 100% | 0.87 |
|  | round6 | 87 | 0.047 | 99% | 0.89 |
|  | round7 | 87 | 0.045 | 100% | 0.88 |
|  | gaussian_shaper | 87 | 0.001 | 100% | 0.97 |
| Cổ tay vận động | Thật · người chưa dùng | 90 | 0.250 | 77% | 0.52 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 73 | 0.204 | 79% | 0.62 |
|  | v2_round3 | 101 | 0.230 | 56% | 0.26 |
|  | round6 | 99 | 0.205 | 57% | 0.23 |
|  | round7 | 96 | 0.237 | 55% | 0.27 |
|  | gaussian_shaper | 102 | 0.001 | 100% | 0.97 |

![Realism](realism_by_dataset.png)
