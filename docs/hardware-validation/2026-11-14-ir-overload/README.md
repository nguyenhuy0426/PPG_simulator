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
- Giới hạn: hiệu chuẩn theo đường quang lúc chạy. Làn IR trôi trong ngày (mục 11–13), chỉnh carrier hoặc đổi DC thì
  phải chạy lại. Đây là kiểm tra vòng phát–thu của bộ mô phỏng, không phải hiệu chuẩn SpO2 lâm sàng.
