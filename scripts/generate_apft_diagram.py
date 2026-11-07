import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

def make_ppg_beat(n_samples=200):
    t = np.linspace(0, 1, n_samples)
    w1 = 1.0 * np.exp(-((t - 0.22) / 0.08)**2)
    w2 = 0.45 * np.exp(-((t - 0.42) / 0.09)**2)
    w3 = 0.25 * np.exp(-((t - 0.33) / 0.04)**2)
    sig = w1 + w2 - 0.15 * w3
    sig = sig - np.min(sig)
    sig = sig / np.max(sig)
    return sig

def make_multi_beat(n_beats=4, n_samples=400, noise=0.015):
    sig = []
    beat = make_ppg_beat(100)
    for i in range(n_beats):
        b = beat.copy()
        b = b * (1.0 + (np.sin(i*1.3) * 0.08))
        sig.extend(b)
    sig = np.array(sig)
    if noise > 0:
        sig += np.random.normal(0, noise, len(sig))
    sig = (sig - np.min(sig)) / (np.max(sig) - np.min(sig))
    return sig

def draw_waveform_box(ax, x, y, w, h, data, title, color='#0288D1'):
    sub_ax = ax.figure.add_axes([x, y, w, h])
    sub_ax.plot(data, color=color, lw=1.2)
    sub_ax.set_facecolor('#FAFAFA')
    sub_ax.grid(True, color='#E0E0E0', linestyle='--', linewidth=0.5)
    sub_ax.set_xticks([])
    sub_ax.set_yticks([])
    for spine in sub_ax.spines.values():
        spine.set_color('#BDBDBD')
        spine.set_linewidth(0.8)
    ax.text(x + w/2, y + h + 0.012, title, ha='center', va='bottom', 
            fontsize=10.5, fontweight='bold', color='#212121')

def create_apft_diagram(out_path):
    fig = plt.figure(figsize=(14, 13), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Title Header
    ax.text(0.5, 0.965, "KIẾN TRÚC MÔ HÌNH APFT (PPG-PHYSIGPT / APFT-GAN v3)", 
            ha='center', va='center', fontsize=18, fontweight='bold', color='#0D47A1')
    ax.text(0.5, 0.940, "Autoregressive Patch Flow Transformer & Tinh chỉnh Đối nghịch Cục bộ (Head-Only GAN)", 
            ha='center', va='center', fontsize=12, fontstyle='italic', color='#424242')

    c_gen_bg = '#FFF3E0'      # soft peach/orange
    c_gen_border = '#FB8C00'
    c_disc_bg = '#FFEBEE'     # soft coral/pink
    c_disc_border = '#E53935'
    c_loss_bg = '#EDE7F6'     # soft lavender/purple
    c_loss_border = '#8E24AA'
    c_aux_bg = '#E8F5E9'      # soft green
    c_aux_border = '#43A047'

    # 1. Generator Box (APFT-L Backbone + Flow Head)
    gen_box = FancyBboxPatch((0.18, 0.36), 0.47, 0.25,
                             boxstyle="round,pad=0.02,rounding_size=0.03",
                             facecolor=c_gen_bg, edgecolor=c_gen_border, linewidth=2.2, zorder=2)
    ax.add_patch(gen_box)
    
    ax.text(0.415, 0.585, "Generator (APFT Large Backbone + Flow Head)", ha='center', va='center', 
            fontsize=15, fontweight='bold', color='#E65100', zorder=3)
    ax.text(0.415, 0.548, r"$\mathbf{Loss} = \mathcal{L}_{\mathrm{flow\text{-}anchor}} + \lambda_{\mathrm{adv}} \cdot \mathcal{L}_{\mathrm{adv}} + \lambda_{\mathrm{feat}} \cdot \mathcal{L}_{\mathrm{feat}}$", 
            ha='center', va='center', fontsize=12.5, fontweight='bold', color='#BF360C', zorder=3)
    
    gen_details = (
        "• Patch Division: Cửa sổ 30 s @ 40 Hz (1200 mẫu) chia thành 30 patch liên tiếp (40 mẫu/patch)\n"
        "• Causal Transformer Backbone: 99,9M tham số, dim 768, 12 layers, RoPE, SwiGLU, RMSNorm\n"
        "  Cơ chế KV-Cache tăng tốc suy luận: giảm thời gian sinh từ 17,8 s $\\to$ 7,6 s / 64 cửa sổ\n"
        "• Flow-Matching Head (adaLN-MLP): Dự đoán trường vector vận tốc vi phân $v_\\theta(x_t, t | h_{\\mathrm{HR}}, x_{<k})$\n"
        "• Heun ODE Solver: Tích phân số 16/32 bước Heun sinh tuần tự từng patch theo quy luật dòng\n"
        "• Cơ chế v3: Gradient đối nghịch $\\mathcal{L}_{\\mathrm{adv}}$ chỉ vào Flow Head; Backbone được neo giữ bởi Flow Anchor"
    )
    ax.text(0.415, 0.445, gen_details, ha='center', va='center', fontsize=9.2, color='#37474F', zorder=3)

    # 2. Discriminator Box (Strict Multi-Branch Critic)
    disc_box = FancyBboxPatch((0.74, 0.65), 0.23, 0.23,
                              boxstyle="round,pad=0.02,rounding_size=0.03",
                              facecolor=c_disc_bg, edgecolor=c_disc_border, linewidth=2.2, zorder=2)
    ax.add_patch(disc_box)
    ax.text(0.855, 0.845, "Strict Multi-Branch Critic", ha='center', va='center', 
            fontsize=14, fontweight='bold', color='#B71C1C', zorder=3)
    disc_details = (
        "Cụm 3 Nhánh Phân tích (3,6M param):\n"
        "• Time Branch: 1D CNN bắt\n"
        "  hình thái dốc và khuyết dicrotic\n"
        "• Spectral Branch: Log-STFT\n"
        "  so sánh phổ tần số 0,5–8 Hz\n"
        "• ACF Branch: Tự tương quan\n"
        "  chấm độ tuần hoàn nhịp tim\n"
        "• Phép chiếu điều kiện nhịp tim ($f_0$)"
    )
    ax.text(0.855, 0.740, disc_details, ha='center', va='center', fontsize=9.2, color='#263238', zorder=3)

    # 3. Loss Boxes
    # Adversarial Loss Box
    loss_adv_box = FancyBboxPatch((0.74, 0.46), 0.23, 0.08,
                                   boxstyle="round,pad=0.015,rounding_size=0.02",
                                   facecolor=c_loss_bg, edgecolor=c_loss_border, linewidth=1.8, zorder=2)
    ax.add_patch(loss_adv_box)
    ax.text(0.855, 0.515, "Adversarial Loss (Head-Only)", ha='center', va='center', 
            fontsize=11.5, fontweight='bold', color='#4A148C', zorder=3)
    ax.text(0.855, 0.480, r"$\mathcal{L}_{\mathrm{adv}} = \mathbb{E}[\max(0, 1 - D(x_{\mathrm{syn}}))]$", 
            ha='center', va='center', fontsize=9.8, color='#4A148C', zorder=3)

    # Flow Anchor Loss Box (Top left above Generator)
    loss_flow_box = FancyBboxPatch((0.18, 0.73), 0.22, 0.09,
                                   boxstyle="round,pad=0.015,rounding_size=0.02",
                                   facecolor=c_loss_bg, edgecolor=c_loss_border, linewidth=1.8, zorder=2)
    ax.add_patch(loss_flow_box)
    ax.text(0.29, 0.785, "Logit-Laplace Flow Anchor", ha='center', va='center', 
            fontsize=11.5, fontweight='bold', color='#4A148C', zorder=3)
    ax.text(0.29, 0.750, r"$\mathbb{E}_{t, x_0, x_1} \|v_\theta(x_t, t) - (x_1 - x_0)\|^2$", 
            ha='center', va='center', fontsize=10, color='#4A148C', zorder=3)

    # 22-Feature Wasserstein Loss Box
    loss_feat_box = FancyBboxPatch((0.28, 0.25), 0.27, 0.07,
                                   boxstyle="round,pad=0.015,rounding_size=0.02",
                                   facecolor=c_loss_bg, edgecolor=c_loss_border, linewidth=1.8, zorder=2)
    ax.add_patch(loss_feat_box)
    ax.text(0.415, 0.298, "22-Feature Wasserstein Loss", ha='center', va='center', 
            fontsize=11, fontweight='bold', color='#4A148C', zorder=3)
    ax.text(0.415, 0.268, r"$\mathcal{L}_{\mathrm{feat}} = \sum_{i=1}^{22} \mathcal{W}_1(\Phi_i(x_{\mathrm{real}}), \Phi_i(x_{\mathrm{syn}}))$", 
            ha='center', va='center', fontsize=9.5, color='#4A148C', zorder=3)

    # 4. Waveforms
    real_ppg = make_multi_beat(n_beats=4, n_samples=300, noise=0.01)
    draw_waveform_box(ax, 0.48, 0.75, 0.16, 0.12, real_ppg, "Real PPG signal (MIMIC-III)", color='#0288D1')
    
    syn_ppg = make_multi_beat(n_beats=4, n_samples=300, noise=0.012)
    draw_waveform_box(ax, 0.48, 0.61, 0.16, 0.10, syn_ppg, "Synthetic PPG signal (APFT)", color='#00897B')

    # Condition & Patch input
    noise_data = np.random.normal(0, 1, 200)
    draw_waveform_box(ax, 0.02, 0.43, 0.12, 0.10, noise_data, "Noise $x_1$ + Điều kiện $f_0$", color='#5C6BC0')

    # Waveform thumbnails at bottom for 22 features
    draw_waveform_box(ax, 0.29, 0.05, 0.11, 0.08, real_ppg[:150], "Real Features $\Phi(x)$", color='#0288D1')
    draw_waveform_box(ax, 0.53, 0.05, 0.11, 0.08, syn_ppg[:150], "Syn Features $\Phi(G)$", color='#00897B')

    # 1D Wasserstein distance block
    w1_box = FancyBboxPatch((0.37, 0.17), 0.19, 0.04,
                            boxstyle="round,pad=0.01,rounding_size=0.01",
                            facecolor=c_aux_bg, edgecolor=c_aux_border, linewidth=1.5, zorder=2)
    ax.add_patch(w1_box)
    ax.text(0.465, 0.190, "1-D Wasserstein Distance", ha='center', va='center', fontsize=10, fontweight='bold', color='#1B5E20')

    # 5. Connecting Arrows
    arrow_style = "Simple,tail_width=1.5,head_width=6,head_length=7"
    
    # Input -> Generator
    a1 = FancyArrowPatch((0.145, 0.48), (0.18, 0.48), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a1)

    # Generator -> Synthetic PPG
    a2 = FancyArrowPatch((0.45, 0.61), (0.48, 0.64), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a2)

    # Real PPG -> Discriminator
    a3 = FancyArrowPatch((0.645, 0.81), (0.74, 0.79), arrowstyle=arrow_style, color='#212121')
    ax.add_patch(a3)

    # Synthetic PPG -> Discriminator
    a4 = FancyArrowPatch((0.645, 0.66), (0.74, 0.71), arrowstyle=arrow_style, color='#212121')
    ax.add_patch(a4)

    # Real PPG -> Flow Loss
    a5 = FancyArrowPatch((0.48, 0.81), (0.40, 0.78), arrowstyle=arrow_style, color='#616161')
    ax.add_patch(a5)

    # Flow Loss -> Generator
    a7 = FancyArrowPatch((0.29, 0.73), (0.29, 0.61), arrowstyle=arrow_style, color='#8E24AA')
    ax.add_patch(a7)

    # Discriminator -> Real or Fake? -> Adversarial Loss
    a8 = FancyArrowPatch((0.855, 0.65), (0.855, 0.54), arrowstyle=arrow_style, color='#212121')
    ax.add_patch(a8)
    ax.text(0.865, 0.595, "Real or Fake?", ha='left', va='center', fontsize=10.5, fontweight='bold', color='#C62828')

    # Adversarial Loss -> Generator (Head Only)
    a9 = FancyArrowPatch((0.74, 0.50), (0.65, 0.50), arrowstyle=arrow_style, color='#8E24AA')
    ax.add_patch(a9)

    # Feature extraction arrows
    a10 = FancyArrowPatch((0.345, 0.13), (0.345, 0.165), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a10)
    a11 = FancyArrowPatch((0.585, 0.13), (0.585, 0.165), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a11)

    # W1 to Feature Loss Box
    a12 = FancyArrowPatch((0.465, 0.21), (0.465, 0.25), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a12)

    # Feature Loss -> Generator
    a13 = FancyArrowPatch((0.415, 0.32), (0.415, 0.36), arrowstyle=arrow_style, color='#8E24AA')
    ax.add_patch(a13)

    fig.savefig(out_path, dpi=300, facecolor='white', bbox_inches='tight')
    plt.close(fig)
    print(f"Saved APFT diagram to {out_path}")

if __name__ == '__main__':
    create_apft_diagram('docs/figures_ppt/arch_apft.png')
