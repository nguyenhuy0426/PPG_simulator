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

def make_multi_beat(n_beats=4, n_samples=400, noise=0.02):
    sig = []
    beat = make_ppg_beat(100)
    for i in range(n_beats):
        b = beat.copy()
        b = b * (1.0 + (np.sin(i*1.5) * 0.1))
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

def create_psf_gan_diagram(out_path):
    fig = plt.figure(figsize=(14, 13), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    
    # Title Header
    ax.text(0.5, 0.965, "KIẾN TRÚC MÔ HÌNH PSF-GAN (PERIODIC SOURCE-FILTER GAN)", 
            ha='center', va='center', fontsize=18, fontweight='bold', color='#0D47A1')
    ax.text(0.5, 0.940, "Máy phát Nguồn - Lọc Điều hòa (Source-Filter) & Cụm Discriminator Đa chu kỳ (MPD / MSD / STFT)", 
            ha='center', va='center', fontsize=12, fontstyle='italic', color='#424242')

    c_gen_bg = '#FFF3E0'      # soft peach/orange
    c_gen_border = '#FB8C00'
    c_disc_bg = '#FFEBEE'     # soft coral/pink
    c_disc_border = '#E53935'
    c_loss_bg = '#EDE7F6'     # soft lavender/purple
    c_loss_border = '#8E24AA'
    c_aux_bg = '#FFFDE7'      # soft yellow/cream
    c_aux_border = '#FBC02D'

    # 1. Generator Box
    gen_box = FancyBboxPatch((0.18, 0.38), 0.46, 0.22,
                             boxstyle="round,pad=0.02,rounding_size=0.03",
                             facecolor=c_gen_bg, edgecolor=c_gen_border, linewidth=2.2, zorder=2)
    ax.add_patch(gen_box)
    
    ax.text(0.41, 0.565, "Generator (Source-Filter)", ha='center', va='center', 
            fontsize=16, fontweight='bold', color='#E65100', zorder=3)
    ax.text(0.41, 0.525, r"$\mathbf{Loss} = \mathcal{L}_{\mathrm{LSGAN}} + \lambda_{\mathrm{FM}} \cdot \mathcal{L}_{\mathrm{FM}} + \lambda_{\mathrm{feat}} \cdot \mathcal{L}_{\mathrm{feat}}$", 
            ha='center', va='center', fontsize=13, fontweight='bold', color='#BF360C', zorder=3)
    
    gen_details = (
        "• Nguồn kích thích (Source): Pha điều hòa $\phi(t) = \phi_0 + 2\pi\int(f_0 + \Delta f(t))dt$ (HRV $\pm 30\%$)\n"
        "  Các hài bậc cao: $[\sin(k\phi(t)), \cos(k\phi(t))]_{k=1}^4$ khóa nhịp tim chính xác theo thiết kế\n"
        "• Bộ lọc tạo dáng (Filter): 1D Conv đa tỉ lệ (7,22M param) điều biến đỉnh tâm thu & dicrotic notch\n"
        "• Hậu xử lý: Sinh 40 s $\\to$ Lọc Butterworth 0,5–8 Hz $\\to$ Cắt giữa 30 s (1200 mẫu) $\\to$ Min-Max [0, 1]"
    )
    ax.text(0.41, 0.445, gen_details, ha='center', va='center', fontsize=9.5, color='#37474F', zorder=3)

    # 2. Discriminator Box
    disc_box = FancyBboxPatch((0.74, 0.65), 0.23, 0.22,
                              boxstyle="round,pad=0.02,rounding_size=0.03",
                              facecolor=c_disc_bg, edgecolor=c_disc_border, linewidth=2.2, zorder=2)
    ax.add_patch(disc_box)
    ax.text(0.855, 0.835, "Discriminator Ensemble", ha='center', va='center', 
            fontsize=14, fontweight='bold', color='#B71C1C', zorder=3)
    disc_details = (
        "Cụm 3 Bộ phân biệt (4,51M param):\n"
        "• MPD (Multi-Period): 5 mạng\n"
        "  chu kỳ nguyên tố (p=2, 3, 5, 7, 11)\n"
        "• MSD (Multi-Scale): 3 thang tỉ lệ\n"
        "  thời gian ($1\\times, 2\\times, 4\\times$)\n"
        "• Log-STFT Critic: Phổ biên độ T-F\n"
        "• Chiếu điều kiện nhịp tim ($f_0$)"
    )
    ax.text(0.855, 0.735, disc_details, ha='center', va='center', fontsize=9.2, color='#263238', zorder=3)

    # 3. Loss Boxes
    loss_lsgan_box = FancyBboxPatch((0.74, 0.46), 0.23, 0.08,
                                    boxstyle="round,pad=0.015,rounding_size=0.02",
                                    facecolor=c_loss_bg, edgecolor=c_loss_border, linewidth=1.8, zorder=2)
    ax.add_patch(loss_lsgan_box)
    ax.text(0.855, 0.515, "LSGAN Loss (Least Squares)", ha='center', va='center', 
            fontsize=11.5, fontweight='bold', color='#4A148C', zorder=3)
    ax.text(0.855, 0.480, r"$\mathbb{E}[(D(G(z)) - 1)^2]$", ha='center', va='center', 
            fontsize=10.5, color='#4A148C', zorder=3)

    loss_fm_box = FancyBboxPatch((0.18, 0.72), 0.19, 0.09,
                                 boxstyle="round,pad=0.015,rounding_size=0.02",
                                 facecolor=c_loss_bg, edgecolor=c_loss_border, linewidth=1.8, zorder=2)
    ax.add_patch(loss_fm_box)
    ax.text(0.275, 0.778, "Feature Matching Loss", ha='center', va='center', 
            fontsize=11.5, fontweight='bold', color='#4A148C', zorder=3)
    ax.text(0.275, 0.742, r"$\sum_l \frac{1}{N_l} \|D^{(l)}(x) - D^{(l)}(G(z))\|_1$", 
            ha='center', va='center', fontsize=10, color='#4A148C', zorder=3)

    loss_feat_box = FancyBboxPatch((0.28, 0.28), 0.26, 0.065,
                                   boxstyle="round,pad=0.015,rounding_size=0.02",
                                   facecolor=c_loss_bg, edgecolor=c_loss_border, linewidth=1.8, zorder=2)
    ax.add_patch(loss_feat_box)
    ax.text(0.41, 0.323, "22-Feature Wasserstein Loss", ha='center', va='center', 
            fontsize=11, fontweight='bold', color='#4A148C', zorder=3)
    ax.text(0.41, 0.297, r"$\mathcal{L}_{\mathrm{feat}} = \sum_{i=1}^{22} \mathcal{W}_1(\Phi_i(x), \Phi_i(G(z)))$", 
            ha='center', va='center', fontsize=9.5, color='#4A148C', zorder=3)

    # 4. Waveforms
    real_ppg = make_multi_beat(n_beats=4, n_samples=300, noise=0.01)
    draw_waveform_box(ax, 0.47, 0.75, 0.16, 0.12, real_ppg, "Real PPG signal (MIMIC-III)", color='#0288D1')
    
    syn_ppg = make_multi_beat(n_beats=4, n_samples=300, noise=0.015)
    draw_waveform_box(ax, 0.47, 0.61, 0.16, 0.10, syn_ppg, "Synthetic PPG signal", color='#00897B')

    noise_data = np.random.normal(0, 1, 200)
    draw_waveform_box(ax, 0.02, 0.44, 0.12, 0.10, noise_data, "Noise $z$ + Nhịp $f_0$", color='#5C6BC0')

    draw_waveform_box(ax, 0.29, 0.05, 0.11, 0.08, real_ppg[:150], "Real signal", color='#0288D1')
    draw_waveform_box(ax, 0.52, 0.05, 0.11, 0.08, syn_ppg[:150], "Synthetic signal", color='#00897B')

    ac_real_box = FancyBboxPatch((0.29, 0.16), 0.11, 0.038,
                                 boxstyle="round,pad=0.01,rounding_size=0.01",
                                 facecolor=c_aux_bg, edgecolor=c_aux_border, linewidth=1.5, zorder=2)
    ax.add_patch(ac_real_box)
    ax.text(0.345, 0.179, "Auto-correlation", ha='center', va='center', fontsize=9.5, fontweight='bold', color='#795548')

    ac_syn_box = FancyBboxPatch((0.52, 0.16), 0.11, 0.038,
                                boxstyle="round,pad=0.01,rounding_size=0.01",
                                facecolor=c_aux_bg, edgecolor=c_aux_border, linewidth=1.5, zorder=2)
    ax.add_patch(ac_syn_box)
    ax.text(0.575, 0.179, "Auto-correlation", ha='center', va='center', fontsize=9.5, fontweight='bold', color='#795548')

    mmd_box = FancyBboxPatch((0.36, 0.22), 0.18, 0.038,
                             boxstyle="round,pad=0.01,rounding_size=0.01",
                             facecolor='#EDE7F6', edgecolor='#8E24AA', linewidth=1.5, zorder=2)
    ax.add_patch(mmd_box)
    ax.text(0.45, 0.239, "ACF MMD Distance", ha='center', va='center', fontsize=10, fontweight='bold', color='#4A148C')

    # 5. Arrows
    arrow_style = "Simple,tail_width=1.5,head_width=6,head_length=7"
    
    a1 = FancyArrowPatch((0.145, 0.49), (0.18, 0.49), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a1)
    a2 = FancyArrowPatch((0.44, 0.60), (0.47, 0.64), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a2)
    a3 = FancyArrowPatch((0.635, 0.81), (0.74, 0.79), arrowstyle=arrow_style, color='#212121')
    ax.add_patch(a3)
    a4 = FancyArrowPatch((0.635, 0.66), (0.74, 0.71), arrowstyle=arrow_style, color='#212121')
    ax.add_patch(a4)
    a5 = FancyArrowPatch((0.47, 0.81), (0.37, 0.78), arrowstyle=arrow_style, color='#616161')
    ax.add_patch(a5)
    a6 = FancyArrowPatch((0.47, 0.68), (0.37, 0.74), arrowstyle=arrow_style, color='#616161')
    ax.add_patch(a6)
    a7 = FancyArrowPatch((0.275, 0.72), (0.275, 0.60), arrowstyle=arrow_style, color='#8E24AA')
    ax.add_patch(a7)

    a8 = FancyArrowPatch((0.855, 0.65), (0.855, 0.54), arrowstyle=arrow_style, color='#212121')
    ax.add_patch(a8)
    ax.text(0.865, 0.595, "Real or Fake?", ha='left', va='center', fontsize=10.5, fontweight='bold', color='#C62828')

    a9 = FancyArrowPatch((0.74, 0.50), (0.64, 0.50), arrowstyle=arrow_style, color='#8E24AA')
    ax.add_patch(a9)

    a10 = FancyArrowPatch((0.345, 0.13), (0.345, 0.16), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a10)
    a11 = FancyArrowPatch((0.575, 0.13), (0.575, 0.16), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a11)

    a12 = FancyArrowPatch((0.37, 0.198), (0.42, 0.22), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a12)
    a13 = FancyArrowPatch((0.54, 0.198), (0.48, 0.22), arrowstyle=arrow_style, color='#424242')
    ax.add_patch(a13)

    a14 = FancyArrowPatch((0.45, 0.258), (0.43, 0.28), arrowstyle=arrow_style, color='#8E24AA')
    ax.add_patch(a14)
    a15 = FancyArrowPatch((0.41, 0.345), (0.41, 0.38), arrowstyle=arrow_style, color='#8E24AA')
    ax.add_patch(a15)

    fig.savefig(out_path, dpi=300, facecolor='white', bbox_inches='tight')
    plt.close(fig)
    print(f"Saved PSF-GAN diagram to {out_path}")

if __name__ == '__main__':
    create_psf_gan_diagram('docs/figures_ppt/arch_psf_gan.png')
