import os
import shutil
import pptx
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

SRC_PPTX = '/home/huynn/Documents/BaoCaoTienDo_KLTN.pptx.bak'
DST_PPTX = '/home/huynn/Documents/BaoCaoTienDo_KLTN.pptx'

# Colors
C_DARK_BLUE = RGBColor(13, 71, 161)
C_TITLE = RGBColor(33, 33, 33)
C_BODY = RGBColor(66, 66, 66)
C_CARD_BG = RGBColor(248, 249, 250)
C_CARD_BORDER = RGBColor(207, 216, 220)
C_PILL_BG = RGBColor(232, 245, 233)
C_PILL_BORDER = RGBColor(76, 175, 80)
C_PILL_TEXT = RGBColor(46, 125, 50)

def add_header_and_title(slide, header_text, title_text, pill_text=None, pill_color=C_PILL_BG, pill_border=C_PILL_BORDER, pill_txt_color=C_PILL_TEXT):
    # Set text on layout placeholders
    for ph in slide.placeholders:
        if ph.placeholder_format.idx == 100:
            ph.text = header_text
            if ph.text_frame.paragraphs:
                p = ph.text_frame.paragraphs[0]
                p.font.size = Pt(12)
                p.font.bold = True
        elif ph.placeholder_format.idx == 101:
            ph.text = title_text
            if ph.text_frame.paragraphs:
                p = ph.text_frame.paragraphs[0]
                p.font.size = Pt(26)
                p.font.bold = True

    # Pill
    if pill_text:
        pill = None
        for s in slide.shapes:
            if s.name == 'statusPill':
                pill = s
                break
        if not pill:
            pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, 9677095, 457200, 1965960, 384048)
            pill.name = "statusPill"
        
        pill.fill.solid()
        pill.fill.fore_color.rgb = pill_color
        pill.line.color.rgb = pill_border
        pill.line.width = Pt(1.2)
        tf = pill.text_frame
        tf.word_wrap = False
        p = tf.paragraphs[0]
        p.text = pill_text
        p.alignment = PP_ALIGN.CENTER
        p.font.bold = True
        p.font.size = Pt(9.5)
        p.font.color.rgb = pill_txt_color

def add_card(slide, left, top, width, height, title, body_lines, 
             fill_rgb=C_CARD_BG, border_rgb=C_CARD_BORDER, title_color=C_DARK_BLUE):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = fill_rgb
    card.line.color.rgb = border_rgb
    card.line.width = Pt(1.2)
    
    tf = card.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.18)
    tf.margin_right = Inches(0.18)
    tf.margin_top = Inches(0.16)
    tf.margin_bottom = Inches(0.16)
    
    p0 = tf.paragraphs[0]
    p0.text = title
    p0.font.bold = True
    p0.font.size = Pt(12)
    p0.font.color.rgb = title_color
    p0.space_after = Pt(6)
    
    for line in body_lines:
        p = tf.add_paragraph()
        p.text = line
        p.font.size = Pt(9.8)
        p.font.color.rgb = C_BODY
        p.space_after = Pt(4)
    return card

def main():
    prs = pptx.Presentation(SRC_PPTX)
    print(f"Loaded original presentation with {len(prs.slides)} slides.")

    # -------------------------------------------------------------
    # 1. Update Slide 3 (TỔNG KẾT)
    # -------------------------------------------------------------
    slide3 = prs.slides[2]
    for s in slide3.shapes:
        if s.has_text_frame:
            for p in s.text_frame.paragraphs:
                if "Train PPG-physiGPT trên MIMIC-III" in p.text:
                    p.text = "Phát triển kiến trúc APFT (physiGPT) & PSF-GAN; bản thảo bài báo Q1"
                elif "Độ giống đặc trưng của PPG-physiGPT large" in p.text:
                    p.text = "Độ giống đặc trưng của APFT Large so với người thật (đạt V1); thiết kế PSF-GAN giải quyết loạn nhịp"
    print("Updated Slide 3.")

    # -------------------------------------------------------------
    # 2. Update Slide 18 (MÔ HÌNH SINH PPG)
    # -------------------------------------------------------------
    slide18 = prs.slides[17]
    for s in slide18.shapes:
        if s.name == 'modelTable' and s.has_table:
            t = s.table
            data_rows = [
                ['Mô hình', 'Kiến trúc', 'AUC giám khảo / Chỉ số', 'Quyết định'],
                ['3-Gaussian (IntelliVue)', 'Giải tích tham số 3 đỉnh Gaussian', 'Khớp chuẩn nhịp', 'Mặc định trên Pi (DAC/TX)'],
                ['LSM-GAN (author_v3)', 'GAN Conv1D, loss phổ log (Ding 2021)', '1,00', 'Baseline trong app, sinh 30 s'],
                ['PhysioMix (vòng 9)', 'Conditional GAN, 162k tham số', '0,999', 'Đã gỡ (loạn nhịp 30 s)'],
                ['PhysioFlow (vòng 10)', 'Rectified flow, U-Net 6,9M tham số', '1,00', 'Đã gỡ (không vượt trội trên wrist)'],
                ['APFT (physiGPT Large)', 'Patch Transformer + Flow-Matching, 99,9M', '1−KS 0,938 (98,1%)', 'Bản V1 ở tầng đặc trưng'],
                ['APFT-GAN v3', 'Tinh chỉnh đối nghịch cục bộ (head-only)', '1−KS 0,936', 'Cân bằng anchor & strict critic'],
                ['PSF-GAN (Pure GAN)', 'Source-Filter (pha điều hòa) + MPD/MSD', 'Đang huấn luyện', 'Khắc phục triệt để lỗi loạn nhịp'],
            ]
            for r_idx, row in enumerate(t.rows):
                if r_idx < len(data_rows):
                    for c_idx, val in enumerate(data_rows[r_idx]):
                        row.cells[c_idx].text = val
                        p = row.cells[c_idx].text_frame.paragraphs[0]
                        p.font.size = Pt(9.5 if r_idx > 0 else 10)
                        if r_idx == 0:
                            p.font.bold = True
        elif s.name == 'mdABody' and s.has_text_frame:
            s.text_frame.text = "Chấm trên 180 bệnh nhân MIMIC-III chưa từng train. Mô hình phân biệt 3 nhánh (thời gian, phổ, tự tương quan). Mức người thật vs người thật: 0,50, d' = 0,14."
        elif s.name == 'mdBBody' and s.has_text_frame:
            s.text_frame.text = "Trong app hiện tại chạy 3-Gaussian (thời gian thực) và LSM-GAN (chuỗi 30 s). APFT (physiGPT) và PSF-GAN là bước nâng cấp lớn về hình thái sóng và độ tương đồng đặc trưng sinh lý."
    print("Updated Slide 18.")

    # -------------------------------------------------------------
    # 3. Update Slide 19 (MÔ HÌNH SINH PPG · KIẾN TRÚC APFT)
    # -------------------------------------------------------------
    slide19 = prs.slides[18]
    add_header_and_title(slide19, "MÔ HÌNH SINH PPG  ·  KIẾN TRÚC APFT (PPG-PHYSIGPT)", 
                         "Autoregressive Patch Flow Transformer & Tinh chỉnh APFT-GAN v3",
                         pill_text="ĐÃ ĐẠT V1 ĐẶC TRƯNG")
    
    keep_names = ['Text 0', 'statusPill', 'Slide Number Placeholder 0']
    shapes_to_remove = [s for s in slide19.shapes if s.name not in keep_names]
    for s in shapes_to_remove:
        sp = s._element
        sp.getparent().remove(sp)
    
    slide19.shapes.add_picture('docs/figures_ppt/arch_apft.png', 548640, 1422400, 7200000, 4850000)
    
    c1_lines = [
        "• Cửa sổ 30 s @ 40 Hz chia 30 patch × 40 mẫu",
        "• Causal Transformer: Large 99,9M param (12 layers, dim 768); Base 30,7M (8 layers, dim 512)",
        "• RoPE, SwiGLU, RMSNorm",
        "• Đầu Flow-Matching (adaLN-MLP) dự đoán trường vận tốc vi phân v_θ",
        "• Bộ giải Heun ODE (16 bước) kết hợp KV-Cache tăng tốc suy luận ×2,3 lần (7,6 s / 64 cửa sổ)"
    ]
    add_card(slide19, 7950000, 1422400, 3700000, 2350000, "Thông số & Cơ chế APFT", c1_lines)

    c2_lines = [
        "• Khắc phục lỗi sụp đổ độ dốc ở v1: Gradient đối nghịch L_adv chỉ vào Flow Head (--adv-scope head)",
        "• Backbone được neo giữ bởi Flow Anchor (L_flow-anchor)",
        "• Khớp phân phối 22 đặc trưng bằng khoảng cách 1D-Wasserstein (L_feat)",
        "• Huấn luyện trên 2,18 triệu cửa sổ MIMIC-III (Kaggle 2×T4 DDP fp16, ~8,5 h)"
    ]
    add_card(slide19, 7950000, 3922400, 3700000, 2350000, "Tinh chỉnh APFT-GAN v3", c2_lines)
    print("Updated Slide 19 with arch_apft.png and detailed cards.")

    # -------------------------------------------------------------
    # 4. Insert New Slide 20: KIẾN TRÚC PSF-GAN
    # -------------------------------------------------------------
    slide20 = prs.slides.add_slide(prs.slide_layouts[2])
    add_header_and_title(slide20, "MÔ HÌNH SINH PPG  ·  KIẾN TRÚC PSF-GAN",
                         "Pure Periodic Source-Filter GAN & Cụm Discriminator Đa chu kỳ",
                         pill_text="KIẾN TRÚC MỚI", pill_color=RGBColor(254, 243, 199), 
                         pill_border=RGBColor(245, 158, 11), pill_txt_color=RGBColor(180, 83, 9))
    
    slide20.shapes.add_picture('docs/figures_ppt/arch_psf_gan.png', 548640, 1422400, 7200000, 4850000)
    
    psf_c1 = [
        "• Khắc phục triệt để lỗi trôi pha nhịp tim của các GAN trước đây (PhysioMix, LSM-GAN)",
        "• Tích phân pha điều hòa φ(t) = φ0 + 2π ∫ (f0 + Δf(t))dt từ nhịp tim đặt f0 và HRV biến thiên ±30%",
        "• 4 sóng hài [sin(kφ), cos(kφ)] kích thích trực tiếp bộ lọc 1D Conv đa tỉ lệ (7,22M param)",
        "• Khóa nhịp tim tuần hoàn chính xác 100% theo thiết kế"
    ]
    add_card(slide20, 7950000, 1422400, 3700000, 2350000, "Máy phát Nguồn - Lọc (7,22M)", psf_c1)

    psf_c2 = [
        "• HiFi-GAN MPD (Multi-Period): 5 mạng chu kỳ nguyên tố (p = 2, 3, 5, 7, 11) bắt nhịp tuần hoàn",
        "• MSD (Multi-Scale): 3 mạng đa tỉ lệ kiểm tra cấu trúc thời gian vĩ mô",
        "• Log-STFT Critic: Kiểm tra năng lượng phổ tần số",
        "• Loss kết hợp: L_LSGAN + λ_FM · L_FM + λ_feat · L_feat (Wasserstein 22 đặc trưng)"
    ]
    add_card(slide20, 7950000, 3922400, 3700000, 2350000, "Cụm Discriminator & Loss (4,51M)", psf_c2)
    print("Created Slide 20 (PSF-GAN Architecture).")

    # -------------------------------------------------------------
    # 5. Insert New Slide 21: ĐÁNH GIÁ THỐNG KÊ & BENCHMARK
    # -------------------------------------------------------------
    slide21 = prs.slides.add_slide(prs.slide_layouts[2])
    add_header_and_title(slide21, "MÔ HÌNH SINH PPG  ·  ĐÁNH GIÁ THỐNG KÊ & BENCHMARK",
                         "Kết quả đánh giá trên 180 bệnh nhân MIMIC-III độc lập với 22 đặc trưng",
                         pill_text="V1 ĐẠT  ·  V2 TIẾP TỤC", pill_color=RGBColor(238, 242, 255),
                         pill_border=RGBColor(99, 102, 241), pill_txt_color=RGBColor(67, 56, 202))
    
    slide21.shapes.add_picture('docs/figures_ppt/benchmark_metrics.png', 548640, 1422400, 7400000, 4850000)

    bench_c1 = [
        "• APFT Large đạt tương đồng 0,9413 / 0,960 (98,1% mức người thật vs người thật)",
        "• Vượt trội hoàn toàn so với RSR-Flow (0,904) và RSH-GAN (0,888)",
        "• APFT Large và APFT-GAN tương đương nhau (+0,0016, khoảng tin cậy 95% [-0,0112, +0,0146])",
        "• Cả hai đều đánh bại hoàn toàn các baseline trước trên cùng tập dữ liệu"
    ]
    add_card(slide21, 8150000, 1422400, 3500000, 2350000, "Đạt Tiêu chí V1 (98,1%)", bench_c1)

    bench_c2 = [
        "• Ngưỡng V2: Mean 1-KS ≥ 0,950 và Tree Acc ≤ 0,600",
        "• APFT đạt Tree Acc 0,638 (gần mức 0,60 nhất; RSH-GAN bị tách 0,975)",
        "• Giám khảo nghiêm C2ST: khoảng cách d' giảm từ 17,9 → 8,6 (tiệm cận mức xáo pha người thật 7,7)",
        "• Điểm nghẽn cần hoàn thiện: bù đắp năng lượng dải tần 5–8 Hz và sai phân bậc 2"
    ]
    add_card(slide21, 8150000, 3922400, 3500000, 2350000, "Tiêu chí V2 & C2ST", bench_c2)
    print("Created Slide 21 (Statistical Evaluation & Benchmark).")

    # -------------------------------------------------------------
    # 6. Insert New Slide 22: DÁNG SÓNG & ĐẶC TÍNH TRIỂN KHAI PI 4
    # -------------------------------------------------------------
    slide22 = prs.slides.add_slide(prs.slide_layouts[2])
    add_header_and_title(slide22, "MÔ HÌNH SINH PPG  ·  DÁNG SÓNG & ĐẶC TÍNH TRIỂN KHAI PI 4",
                         "So sánh hình thái sóng thực tế, phổ tần số và thời gian đáp ứng trên Pi 4",
                         pill_text="KHẢ THI TRIỂN KHAI", pill_color=RGBColor(240, 253, 244),
                         pill_border=RGBColor(34, 197, 94), pill_txt_color=RGBColor(21, 128, 61))
    
    slide22.shapes.add_picture('docs/figures_ppt/waveform_comparison.png', 548640, 1422400, 7400000, 4850000)

    wave_c1 = [
        "• Tái tạo trọn vẹn đỉnh tâm thu, vết khuyết dicrotic notch và đỉnh tâm trương phản xạ",
        "• Độ nhọn (kurtosis 0,950 vs thật 0,940) và độ dốc (diff skew 0,979 vs thật 0,948) đạt chuẩn sinh lý lâm sàng",
        "• Khắc phục hoàn toàn hiện tượng gãy sóng và nhiễu vi phân của GAN thuần thế hệ trước"
    ]
    add_card(slide22, 8150000, 1422400, 3500000, 2350000, "Chất lượng Hình thái sóng", wave_c1)

    wave_c2 = [
        "• KV-Cache giúp giảm thời gian sinh APFT từ 17,8 s → 7,6 s / 64 cửa sổ (x86 CPU). Ước tính 10–20 s trên Cortex-A72 Pi 4 cho 30 s output",
        "• Tận dụng luồng đệm đa tầng (sequence_worker.py), việc phát DAC hoàn toàn không bị trễ hay gián đoạn (0 mẫu bỏ)",
        "• PSF-GAN suy luận dạng feed-forward cực nhanh, tiềm năng tạo xung tức thời"
    ]
    add_card(slide22, 8150000, 3922400, 3500000, 2350000, "Khả thi thực thi trên Pi 4", wave_c2)
    print("Created Slide 22 (Waveform Morphology & Pi 4 Feasibility).")

    # -------------------------------------------------------------
    # Reorder slides into logical progression
    # -------------------------------------------------------------
    sldIdLst = prs.slides._sldIdLst
    
    id_s22 = sldIdLst[-1]
    id_s21 = sldIdLst[-2]
    id_s20 = sldIdLst[-3]

    # Remove the old slide 20
    old_slide20_id = sldIdLst[19]
    sldIdLst.remove(old_slide20_id)

    # Remove new slides from end and insert at indices 19, 20, 21
    sldIdLst.remove(id_s20)
    sldIdLst.remove(id_s21)
    sldIdLst.remove(id_s22)
    
    sldIdLst.insert(19, id_s20)
    sldIdLst.insert(20, id_s21)
    sldIdLst.insert(21, id_s22)

    # -------------------------------------------------------------
    # 7. Update Slide 23 (VẤN ĐỀ TỒN TẠI)
    # -------------------------------------------------------------
    slide23 = prs.slides[22]
    add_header_and_title(slide23, "VẤN ĐỀ TỒN TẠI", 
                         "Rủi ro kỹ thuật cần xử lý trước khi đánh giá nghiệm thu",
                         pill_text="CẦN XỬ LÝ", pill_color=RGBColor(254, 242, 242),
                         pill_border=RGBColor(239, 68, 68), pill_txt_color=RGBColor(185, 28, 28))
    
    w_col = 3500000
    h_col = 4800000
    top_col = 1422400
    
    hw_lines = [
        "• Đo đạc thực nghiệm với Oscilloscope:",
        "  - Kiểm chứng xung nhịp timer ghi DAC thực tế (500 Hz, chu kỳ 2 ms)",
        "  - Đo dòng phát thực tế qua LED Đỏ & Hồng ngoại và điện áp V_sense qua điện trở shunts",
        "• Hệ số tương quan quang học TX–RX:",
        "  - Cần tính toán lại sau khi hàn PCB panel và lắp đặt buồng tối hoàn chỉnh",
        "  - Cân chỉnh độ nhạy quang học cảm biến OPT101 để tránh bão hòa ánh sáng"
    ]
    add_card(slide23, 548640, top_col, w_col, h_col, "1. Phần cứng & Quang học", hw_lines)

    ble_lines = [
        "• Đo trễ lệnh và độ ổn định BLE:",
        "  - Đo đạc thực tế độ trễ lệnh (command latency) giữa ứng dụng Android và Raspberry Pi 4",
        "  - Thống kê tỉ lệ mất gói tin BLE trong điều kiện môi trường phòng thí nghiệm có nhiễu Wi-Fi",
        "• Kiểm tra tính ổn định:",
        "  - Duy trì kết nối liên tục khi quét và truyền chuỗi xung dài (> 10 phút)",
        "  - Hoàn thiện cơ chế tự động quét lại (auto-reconnect) khi tín hiệu gián đoạn"
    ]
    add_card(slide23, 4346000, top_col, w_col, h_col, "2. Truyền thông BLE & App", ble_lines)

    ai_lines = [
        "• Khoảng trống tần số cao mô hình sinh:",
        "  - Dải tần 5–8 Hz và sai phân bậc 2 chưa đạt tuyệt đối mốc V2 (cần nghiên cứu bổ sung loss phổ)",
        "  - Tiếp tục hoàn thiện huấn luyện PSF-GAN để kiểm chứng khóa nhịp tim thực tế",
        "• Đóng gói triển khai nhúng Pi 4:",
        "  - Chuyển đổi mô hình tối ưu sang TorchScript / ONNX Runtime",
        "  - Kiểm soát tài nguyên RAM và tải CPU khi chạy đồng thời GUI Tkinter, tiến trình BLE và worker sinh xung AI"
    ]
    add_card(slide23, 8143360, top_col, w_col, h_col, "3. Mô hình AI & Triển khai", ai_lines)
    print("Updated Slide 23 (Vấn đề tồn tại).")

    # -------------------------------------------------------------
    # 8. Update Slide Numbers across ALL slides
    # -------------------------------------------------------------
    total_slides = len(prs.slides)
    for idx, slide in enumerate(prs.slides):
        slide_num = idx + 1
        if slide_num == 1 or slide_num == total_slides:
            continue
        
        found = False
        for s in slide.shapes:
            if 'Slide Number' in s.name or 'slide_number' in s.name.lower():
                if s.has_text_frame:
                    s.text_frame.text = str(slide_num)
                    found = True
                    break
        if not found:
            tb = slide.shapes.add_textbox(11094415, 6419088, 548640, 256032)
            tb.name = "Slide Number Placeholder 0"
            p = tb.text_frame.paragraphs[0]
            p.text = str(slide_num)
            p.alignment = PP_ALIGN.RIGHT
            p.font.size = Pt(11)
            p.font.color.rgb = RGBColor(158, 158, 158)
    print("Updated all slide numbers.")

    prs.save(DST_PPTX)
    print(f"Successfully saved updated presentation to {DST_PPTX}!")

if __name__ == '__main__':
    main()
