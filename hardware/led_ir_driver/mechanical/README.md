# Gá chuyển driver 70×50 mm lên đế 70×55 cũ

In `driver_70x50_adapter_print.stl`, đơn vị mm, scale 100%, mặt phẳng lớn
đặt xuống bàn in. Adapter 70×55 mm, dày nền 2 mm, tổng cao 6 mm. Không in
`*_pcb_assembly.stl` để thay cho adapter.

Đặt adapter lên bốn trụ driver cũ trên đế hệ thống. Hai lỗ adapter phía
trên tại (4,4), (66,4) bắt vào trụ cũ bằng vít M3 phù hợp, danh nghĩa M3×6.
PCB mới nằm tại gốc (0,5), mặt dưới cao 6 mm so với mặt dưới adapter.
Hai vít PCB trên tại (4,25)/(66,25) vào lỗ mồi Ø2,6 trên adapter, dùng
M3×6. Hai vít PCB dưới tại (4,46)/(66,46) đi qua adapter vào trụ cũ,
danh nghĩa M3×16 theo đế nguồn có trụ 5 mm + nền 4 mm. Kiểm tra chiều dài
vít thật và không để vít chạm nền bên dưới. Không siết quá mức vào nhựa.

PCB cao hơn vị trí cũ 6 mm; cắt chân hàn nhô sau PCB ≤2 mm. Gá không thay
vị trí Pi hoặc thân hộp quang. Đã kiểm tra mesh kín, một khối, không giao
với PCB và bao chân hàn danh nghĩa. Chưa kiểm tra độ co, đầu cáp, module
MCP4725 mua thực hoặc thử lắp. `fit_report.json` lưu phép kiểm tra và tọa độ.
