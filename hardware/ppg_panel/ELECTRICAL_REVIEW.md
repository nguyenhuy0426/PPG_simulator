# Rà soát panel hai board — 06/11/2026

Chỉ giữ OPT101 và LED/IR driver. Driver dịch lên20mm trong panel, không đổi nguồn/mạch/linh kiện. Source PCB/schematic DRC/parity:0 vi phạm,0 thiếu kết nối. Kết quả panel/source hash ở reports/.

R4/R9=100Ω từ SENSE_IR/RED về GND. I_emitter=V_sense/R_sense, xấp xỉ dòng collector LED nhưng còn dòng base. Cầu chia DAC10k/10k và LM358 cho V_sense≈V_DAC/2 khi đủ headroom. C2/C4 DNP; chưa đo ổn định vòng.

OPT101 chân4–5 nối nhau, dùng hồi tiếp1MΩ nội; R1/R2=1kΩ,C3/C4=1µF lọc ngõ ra, fc danh nghĩa159Hz. Cần đo nền tối, clipping, gain/pha và xuyên kênh. RC không sửa bão hòa.

PCB driver đầu vào có J1–J7; v2.0/J8 trong generator chưa áp dụng. PCB OPT101 ghiRED/A2, appPi dùngRED/A4: đối chiếu dây/kênh. Không tự thay source trong tác vụ bỏ BPW34. Xem [hướng dẫn đo](../MEASUREMENT_GUIDE.md) cho điểm đo đã kiểm tra theoPCB.

Đây là kiểm tra CAD, không phải kết quả đo điện/quang hoặc xác nhận nhà in. Bản rà soát ba board cũ nằm trong archive.
