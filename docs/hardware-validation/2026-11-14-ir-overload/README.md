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

`scripts/calibrate_optical.py --apply` (buổi sáng; script này đã được thay bằng nút «Đo đường truyền» trong app, mục 6):

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

## 6. Chiều 14/11: 1:1 TX→RX, OPT101, driver RED/IR (`probe3.py`, ảnh trong thư mục)

**OPT101 bão hòa ở bao nhiêu V.** Datasheet TI OPT101 §6.5: V_out cao = V_S − 1.3 V (min) / V_S − 1.15 V
(typ), RL = 10 kΩ, phục hồi quá tải 50 µs. Board cấp 3.3 V từ Grove → bảo đảm ~2.0–2.15 V. Đo được
2.51–2.54 V ở cả hai kênh khi quang đủ mạnh (tải nhẹ: 1 kΩ + 1 µF + ADC). Dùng 2.0 V làm mức an toàn,
~2.5 V là trần thực tế. Phục hồi 50 µs nghĩa là "sập có nhớ" vài giây–phút **không** phải hành vi của OPT101.

**Driver IR giới hạn dòng.** Trần IR phía thu đổi theo vị trí quang (2495 → 1214 → 1026 → 896 mV trong
phiên) nhưng luôn gãy ở cùng một mức phát ~600–750 mV DAC, tức V_sense ≈ 0.3–0.37 V, I ≈ 3–3.7 mA
(R4 = 100 Ω). RED cùng LM358 vẫn tuyến tính tới ~2200 mV DAC (~11 mA). Giới hạn nằm ở phía phát IR
(Q1/R3/LED IR hoặc tiếp xúc), không phải OPT101. Có lúc IR không bám điều chế (phẳng ~573 mV, ảnh
`classic-ir-flat.png`). Cần đo V_sense IR (R4 pad 1 ↔ GND) và V_base Q1 ở 300/600/1000 mV DAC.

**Vùng chết RED.** Không tái hiện trong 7 lần bật từ trạng thái tắt (bật ngay 0 ms) và quét lên/xuống
không trễ từ. Các lần trước: tắt tới 950 mV rồi bật vọt, một lần bật trễ 2.55 s ở 300 mV mà không có lệnh
ghi mới (DAC đọc lại đúng mã), và các lần tụt về ~0 trong ~0.1 s khi đang phát. Mạch thiết kế
(I = V_DAC/200 Ω) không thể có vùng chết hàng trăm mV, nên đây là lỗi chập chờn (tiếp xúc đầu nối/carrier
RED, hoặc vòng LM358 dao động vì C2/C4 DNP). Cần đo V_sense RED (R9) bằng scope khi đang phát.

**Phần mềm 1:1.** `core/optical_map.py` đo đường truyền ngay trong app (nút «Đo đường truyền») và
nghịch đảo nó: mức đặt là mV thu. Vòng chỉnh chậm (0.5 s, giới hạn ±10 %/lần, ×0.5–2, không vượt điểm
trên của bản đồ) bù trôi quang. Kết quả trên Pi:

| Thử | Lệnh (mV thu) | Thu được | Δ |
|---|---|---|---|
| Mức cố định | IR 800, RED 1000 | 800, 999 | +0, −1 |
| Sine 1 Hz ±50 | IR 850/750, RED 1050/950 | 831/754, 1048/944 | −19, −6 |
| Classic | IR 600/30, RED 1000 | IR ~30 mV xung trên 605, RED ~22 trên 1012 | — |

**SpO₂ RX sai do phần mềm, đã sửa.** Ước lượng cũ lấy AC = RMS sau lọc: chính sóng TX của model (RED
nhọn hơn IR) cho R = 0.222 thay vì 0.441. Ước lượng mới: biên độ đỉnh–đáy từng nhịp (bỏ nền tuyến tính
trong nhịp), lưới 100 Hz. Trên sóng model: SpO₂ đặt 99/95/90/85 % → đọc 99.4/95.6/91.4/87.0 %.

**DAC 500 Hz không giữ được trên Pi khi có GUI + RX** (ring 1019/1024, mất ~44 mẫu/s, trễ ~2 s). Mặc định
Pi giờ là 200 Hz: Buffer ~30, Lost 0.

Chưa xác minh: SpO₂/RR RX trên phần cứng (IR phẳng ở lượt cuối nên app từ chối hiển thị số). RR cần
≥ 30 s liên tục; ngưỡng khoảng trống nới lên 0.25 s vì RX trên Pi có lỗ 50–110 ms.

**Cập nhật cuối ngày:** theo yêu cầu người dùng, đã gỡ bỏ bù quang 1:1 (`core/optical_map.py`, nút đo
đường truyền, vòng chỉnh trôi) và toàn bộ chế độ TDM một buồng. Trang Calib giữ mức IR/RED theo mV DAC,
dung sai ±x và chấm báo đạt (Δ = mức thu − mức phát). Ước lượng SpO₂ theo biên độ từng nhịp, RR và DAC
200 Hz vẫn giữ.

## 7. 14:30: trần IR ~840 mV nằm ở phía thu (`probe4.py`, `probe4.json.gz`)

App dừng, chỉ probe trên bus. Bậc 50 mV, 0.25 s mỗi bậc, RED tắt:

| DAC IR (mV) | 0 | 400 | 800 | 1000 | 1100 | 1200 | 1300 | 1500 | 2000 |
|---|---|---|---|---|---|---|---|---|---|
| A4 thu (mV) | 1 | 177 | 489 | 662 | 750 | 840 | 845 | 841 | 834 |

- Tuyến tính ~0.88 mV/mV tới 1200 mV DAC rồi **phẳng ở ~840 mV**; quét xuống không trễ.
- RED cùng lúc tuyến tính tới 2500 mV DAC → 1645 mV, không trần.
- Bật RED 2500 mV không đổi IR (A4 203/204/206 ở IR 400; 891/883/877 ở IR 1500): 5 V / LM358 dùng chung không phải nguyên nhân.
- Giữ IR 1500 mV 15 s: 873 → 837 mV (−4 %).

**Sửa kết luận mục 6.** Gãy của IR không ở một dòng phát cố định: lúc chiều là ~600–750 mV DAC, giờ là 1200 mV
DAC, trong khi mức RX tại trần vẫn quanh 0.7–0.9 V và không tăng khi đưa carrier sát hơn (quan sát của người dùng).
Giới hạn theo *mức điện áp thu*, không theo dòng phát → nằm ở phía thu IR: ngõ ra OPT101 IR, nguồn VS của nó, hoặc
dây/cổng A4. OPT101: V_out max = VS − 1.15…1.3 V, nên trần 0.84 V tương ứng **VS ≈ 2.0–2.1 V** thay vì 3.28 V
(suy luận, chưa đo). Trần giảm dần trong ngày (2.5 → 1.2 → 1.0 → 0.9 → 0.84 V) khi carrier dời sát hơn cũng hợp với
nguồn VS bị sụt khi dòng quang tăng (tiếp xúc/điện trở nối tiếp trên đường VS). Cần đo bằng DMM khi IR ≥ 1500 mV DAC:
VS (chân 1) và ngõ ra (chân 5) của OPT101 IR so với GND, so với OPT101 RED; hoặc đổi chéo cáp Grove hai OPT101.

## 8. 16:00: RED bật trễ và thu thấp hơn mức phát (`probe5–8.py`, `probe5–7.json.gz`)

- **Trực tiếp trên bus, app dừng** (`probe5.py`, 0 → 1000 mV): RED lên sau 0.23 / 0.16 / **5.69 s**; IR lên sau 0.6 ms.
  Đã lên rồi RED vẫn trôi ở cùng mã DAC: 1074 → 762 → 791 mV trong 10 s. Lượt đó IR đọc 1150–1180 mV
  (trần ~840 mV của mục 7 không còn: phía thu IR cũng chập chờn).
- **LED RED có sáng trong lúc trễ không** (`probe6.py`, 0 → 1500 mV, 6 lượt): đọc lại MCP4725 0x60 trong lúc trễ luôn
  đúng mã 1873. A4 (OPT101 IR, LED IR tắt) có nhận chút ánh sáng lọt từ RED: trong lúc A0 tối A4 bằng mức trước
  bước (7.03 so với 6.99 mV), A0 sáng thì A4 tăng (7.56 mV). Vậy LED RED chưa phát sáng: lỗi ở phía phát RED
  (LM358 kênh B / Q2 / LED RED / dây nối), không ở OPT101 RED. Chênh lệch chỉ ~0.5 mV, là bằng chứng yếu.
- **Giữ dòng nền** (`probe7.py`): nền 0 / 100 / 200 mV DAC đều trễ 0–2.4 s ngẫu nhiên. Ở nền 100–200 mV, A0 vẫn
  ~6 mV (sáng nay 100 mV DAC cho 47 mV), nên giữ nền không chữa được.
- **Qua app** (`probe8.py`, SignalEngine + OPT101Receiver, không GUI): trễ 0.05 / 0.07 / 0.12 / 0.18 / 3.0 / 6.9 s,
  giống hệt đo trực tiếp. App không thêm trễ: Start ghi DAC ngay, không có ramp. Trên GUI: IR lên ngay, RED lên
  sau 2–4 s, bò lên ~1.5 s rồi có lúc tụt về ~300 mV.

**Kết luận:** RED bật trễ và thu "chỉ ~890 mV" ở 1000 mV đều do đường phát RED chập chờn. Ở cùng mã DAC, RX dao động
760–1070 mV trong vài giây. Phần mềm không sửa được. Calib giờ báo "RED LED chưa sáng" khi lane còn tối dù DAC đã ghi.
Đo tiếp: scope TP_LM358_RED (LM358 chân 7) và TP_RSENSE_RED lúc bấm Start. Nếu chân 7 đã lên mà R_sense chưa có dòng
→ Q2/LED/dây; nếu chân 7 chưa lên → LM358 kênh B (thử C2b). Có thể đổi chéo: cho LED RED chạy bằng driver IR; nếu
trễ đi theo LED/carrier thì lỗi ở LED/dây nối.

## 9. 16:24: RED không chạy ở mọi trang (Classic)

- App của người dùng, Classic, DC RED 1000 / AC 22 mV. Đọc lại MCP4725 0x60 trong lúc chạy (`dac_readback.py`, chỉ đọc):
  mã 1247–1271 = **999–1018 mV**, có điều chế, 0 lỗi I²C. 0x61 (IR): 600–630 mV. App ghi đúng cả hai kênh.
- Cùng lúc A0 (RED): bò lên từ 0 tới ~980 mV trong ~8 s, sau đó DC ~800 mV và **gần như không có nhịp**. A4 (IR) hiện
  nhịp rõ (RX 75 bpm).
- Lệnh tới DAC đúng, tín hiệu mất sau DAC: chậm vài giây (bò lên), mất thành phần AC, chết ở mức thấp. Hành vi này giống
  một nút có điện trở rất lớn + tụ trên đường lệnh RED (dây/đầu nối VOUT 0x60 → R4a → LM358 chân 5, hoặc C1b),
  hay tiếp xúc kém trên đường dòng LED RED. Đây là suy luận; cần đo TP_DAC_RED và TP_CMD_RED bằng DMM khi đang phát
  (đúng thì TP_CMD_RED = TP_DAC_RED / 2, lên ngay).
- Sáng 14/11 cùng phần cứng RED có nhịp 86–160 mV ở DC 1150 (mục 5), nên đường RED đã xấu đi trong ngày.

## 10. 17:00: đo lại Calib/Classic, nhiễu RX và lọc hiển thị (`capture.py`, `filtcheck.py`)

Đường app không GUI (`capture.py`, chỉ một client trên bus, DAC 200 Hz, 0 mẫu TX mất):

| Chế độ | IR phát → thu | RED phát → thu |
|---|---|---|
| Calib 1000 mV | 1138 mV (Δ+138) | 676 mV (Δ−324), trôi 643–775 |
| Calib 1000 ± 300 mV | 663–1567 | 405–841 |
| Classic DC/AC | 600/30 → 642, dải 610–684 | 1000/22 → 618, dải 601–655 |

RED vẫn bật trễ 8.3 s (Calib) và 5.4 s (Classic). Trên GUI (17:10): IR 1381 mV, RED 645 mV ở 1000 mV.

**Nhiễu RX:** nền MAD ~1 mV. Gai là 1–3 mẫu, ±15–100 mV, 1–2 gai/s, có ở cả hai làn khi đèn đứng yên
(9/39 gai trùng thời điểm giữa A0 và A4 → có phần điện, không chỉ quang). "Tụt về 0" là RED tắt thật (hàng
giây), không phải gai. Nguồn gai chưa xác định (nhiễu nguồn/đất hoặc HAT ADC).

**Lọc hiển thị** (`core/rx_filter.py`): đoạn 1–3 mẫu lệch khỏi dây cung giữa hai mẫu lân cận > max(12 mV, 6σ) và
lệch nhiều hơn chênh lệch hai mẫu lân cận (để không ăn bước bật/tắt LED) được thay bằng dây cung; sau đó trung bình
trượt 5 mẫu căn giữa. Trên dữ liệu đo: gai 23–36 → 0–1 mỗi làn, biên độ mạch giữ 74 → 72 mV, sine 904 → 900 mV.
Chỉ đường vẽ được lọc; HR, SpO₂, RR và chấm Calib vẫn đọc mẫu thô. Trên Pi: 2.2 ms/làn mỗi lần làm mới
(lọc tăng dần; lọc lại cả 800 điểm là 15 ms).

## 11. 17:45: RX trôi ở Classic và Calib không còn khớp (`drift.py`, `drift.json.gz`)

Người dùng chỉnh carrier để Calib 1000 mV đọc RED 990 / IR 1003 mV. Sau đó ở Classic, RX lên rồi trôi xuống 700–800 mV,
có lúc giật lại ~1000 mV; quay về Calib thì không còn khớp như lúc chỉnh.

Đo lại đúng trình tự Calib 1000/1000 30 s → Classic (DC IR = DC RED = 1000 mV) 150 s → Calib 40 s. Đọc lại MCP4725
mỗi 0.5 s, ghi mọi mẫu RX, nhiệt CPU và cờ thiếu áp của Pi (`rpi_volt`):

- **Lệnh phát không đổi:** Calib đúng 1000/1000 mV mọi lần đọc. Classic có nền 998–1000 mV cộng nhịp mạch tới ~1070 mV
  suốt 150 s. App không làm trôi mức phát.
- **Pi:** không có cờ thiếu áp; CPU 63–65 °C, ổn định.
- **RX ở cùng một lệnh vẫn trôi:**
  - Calib 1: IR 902 → 671 mV trong 27 s (lên rồi tụt dần ngay sau khi bật); RED 762 → 821 mV.
  - Classic: IR 682 → 815 → 708 mV; RED 946 → 878 → 987 mV (có bước nhảy).
  - Calib 2: IR 700–719 mV, RED 767–871 mV, RED vẫn có lúc tụt về ~0.
  - IR và RED trôi khác chiều nhau, nên không phải do một nguồn chung (5 V / 3.3 V / ADC).

**Kết luận:** độ lệch nằm sau DAC, ở driver, LED, quang/cơ khí carrier hoặc OPT101 của từng kênh; không phải lỗi phần mềm.
Cần đo V trên R_sense (TP_RSENSE_IR / _RED) bằng DMM trong 2 phút giữ Calib 1000 mV. Nếu V_sense đứng yên mà RX trôi
→ quang/cơ khí/OPT101; nếu V_sense trôi → driver. Có thể kiểm tra chéo bằng cách nối VOUT DAC vào một cổng analog
trống của HAT.

## 12. 18:20: RED "bật trễ" nằm ở làn thu RED, không phải LED (`probe9.py`, `probe10.py`)

- **IR và RED cùng bước 0 → 1000 mV** (`probe9.py`, 8 lượt, app dừng): IR lên sau 1 ms ở mọi lượt. RED lên sau
  2.46 s / 1 ms / 1 ms / 1 ms, có 2 lượt **0 mV suốt 15 s**. Đọc lại MCP4725 0x60/0x61 luôn đúng mã 1248. Kích RED
  lên 2000 mV (10 mA) trong 50 ms trước khi về 1000 mV không giúp gì (2/4 lượt vẫn 0 mV). Mức RED lúc đã lên ở cùng
  mã DAC: 666–971 mV.
- **RED một mình, IR DAC = 0** (`probe10.py`, 10 lượt): lượt 8 A0 = 277 mV ngay khi bật rồi rơi về **0 mV** trong
  0.5 s và nằm đó dù lệnh không đổi. Lượt 9 A0 = 0 mV **cả 3 s trước khi bật** (DAC RED = 0). Lượt 0 A0 bò từ 6 lên
  93 mV trong 10 s. A4 (IR, tối) đứng yên 6.6–7.4 mV suốt mọi lượt.
- OPT101 còn nguồn không thể ra dưới mức tối của nó (A0 đo cả ngày 4–12 mV khi tối). 0 mV khi LED RED đang tắt nghĩa là
  OPT101 RED mất nguồn VS / GND, hoặc dây tín hiệu A0 hở (kênh ADC hở đọc 0, xem idle ở mục 7). **Kết luận mục 8
  (lỗi ở phía phát RED) bị thay:** bằng chứng mục 8 chỉ là ~0.5 mV ánh sáng lọt; bằng chứng mới cho thấy làn thu RED
  chập chờn, độc lập với lệnh LED. Bò lên chậm (6 → 93 mV trong 10 s) khớp với tiếp xúc điện trở cao nạp tụ trên VS,
  nhưng đây là suy luận. Chưa loại trừ phía phát cũng lỗi thêm.
- Phần mềm: không thể làm RED lên cùng lúc với IR khi làn thu mất tín hiệu. Calib giờ báo "RX 0 mV, thấp hơn mức tối:
  OPT101 mất nguồn/GND hoặc dây ADC, không phải LED" khi lane đọc < 2 mV (`RX_OFFLINE_MV`).
- Đo tiếp: DMM chân 1 (VS) và chân 3/8 (GND) OPT101 RED so với GND chung, lúc A0 = 0. Lắc dây Grove A0 và đầu nối
  OPT101 RED khi đang phát. Đổi chéo hai cáp Grove A0/A4 ở HAT: lỗi đi theo cáp/bo OPT101 hay ở lại cổng A0.

## 13. 22:00: SpO2 thu không theo SpO2 phát (`spo2sweep.py`, `analyze_sweep.py`, `xtalk.py`, `swapprobe.py`)

- **Nguyên nhân 1 (phần mềm, đã sửa):** `config.json` trên Pi lưu AC RED đặt tay (70 mV, sau đó 50 mV, từ Settings).
  AC RED đặt tay thì R phát cố định, kéo SpO2 ở Classic không đổi gì trên LED. Ô SpO2 ở Classic giờ trả AC RED về
  "suy ra từ SpO2" (`set_spo2_target`). Settings và BLE giữ nguyên hành vi cũ. Đã kiểm trên GUI Pi: SpO2 99 % →
  "AC 24.82 mV from SpO₂" (= 0.44 × 56.4).
- Lượt quét đầu (`spo2sweep.json`) bị chồng với app đang chạy: hai tiến trình cùng ghi con trỏ thanh ghi của HAT,
  mẫu A0/A4 lẫn sang nhau (~4 %). Chạy một mình trên bus: 0/36 000 mẫu lẫn (`swapprobe.py`). Không dùng số đó.
- **Bộ ước lượng đúng:** trên dạng sóng TX lý tưởng (HR 76, PI 4, DC 1000/1000) SpO2 99…70 đọc ra 98.9 / 94.9 / 89.9 /
  85.0 / 79.9 / 75.1 / 70.2.
- **Quét sạch trên phần cứng** (`spo2sweep3.json.gz`, AC RED tự động, HR 93, PI 5.64): tương quan IR/RED 0.98–1.00,
  36 nhịp/25 s. SpO2 phát 99 / 95 / 90 / 85 / 80 / 75 / 70 → thu ngoài thang / 97.7 / 93.7 / 89.8 / 86.0 / 81.8 / 77.8.
  R thu / R phát = 0.81–0.82 ở mọi mức.
- **Nguyên nhân 2 (đường quang):** không có lọt chéo (`xtalk.py`: IR bật, A0 vẫn 4 mV; RED bật, A4 vẫn 0). Mỗi làn
  tuyến tính nhưng có điểm 0 riêng: IR 800/1000/1200 → 576/776/941 mV, RED → 862/1105/1344 mV (≈ 1.21 × phát − 105).
  Với rx = g·(tx − x0): AC/DC thu = AC/(DC − x0). x0 IR ≈ 256 mV, RED ≈ 87 mV, nên AC/DC IR bị phóng ×1.34, RED ×1.10
  → R thu ≈ 0.82 R phát, khớp số đo. HR chỉ dùng thời điểm nhịp nên không bị ảnh hưởng.
- Để SpO2 thu = SpO2 phát trên giàn này phải quy RX về mV phát bằng bản đồ quang từng làn (hoặc hiệu chuẩn đường cong
  SpO2 riêng cho bộ thu). Chưa làm: chờ người dùng chọn.

## 14. 22:40: hiệu chuẩn SpO2 phía thu (`core/rx_spo2_cal.py`, nút "Hiệu chuẩn SpO₂" ở trang Calib)

- Cách làm: phát dạng sóng Classic với thông số đang đặt (AC RED theo SpO2) ở SpO2 98 / 90 / 80 / 70 %, mỗi mức 4 s ổn
  định + 12 s đo. Đọc R thu bằng `estimate_rx_spo2`, khớp SpO2 = A' − B'·R bằng bình phương tối thiểu. Lưu vào
  `config.json` (`rx_spo2_calibration`, giữ lại khi app thoát) nếu sai lệch tối đa ≤ 2 %. Xong thì khôi phục thông số
  Classic và tắt output. Chỉ áp dụng khi DC phát (mức + offset) của mỗi kênh lệch ≤ 20 mV so với lúc hiệu chuẩn;
  khác đi thì nhãn ghi "chưa hiệu chuẩn ở DC này" và dùng A, B của bộ phát.
- Chạy trên Pi (GUI, DC IR/RED 1000 mV, HR 93, PI 5.64): R thu 0.395 / 0.652 / 0.960 / 1.297 → **SpO2 = 110.3 − 31.2·R**,
  sai lệch tối đa 0.3 %.
- Kiểm ở Classic với mức không dùng để khớp (đọc nhãn "SpO₂ RX ước tính (đã hiệu chuẩn)" sau 30 s mỗi mức):
  phát 99 / 95 / 85 / 75 % → thu **99 / 95 / 85 / 76 %** (R 0.37 / 0.48 / 0.81 / 1.10).
- 18/11: Classic chạy DC 600/600 mV trong khi bản khớp duy nhất làm ở 1000/1000, nên app dùng A, B của bộ phát. Kết quả:
  phát 97 % thì thu 99–100 %, phát 99 % thì "ngoài thang". Từ nay `config.json` giữ một bản khớp cho mỗi cặp DC
  (tối đa 8, chạy lại ở cùng DC thì thay bản cũ; vẫn đọc được dạng một bản cũ). Kết quả trong khoảng 100–102 % hiện là
  100 %, giống máy đo SpO2.
- Giới hạn: hiệu chuẩn theo đường quang lúc chạy. Làn IR trôi trong ngày (mục 11–13), chỉnh carrier hoặc đổi DC thì
  phải chạy lại. Đây là kiểm tra vòng phát–thu của bộ mô phỏng, không phải hiệu chuẩn SpO2 lâm sàng.

## 15. 23:40: tiếng bíp theo nhịp thu (`core/beat_detector.py`, `hw/beeper.py`)

- Bộ dò đỉnh nhân quả trên làn IR thu (RED nếu IR chưa khoá): khử gai + trung bình 5 mẫu (trễ 60 ms), đỉnh xác nhận khi
  tín hiệu rơi 25 % biên độ, độ nhô ≥ max(5 mV, 5σ nhiễu, ½ biên độ các nhịp gần đây). Khoá sau 4 nhịp đều (±35 %) mới
  kêu. Chỉ kêu khi đang phát PPG (Classic/playback), không kêu khi Calib. Cao độ 880 Hz ở SpO2 100 %, giảm ½ cung mỗi
  1 % (SpO2 thu), 660 Hz khi chưa có SpO2. Nút "Tiếng bíp: bật/tắt" ở thẻ RX trang Classic, lưu `beep_enabled`.
- Mô phỏng (dạng sóng model + nhiễu 1 mV + gai 1–3 mẫu như Pi): 15–300 bpm và 5 tình trạng bệnh lý: không thừa tiếng,
  hụt ≤ 2 % ở 300 bpm; trễ trung vị 90–210 ms ở 60–300 bpm, 0.35–0.6 s ở 15–30 bpm. AC ≥ 10 mV đủ; 5 mV hầu như
  không kêu (tín hiệu yếu). Nhiễu + gai + đợt nhiễu σ 15 mV trong 120 s: 0 tiếng.
- Trên Pi (ghi từ monitor của sink HDMI bằng `pw-record`): `pw-play` mặc định (độ trễ 100 ms) cắt tiếng 70 ms thành
  45 + 30 ms có lỗ 40 ms; `--latency 10ms` phát liền khi GUI đang chạy (20 ms thêm một tiếng 10 ms). Với 10 ms:
  22 tiếng/19.9 s, mỗi tiếng 65–75 ms, 64.5/phút khi nhịp RX 64–65 bpm, cao độ ~726 Hz (FFT, phân giải 23 Hz;
  SpO2 93 % → 718 Hz). Tắt tiếng: sink im lặng 5.9 s. Chỉ kiểm được tín hiệu tới sink; loa/màn hình HDMI có phát ra
  tiếng hay không thì chưa kiểm.

## 16. 15/11: nhịp thở RR từ dạng sóng PPG thu (`core/rx_resp_rate.py`, `rrcapture*.py`, `rreval.py`)

- Cách tính: mỗi nhịp lấy 3 đặc trưng (mức nền RIIV, biên độ RIAV, khoảng nhịp RIFV) trên làn IR và, khi đang đọc
  được, làn RED. Nhịp tìm bằng `core/beat_detector.py` (đáy→đỉnh, khử gai) trên lưới 100 Hz; mỗi chuỗi lọc Hampel,
  lấy mẫu 4 Hz, bỏ xu hướng, cửa sổ Hann, phổ 4–min(40, 0.45×nhịp mạch)/phút bước 0.25; phổ chuẩn hoá rồi cộng
  (spectral fusion, Charlton 2018). Chỉ ra số khi đỉnh chiếm ≥ 0.30 công suất trong ±1/phút và ≥ 3× điểm mạnh nhất
  cách ≥ 2/phút. Bỏ phần tối ở đầu cửa sổ (trước khi bấm Start) thay vì báo "có mẫu 0 mV" suốt 60 s; bỏ mẫu mới
  hơn `now` (trước đây báo "mẫu lỗi").
- Mô phỏng (dạng sóng model + nhiễu 1 mV): độ sâu mặc định 4 % đọc đúng 6–27/phút; tắt hô hấp thì không ra số
  (điểm ≤ 0.40 / 2.4).
- Pi, app dừng, thu 64 s mỗi mức (`rrcap4.json.gz`, `rrcap16.json.gz`; HR 91, AC IR 56 mV):
  - độ sâu 16 %: RR 10 / 18 / 27 / 36 → 10.0–10.1 / 17.9–18.0 / 26.9–27.0 / 35.9–36.1 (IR+RED, cửa sổ 35–63 s);
  - độ sâu 4 %: phần lớn "unclear", IR+RED đọc 10 và 18 ở một số cửa sổ; không có số sai. Lý do: mức nền làn IR
    dao động 45–55 mV (trôi, bước nhảy, gai tới +300 mV) so với ~4 mV điều biến hô hấp.
- Pi GUI (16 %): RR 12 → 12/phút, RR 27 → 25–27/phút, RR 18 → 16/phút (lúc dùng bản chậm).
- Hiệu năng: bản đầu chạy bộ dò từng mẫu tốn 3 s/làn trên Pi, trên luồng Tk → RX thủng, "Lost" tăng. Giờ: khử gai
  cả chuỗi một lần (thêm lối thoát sớm chính xác: 12 → 4 ms/6000 mẫu trên laptop, kết quả giống hệt), 0.22 s/làn,
  chạy trong luồng riêng mỗi 10 s.
- Phát hiện kèm: luồng bíp gọi `get_samples_since` (sao chép cả bộ đệm 6400 mẫu dưới khoá receiver) 100 lần/s →
  luồng thu chờ khoá. Thêm `get_samples_after` (chỉ đọc mẫu mới từ đầu mới nhất), luồng bíp bỏ làn RED khi IR đã
  khoá, bộ dò chỉ khử gai đoạn đuôi (546 → 232 µs/mẫu). 2 phút Classic trên Pi: Lost 1076 (bản đã commit) → 342;
  tắt bíp: 26. Chế độ không GUI: RX đúng 100 Hz, khe lớn nhất 25 ms; còn lỗ RX > 50 ms khi chạy GUI ở cả bản đã
  commit — chưa xử lý.

## 17. 15/11 13:45: IR 900 → 700 mV rồi giật lên ở cùng lệnh DAC (`irdrift.py`, `irhold.py`, `analyze_irdrift.py`)

App dừng, chỉ probe trên bus. Đọc lại MCP4725 mỗi 0.5 s, RED giữ 1000 mV làm làn đối chứng (`irdrift.json.gz`):

| Pha (IR DAC) | IR thu (trung vị 3 s) | RED thu |
|---|---|---|
| Bật nguội 1000 mV, giữ 150 s | 1924 → 1475 → 1156 → 986 → 901 → 849 → 804 (vẫn đang giảm) | 1246 → 1235 |
| Tắt 5 s rồi bật 1000 mV 30 s | 958 → 871 → 800 | 1235 |
| Tắt 60 s rồi bật 1000 mV 30 s | 1911 → 1306 → 1172 → 1103 | 1234 |
| Xung 1000 mV, 50 ms / 500 ms (10 %), 90 s | đỉnh xung 2000–2005 suốt 90 s (≈ trần OPT101, có thể đang bị xén) | 1231–1235 |
| Giữ 300 mV 90 s | 348 → 348 | 1233 |

- Mã DAC đọc lại luôn đúng (1248 = 1000 mV, 375 = 300 mV). Không có cờ thiếu áp; CPU 68–76 °C. RED cùng loại DAC,
  cùng nguồn, cùng phần mềm: lệch ≤ 1 %.
- IR chỉ tụt khi LED IR sáng liên tục ở mức cao. Nghỉ 60 s thì hồi gần hết, nghỉ 5 s thì hồi rất ít. Chạy xung 10 %
  ở cùng mức thì không tụt. Đây là hiệu ứng tích luỹ theo năng lượng, có "trí nhớ" vài chục giây (dạng nhiệt).

Giữ IR một mình 60 s ở từng mức, nghỉ 45 s giữa các mức (`irhold.json.gz`):

| IR DAC (mV) | 0–1 s | 10 s | 30 s | 60 s | Thay đổi |
|---|---|---|---|---|---|
| 450 | 651 | 649 | 648 | 648 | −0.5 % |
| 600 | 989 | 984 | 982 | 968 | −2 % |
| 750 | 1350 | 1323 | 1124 | 912 | −32 % |
| 900 | 1549 | 1440 | 1130 | 1045 | −33 % |

**Kết luận:** DAC không phát sai. Làn IR có một ngưỡng ở khoảng 600–750 mV DAC (~1.0–1.35 V thu): dưới ngưỡng thì ổn
định, trên ngưỡng thì tụt mạnh theo thời gian sáng và hồi lại khi nghỉ. Ở 1000 mV DAC, IR thu lúc mới bật ~1.9 V, sát
trần đảm bảo 2.0 V của OPT101 (V_S − 1.3 V), tức IR đang quá sáng so với RED (1235 mV ở cùng lệnh). Cú "giật lên
1100 mV" trong app khớp với LED IR được nghỉ (Stop/Start, đổi trang, đoạn điều chế thấp) rồi sáng lại; lần đo này
không thấy bước nhảy tự phát nào ngoài một chớp 0.2 s (+80/−146 mV) ở giây 51.

Linh kiện cụ thể chưa xác định. Ánh sáng vài µW lên OPT101 không thể làm nóng nó, và phục hồi quá tải của OPT101 là
50 µs, nên nghi phía phát IR (LED IR/driver nóng lên). Ngưỡng 600–750 mV DAC cũng trùng với mục 6 dù vị trí quang đã
đổi; mục 7 thì thấy ngưỡng ở 1200 mV. Thử tách không cần dụng cụ: chắn một lớp giấy giữa LED IR và OPT101 để thu còn
~600 mV ở 1000 mV DAC. Nếu vẫn tụt → phía phát (theo dòng); nếu hết tụt → phía thu (theo mức sáng). Có DMM thì đo
V trên R_sense IR khi giữ 1000 mV 2 phút.

## 18. 15/11 15:00: APFT-GAN trên Pi 4: thời gian và CPU (`apft_bench.py`, `apft_bench.jsonl`)

APFT-GAN v3 HR v1, checkpoint 1250 (100,5 M tham số, float32, SHA256 khớp `assets/apft/manifest.json`), PyTorch 2.5.1,
`OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=1`, torch 1 luồng như app. App GUI vẫn chạy (Pathology, output tắt; ~50–90 % một
lõi, Xwayland + gnome-shell ~30 %).

| Bước | Thời gian | CPU tiến trình | CPU toàn máy (4 lõi) |
|---|---|---|---|
| Nạp (SHA256 402 MB + `torch.load` + dựng mạng) | 11,9 s | 91 % một lõi | 75 % |
| 1 cửa sổ 30 s (1200 mẫu, 40 Hz, 30 patch × Heun 16 bước), 1 luồng, 3 lần | 91–100 s | 98–100 % một lõi | 67–86 % |
| Cùng việc, 4 luồng, 2 lần | 123–128 s | ~192 % | ~89 % |

RAM đỉnh 972 MB. CPU 82–85 °C trong lúc chạy (ngưỡng hạ xung Pi 4 là 80 °C; xung đọc được 1,8 GHz, cờ throttle không
đọc được vì không có `vcgencmd`). Chậm hơn thời gian thực ~3,2 lần → chỉ dùng được kiểu sinh trước rồi phát. 4 luồng
chậm hơn vì các lõi khác đang bận với GUI. Trang Neural cho APFT giới hạn 300 s (`core/sequence_worker.py`).

## 19. 15/11 16:30: APFT nhanh hơn, int8 và độ bám HR (`scripts/apft_speed_bench.py`, `scripts/apft_quant_quality.py`, `core/apft_fast.py`)

Pi 4, PyTorch 2.5.1, 1 luồng, app GUI chạy (`apft_speed_pi.jsonl`):

| Biến thể | Nạp | 1 cửa sổ 30 s | Đầu ra so với bản gốc |
|---|---|---|---|
| fp32 như bản phát hành | 10,1–10,4 s | 94,8 s | — |
| fp32, dựng mạng trên `meta` + flow head tính trước theo (h, t) | 6,4–6,9 s | 45,7 s | giống hệt (sai khác 0) |
| int8 động (`qnnpack`) + tính trước | +4 s lượng tử | 21,7 s (2 luồng 18,3 s) | khác phân bố, xem dưới |
| file fp16 (192 MB) | 5,0 s | — | trọng số làm tròn; không dùng |

Worker của app (`python -m core.sequence_worker 42 APFT-GAN 75`) sau khi đổi: **57,7 s** tổng, RSS tối đa 650 MB
(trước ~110 s, 972 MB).

Chất lượng int8 (laptop, engine `qnnpack` như Pi, 192 cửa sổ mỗi bộ, HR yêu cầu 50–150; `apft_quant_quality.json`):
1 − KS trung bình trên 22 đặc trưng so với fp32 seed A: fp32 seed B 0,912 (mức do lấy mẫu), int8 seed A 0,861, int8
seed B 0,823; thấp nhất amp_cv 0,69–0,72. int8 động làm đổi dạng sóng sinh ra nhiều hơn dao động lấy mẫu → app không dùng.

Độ bám HR yêu cầu (fp32, 16 cửa sổ mỗi mức, HR đo bằng khoảng nhịp `core/beat_detector.py`):

| Yêu cầu (bpm) | 50 | 60 | 70 | 75 | 80 | 90 | 100 | 110 | 120 | 130 | 140 | 150 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Trung vị đo | 80 | 62 | 72 | 76 | 83 | 91 | 86 | 79 | 83 | 84 | 79 | 80 |
| Tỉ lệ trong ±10 % | 0 | 0,50 | 0,44 | 0,56 | 0,56 | 0,38 | 0,38 | 0,19 | 0 | 0 | 0 | 0 |

APFT chỉ bám HR một phần trong 60–100 bpm; ngoài khoảng đó gần như luôn ra ~80 bpm. HR "yêu cầu" không phải HR bảo đảm.

## 20. 15/11 17:00: khoảng HR min–max cho APFT (`core/apft_range.py`, `scripts/apft_range_eval.py`)

Trang Neural, chế độ APFT: hai thanh **HR min / HR max**, giới hạn 60–100 bpm (vùng mà mục 19 cho thấy model còn bám
HR yêu cầu), rộng tối thiểu 2 bpm. Worker sinh mỗi lượt 8 cửa sổ trong một lần gọi, HR yêu cầu trải đều trong khoảng;
mỗi cửa sổ được đếm nhịp bằng `core/beat_detector.py` (bỏ "nhịp" đến sớm hơn 65 % khoảng nhịp trung vị, ví dụ sóng
dicrotic ở nhịp đầu; loại cửa sổ có > 5 % khoảng nhịp lệch > 35 %, tức có nhịp bị sót). Chỉ nhận cửa sổ có HR đo nằm
trong khoảng, chọn cái gần giữa khoảng nhất; lượt sau dời mọi yêu cầu ngược với độ lệch trung vị. Hết 240 s mà không có
thì báo lỗi kèm HR đo được, **không phát** cửa sổ ngoài khoảng.

- Batch gần như miễn phí trên Pi 4 (1 luồng, app chạy): 1 / 2 / 4 / 8 cửa sổ mỗi lần gọi mất 44,0 / 44,9 / 49,0 / 57,4 s.
- Tỉ lệ tìm được trong ngân sách (laptop, checkpoint thật, 20 lần mỗi khoảng, `apft_range_eval.json`): 4 lượt × 8 cửa
  sổ: 60–65 15/20, 70–75 19/20, 70–80 20/20, 85–90 18/20, 95–100 18/20, 60–100 20/20 (trung bình 1,0–2,2 lượt). Cùng
  ngân sách nhưng 1 cửa sổ mỗi lượt chỉ được 5–13/20 với khoảng 5–10 bpm.
- Pi, app thật: 70–80 → 79,2 bpm (1 cửa sổ, bản trước batch, ~55 s); khi phát ra LED, ước lượng RX đọc 79 bpm ở cả IR
  và RED. 70–80 → 73,9 bpm và 70–75 → 70,5 bpm (1 lượt 8 cửa sổ, ~80 s gồm nạp).

HR là HR đo trên dạng sóng phát, không phải HR "yêu cầu". SpO₂/RR không phải đầu vào của APFT (model học PPG một kênh,
không có nhãn RR, không có cặp IR/RED); chúng chỉ có thể thêm bằng lớp vật lý sau model.
