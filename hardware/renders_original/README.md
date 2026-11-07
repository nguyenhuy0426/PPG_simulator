# Ảnh 3D bản gốc (driver trước v2.0 + OPT101)

Render bằng `kicad-cli pcb render` (KiCad 10.0.6, chất lượng basic). Driver lấy từ commit `fcd6c97a` (không jumper, dùng chung I²C); OPT101 lấy từ file hiện tại, không đổi so với bản đó.

- `PPG_original_driver_OPT101_assembled.png`: ảnh tổng hợp.
- `driver_orig_*.png`, `opt101_*.png`: từng góc nhìn (mặt trước, góc nghiêng, mặt sau).

Giới hạn: hình dạng module MCP4725 (tấm đỏ 15,24 × 15,24 mm, nằm ngang, chìa vào phía trong board) và chip LM358P là model gần đúng, không đo từ linh kiện thật. Thân OPT101P theo bản vẽ vỏ NTC (R-PDIP-T8) trong `docs/ds_linhkien/opt101.pdf`. Đây là hình dựng, không phải ảnh chụp hay kiểm tra điện.
