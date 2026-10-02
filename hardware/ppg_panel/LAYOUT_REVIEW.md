# Rà soát layout và V-score — 2026-10-02

## Đi dây và bố trí hai mặt

Ba board dùng đoạn ngang/dọc và đoạn chéo 45°, vát các góc rẽ tự do 90°.
Điểm vào pad, via và điểm phân nhánh điện được giữ để không cắt mất kết nối.
Không đổi net, giá trị linh kiện, bề rộng đường nguồn, vị trí header, tâm cảm biến
hay kích thước board. `hardware/routing_45.py --audit` kiểm tra góc đoạn dây
và góc rẽ; DRC/parity kiểm tra kết nối và khoảng hở thực tế.

Góp ý đặt linh kiện hai mặt có ích khi giải quyết được đường dây hoặc diện tích.
Không có quy tắc bắt buộc tất cả điện trở ở dưới, tụ ở trên:

- OPT101 đã có C1/C2 mặt trước; điện trở và tụ lọc output mặt sau. Giữ cách này.
- BPW34 giữ op-amp, Rf và Cf cùng mặt sau để vòng SUM/feedback ngắn, tránh thêm
  via vào nút trở kháng cao. Mặt trước dành cho photodiode và không gian gá.
  Tụ bypass và tụ reference nằm gần mạch analog tương ứng.
- Driver giữ điện trở gần LM358/transistor; tụ 100 nF gần chân nguồn,
  tụ bulk phía sau. Đổi mặt chỉ để phân loại R/C không làm giảm khung 70×40 mm,
  trong khi có thể thêm via, kéo dài đường hồi tiếp và tăng chi phí lắp hai mặt.

Góc 90° không tự làm đường đồng đứt. Rủi ro khi tách board là đồng/linh kiện
quá gần đường cắt và ứng suất uốn; chuyển góc rẽ 45° giúp layout đồng đều,
không thay thế kiểm tra DRC, khoảng hở và quy trình tách.

## Đối chiếu video và điều kiện gia công

Đã đọc transcript và xem minh họa [video DIY Hideout](https://www.youtube.com/watch?v=ph2jV5HMxfQ):
đường bao ngoài là Edge.Cuts, đường V-score là chỉ dẫn riêng và cần xuất Gerber
của lớp chỉ dẫn. Ví dụ thủ công thêm 2 mm khoảng đệm; không áp dụng con số đó
như quy định bắt buộc cho mọi nhà in. Không bỏ qua lỗi kết nối như mẹo trong
ví dụ nhân bản board: panel này dùng tiền tố net riêng cho từng thiết kế.

[Hướng dẫn NextPCB](https://www.nextpcb.com/blog/pcb-panelization-design-guide-v-score-tab-routing)
cho phép V-score ghép không khe, cùng vật liệu/stack-up, và khuyến nghị linh kiện
cách V-cut ít nhất 1 mm. Panel hiện tại:

- FR-4 1,6 mm, hai lớp đồng; khung chữ nhật 70×80 mm.
- Hai tâm V-score Y=20/40 mm từ cạnh trên, chạy hết chiều ngang 70 mm.
- Chỉ phay đường bao ngoài; không phay khe ở tâm V-score.
- Đồng/pad/via/vùng đồng cách tâm score ≥1,5 mm mỗi phía.
- Bao footprint R/C cách tâm score ≥2,095 mm; không có nối điện giữa ba board.

Các điều kiện hình học này phù hợp V-score danh nghĩa. Dấu vẽ trong KiCad không
tự tạo rãnh cơ khí: nhà in phải **score hai mặt**, xác nhận độ sâu, phần FR-4
còn lại và dung sai theo máy của họ. Tách bằng dụng cụ V-score **trước khi hàn**,
đặc biệt tránh uốn panel đã lắp tụ gốm. Không dùng lực bẻ mạnh để thay cho score
đúng độ sâu. Nếu nhà in lắp SMT theo panel, họ cần duyệt thanh biên/fiducial
và phương án tách riêng; bản này là panel PCB trần, không mặc định là panel SMT.

## Kết quả và giới hạn

Ba nguồn: DRC/parity sạch; kiểm tra pin/value và SMD vẫn đạt.
Panel: DRC sạch và đối chiếu nguồn, net riêng, lỗ khoan, vùng V-score đạt.
Xem `reports/drc.rpt`, `reports/panel_audit.json` và báo cáo của từng nguồn.
Đây là kiểm tra CAD; chưa chứng minh nhiễu, độ ổn định analog hay khả năng
tách một mẫu sản xuất thực. Nhà in phải duyệt CAM trước khi sản xuất.
