## Giống thật đến đâu, trên từng tập dữ liệu

| Tập dữ liệu (người chưa dùng để train) | Nguồn | Độ giống (fidelity) | Độ phủ (coverage) | Không phân biệt được (C2ST) |
|---|---|---|---|---|
| GXU ngón tay (khỏe) · 44 người | Dữ liệu thật của người khác | 98% | 99% | 94% (AUC 0.53) |
|  | round7 | 96% | 70% | 21% (AUC 0.89) |
|  | round9 | 95% | 76% | 9% (AUC 0.96) |
|  | gaussian_shaper | 1% | 1% | 0% (AUC 1.00) |
| MIMIC PERform Large (ICU) · 191 người | Dữ liệu thật của người khác | 98% | 95% | 97% (AUC 0.48) |
|  | round7 | 98% | 73% | 57% (AUC 0.71) |
|  | round9 | 98% | 63% | 36% (AUC 0.82) |
|  | gaussian_shaper | 70% | 0% | 0% (AUC 1.00) |
| BIDMC (ICU) · 14 người | Dữ liệu thật của người khác | 51% | 88% | 96% (AUC 0.48) |
|  | round7 | 61% | 71% | 57% (AUC 0.72) |
|  | round9 | 49% | 67% | 45% (AUC 0.77) |
|  | gaussian_shaper | 0% | 60% | 0% (AUC 1.00) |
| MIMIC PERform AF · 4 người | Dữ liệu thật của người khác | 55% | 83% | 56% (AUC 0.28) |
|  | round7 | 58% | 68% | 18% (AUC 0.91) |
|  | round9 | 51% | 46% | 7% (AUC 0.97) |
|  | gaussian_shaper | 1% | 0% | 0% (AUC 1.00) |
| MIMIC PERform không AF · 2 người | Dữ liệu thật của người khác | 11% | 18% | 59% (AUC 0.70) |
|  | round7 | 14% | 94% | 77% (AUC 0.39) |
|  | round9 | 10% | 94% | 80% (AUC 0.40) |
|  | gaussian_shaper | 0% | 0% | 0% (AUC 1.00) |
| Cổ tay khi vận động · 4 người | Dữ liệu thật của người khác | 77% | 54% | 92% (AUC 0.49) |
|  | round7 | 82% | 18% | 42% (AUC 0.79) |
|  | round9 | 92% | 56% | 52% (AUC 0.74) |
|  | gaussian_shaper | 0% | 0% | 0% (AUC 1.00) |

## Có làm theo lệnh trạng thái không

| Trạng thái yêu cầu | Dữ liệu thật: nhận đúng | round7: nhận đúng · P(vận động) | round9: nhận đúng · P(vận động) | gaussian_shaper: nhận đúng · P(vận động) |
|---|---|---|---|---|
| BIDMC | 22% · 0.00 | 35% · 0.00 | 34% · 0.02 | 0% · 0.00 |
| AF | 88% · 0.00 | 53% · 0.00 | 65% · 0.06 | 0% · 0.00 |
| không AF | 0% · 0.00 | 49% · 0.00 | 52% · 0.03 | 20% · 0.03 |
| PERform Large | 35% · 0.04 | 34% · 0.00 | 34% · 0.06 | 36% · 0.00 |
| GXU nghỉ | 84% · 0.00 | 72% · 0.00 | 80% · 0.00 | 39% · 0.00 |
| GXU sau gắng sức | 37% · 0.00 | 47% · 0.00 | 34% · 0.03 | 36% · 0.00 |
| Cổ tay vận động | 86% · 0.74 | 100% · 0.96 | 78% · 0.73 | 8% · 0.07 |
| **Trung bình (đoán mò = 14%)** | 50% | 56% | 54% | 20% |
| **Cùng nhiễu, đổi lệnh: tỉ lệ theo lệnh** | — | 55% | 49% | 17% |

## Thống kê sinh lý theo trạng thái

| Trạng thái | Nguồn | HR trung vị | CV khoảng nhịp | Đo được nhịp | Độ tuần hoàn (ACF) |
|---|---|---|---|---|---|
| BIDMC | Thật · người chưa dùng | 91 | 0.029 | 100% | 0.91 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 87 | 0.124 | 99% | 0.84 |
|  | round7 | 86 | 0.094 | 95% | 0.70 |
|  | round9 | 86 | 0.102 | 98% | 0.67 |
|  | gaussian_shaper | 87 | 0.001 | 100% | 0.97 |
| AF | Thật · người chưa dùng | 94 | 0.224 | 89% | 0.26 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 87 | 0.235 | 76% | 0.24 |
|  | round7 | 87 | 0.195 | 94% | 0.34 |
|  | round9 | 87 | 0.200 | 87% | 0.34 |
|  | gaussian_shaper | 88 | 0.000 | 100% | 0.97 |
| không AF | Thật · người chưa dùng | 93 | 0.030 | 100% | 0.92 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 71 | 0.030 | 97% | 0.91 |
|  | round7 | 71 | 0.026 | 98% | 0.92 |
|  | round9 | 70 | 0.029 | 98% | 0.93 |
|  | gaussian_shaper | 71 | 0.000 | 100% | 0.97 |
| PERform Large | Thật · người chưa dùng | 83 | 0.052 | 98% | 0.87 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 80 | 0.066 | 95% | 0.82 |
|  | round7 | 80 | 0.044 | 95% | 0.77 |
|  | round9 | 79 | 0.051 | 94% | 0.74 |
|  | gaussian_shaper | 82 | 0.000 | 100% | 0.97 |
| GXU nghỉ | Thật · người chưa dùng | 79 | 0.065 | 100% | 0.85 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 80 | 0.059 | 100% | 0.84 |
|  | round7 | 80 | 0.069 | 99% | 0.88 |
|  | round9 | 80 | 0.075 | 99% | 0.86 |
|  | gaussian_shaper | 79 | 0.000 | 100% | 0.97 |
| GXU sau gắng sức | Thật · người chưa dùng | 86 | 0.054 | 99% | 0.86 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 87 | 0.055 | 100% | 0.85 |
|  | round7 | 87 | 0.045 | 100% | 0.88 |
|  | round9 | 87 | 0.052 | 99% | 0.87 |
|  | gaussian_shaper | 87 | 0.001 | 100% | 0.97 |
| Cổ tay vận động | Thật · người chưa dùng | 90 | 0.250 | 77% | 0.52 |
|  | Thật · đúng các cửa sổ dùng làm lệnh | 73 | 0.204 | 79% | 0.62 |
|  | round7 | 96 | 0.237 | 55% | 0.27 |
|  | round9 | 103 | 0.225 | 62% | 0.22 |
|  | gaussian_shaper | 102 | 0.001 | 100% | 0.97 |

![Realism](realism_by_dataset.png)
