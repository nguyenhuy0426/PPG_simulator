# IR bị xén / trôi: đo trực tiếp trên Pi 4, 14/11/2026

Đo trên Pi 4 (Wi-Fi `ppg-rpi4`), I²C 100 kHz, app dừng, chỉ một client trên bus.
Script và dữ liệu thô nằm trong thư mục này. Không có DMM/oscilloscope:
điện áp ADC là số do firmware HAT báo (thanh ghi 0x20+ch), không phải phép đo chuẩn độc lập.

## 1. Đường ADC không gây xén

`probe_txrx.py` quét từng DAC 0–3000 mV và đọc A0/A4 bằng ba cách
(`write_byte`+`read_word_data`, block 3 byte, đọc trơn sau STOP), ở cả hai thanh ghi.

| Thanh ghi | Mẫu sai / tổng (mỗi cách đọc) |
|---|---:|
| Điện áp 0x20+ch | **0 / 1488** |
| Raw 0x10+ch | 349–386 / 1488 (trượt bit: `[lo, hi>>1]`, vd 3156 → 1620) |

Bộ lọc "byte thứ ba ≠ 0xFF" của codex loại được hết frame trượt nhưng bỏ ~50 % frame
nên phải đọc lại tới 16 lần. Bản main đọc thanh ghi điện áp một lần: giữ nguyên.
Không thấy tràn số, lệch bit hay lỗi bộ nhớ ở đường điện áp. Giao diện tự co giãn trục,
không có clamp 1.4 V.

## 2. Mapping và mức DAC

- DAC 0x60 chỉ làm sáng làn A0, 0x61 chỉ làm sáng A4, không xuyên kênh
  (RED bật/tắt 1500 mV: A4 thay đổi 538 → 543 mV).
- Đọc lại thanh ghi MCP4725 (`i2c_rdwr` 5 byte) khớp đúng mã đã ghi ở mọi bước.
  Đây là kiểm tra số; VOUT analog chưa đo.
- Người dùng xác nhận IR = A4 (11–12/11) → IR = 0x61/A4, RED = 0x60/A0.

## 3. Nguyên nhân IR xén ở ~1.4 V và trôi trong Classic

Quét xung 40 ms (`probe2.py`, `optical-calibration-*.json`):

- IR (0x61→A4) dốc ~5 mV RX / mV DAC, chạm trần ~2.5 V ở **~550–600 mV DAC**.
  Trần RED (A0) cũng ~2.5 V.
- Giữ IR **trên knee**: số đọc **sập theo thời gian**. 1500 mV: 1120 → 665 mV sau 20 s.
  600 mV: 1719 → 881 mV (−49 %). Quét chậm cho thấy RX còn *giảm* khi DAC tăng
  quá knee (797 mV ở 600 → 665 mV ở 3000).
- Giữ IR **dưới knee** (300 mV): 768 → 771 mV (+0.3 %).
- Sau một lần quá tải, độ nhạy IR còn thấp trong nhiều giây tới vài phút
  (300 mV cho 768 mV lúc nghỉ, 538 mV ngay sau quá tải; lượt quét đầu ngày có
  trần 2.0 V, lượt sau khi nghỉ 2.51 V).

Mô phỏng TX trên host với cấu hình Pi: lệnh IR ổn định suốt 60 s, giống hệt RED.
Phần mềm phát không trôi.

**Kết luận:** sau khi kéo carrier sát OPT101, IR quá sáng. Trang Calib (0–1000 mV
trên cả hai LED) và Classic với DC IR 1500 mV (cấu hình trên Pi) đẩy IR quá knee
→ đỉnh bị xén ở mức thay đổi theo lịch sử (0.85 / 1.29 / 1.4 V ở các lượt)
rồi nền trôi và biên độ giảm dần. RED ở cùng mức DAC vẫn còn nằm trong vùng tuyến tính.

Chưa xác định được linh kiện cụ thể gây "sập khi quá tải có nhớ": có thể là OPT101
quá tải (fold-back), hoặc driver/LED IR. Cần đo V_sense IR (R4) và VS của OPT101
ở 300 / 600 / 1500 mV DAC để tách.

## 4. Lỗi phần mềm đã sửa

- `SignalEngine.start_simulation` bắt đầu nội suy từ 2048 (1.64 V): tick đầu ramp
  2048 → mức thật trên **cả hai** LED, đẩy IR quá tải ngay lúc Start. Nay tick đầu
  bắt đầu từ chính mẫu của nó (`tests/test_engine_startup.py`, fail trên code cũ).
- Calib dùng một biên độ cho cả hai LED → tách biên độ IR / RED.
- Mapping IR/RED đọc từ `config.py`, không còn hardcode A0/A4 trong UI/logger.
- Xóa hằng số giao diện pygame cũ trong `config.py` và `scripts/sine_dac_bringup.py`
  (khi dừng để DAC ở 2048 = LED sáng nửa mức).

## 5. Calib và kiểm chứng

`scripts/calibrate_optical.py --apply` (dừng quét sau 3 bước chạm trần):

| Kênh | Cửa sổ DAC | DC / AC đã lưu | Ghi chú |
|---|---|---|---|
| IR | 200–350 mV | 238 / 65 mV | hold 400 mV sập −36 % ở lượt này → hạ 350 |
| RED | 400–1450 mV | 882 → **1150** / 75 mV | nâng tay, xem dưới |

Classic không giao diện, ADC/DAC thật (`classic_check.py`, `classic-check.json.gz`):

- IR (DC 238): nền 583 → 573 mV trong 90 s, xung 231–241 mV đều. Lượt hai giữ
  ~710 mV trong 7 s rồi **tụt bậc** còn ~555 mV, sau đó đứng yên. 0 lỗi đọc, ~100 Hz/kênh.
- RED: ở DC 882 có lúc tụt về ~87 mV (LED RED tắt chập chờn). Ở DC 1150 không còn
  tụt (min ≥ 853 mV), nền 1089–1137 mV, xung 86–160 mV.

## Còn mở (phần cứng)

- Ngưỡng bật của RED đổi giữa các lượt: lúc tuyến tính từ 50 mV, lúc chết
  tới 950 mV rồi bật vọt lên ~950 mV RX. Hold RED trôi ±6–15 % ở một số lượt.
- IR có bước nhảy đột ngột (−19 %) dù lệnh DAC không đổi.
- Hành vi dạng bậc / chập chờn hợp với tiếp xúc lỏng sau khi dời carrier, hoặc
  vòng LM358 dao động (C2/C4 đang DNP). Đo V_sense hai kênh bằng scope khi chạy
  Classic, kiểm tra đầu nối carrier. Phần mềm không sửa được điều này.
