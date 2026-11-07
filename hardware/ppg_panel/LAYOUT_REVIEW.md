# Layout hai board — 06/11/2026

OPT10170×20mm phía trên, driver70×40mm phía dưới, panel70×60mm. Một V-score ở20mm từ mép trên. Giữ nguyên layout board nguồn, driver chỉ tịnh tiến.

verify_panel.py kiểm tra đúng hai source OPT/TX, không còn BPW, outline/score, source hash và toàn bộ footprint/pad/track/via/drill/net. Đồng cách score≥1,5mm, bao R/C≥2mm. Kết quả hiện hành ở reports/panel_audit.json.

Edge_Cuts chỉ phay khung ngoài. User_Comments chỉ dẫn V-score hai mặt. Tách trước khi hàn; cần nhà in xác nhận dung sai. Không nối điện qua score. DRC không thay thế thử nghiệm mạch. Rà soát tối ưu ba board cũ đã lưu trong archive.
