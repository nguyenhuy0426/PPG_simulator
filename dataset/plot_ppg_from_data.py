#!/usr/bin/env python3
"""
plot_ppg_from_csv.py

Đọc file data_2.csv, chuyển raw 12-bit sang điện áp (0-3.3V),
vẽ đồ thị IR và Red, hỗ trợ zoom chuột để xem chi tiết AC.

Cách dùng:
    python plot_ppg_from_csv.py data_2.csv
"""

import sys
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.widgets import RectangleSelector
import numpy as np

# --- Tham số chuyển đổi ---
DAC_MAX = 4095      # 12-bit
V_REF = 3.3         # 3.3V

def raw_to_voltage(raw):
    return raw / DAC_MAX * V_REF

def on_zoom(eclick, erelease):
    """Callback khi người dùng kéo chọn vùng zoom."""
    x1, y1 = eclick.xdata, eclick.ydata
    x2, y2 = erelease.xdata, erelease.ydata
    if x1 is None or x2 is None:
        return
    ax.set_xlim(min(x1, x2), max(x1, x2))
    ax.set_ylim(min(y1, y2), max(y1, y2))
    fig.canvas.draw_idle()

def on_double_click(event):
    """Nhấn đúp chuột để reset về toàn bộ dữ liệu."""
    if event.dblclick:
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        fig.canvas.draw_idle()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python plot_ppg_from_csv.py data_2.csv")
        sys.exit(1)

    csv_file = sys.argv[1]
    df = pd.read_csv(csv_file)

    # Kiểm tra các cột cần thiết
    if 'IR_Raw' not in df.columns or 'RED_Raw' not in df.columns:
        print("CSV thiếu cột IR_Raw hoặc RED_Raw")
        sys.exit(1)

    # Chuyển đổi sang điện áp
    ir_voltage = raw_to_voltage(df['IR_Raw'].values)
    red_voltage = raw_to_voltage(df['RED_Raw'].values)

    # Trục thời gian: giả sử tần số lấy mẫu là 1 kHz (mỗi mẫu cách 1 ms)
    # Nếu file ghi với tốc độ khác, bạn có thể điều chỉnh dt bên dưới
    dt = 0.001  # 1 ms -> 1 kHz
    time = np.arange(len(ir_voltage)) * dt

    # Vẽ đồ thị
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(time, ir_voltage, label='IR (Voltage)', linewidth=0.8, color='red')
    ax.plot(time, red_voltage, label='Red (Voltage)', linewidth=0.8, color='blue')
    ax.set_xlabel('Thời gian (s)')
    ax.set_ylabel('Điện áp (V)')
    ax.set_title(f'PPG Signal từ {csv_file}\nTần số giả định = 1 kHz (1 mẫu/ms)')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Lưu giới hạn ban đầu để reset khi double-click
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()

    # Gắn công cụ zoom (RectangleSelector)
    rs = RectangleSelector(ax, on_zoom,
                           useblit=True,
                           button=[1],  # chuột trái
                           minspanx=5, minspany=5,
                           spancoords='pixels',
                           interactive=True)

    # Gắn double-click để reset
    fig.canvas.mpl_connect('button_press_event', on_double_click)

    plt.tight_layout()
    plt.show()