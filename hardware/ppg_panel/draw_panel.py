#!/usr/bin/env python3
"""Manufacturing drawing: dimensions are millimetres, not print scale."""
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
HERE = Path(__file__).resolve().parent
fig, ax = plt.subplots(figsize=(8.27, 11.69))
for top, height, title, color in [(0,30,"OPT101 RX v1.3", "#e0f2fe"),(30,30,"BPW34 RX v1.3", "#dcfce7"),(60,50,"LED / IR driver v1.7", "#fef3c7")]:
    ax.add_patch(Rectangle((0,top),70,height,facecolor=color,edgecolor="#334155",lw=1))
    ax.text(35,top+height/2,title+f"\n70 x {height} mm",ha="center",va="center",fontsize=13)
for y in (30,60):
    ax.plot([-3,73],[y,y],color="#dc2626",ls="--",lw=1.5)
    ax.text(76,y,f"V-SCORE\nY = {y} mm",va="center",fontsize=9,color="#b91c1c")
ax.annotate("",(0,-7),(70,-7),arrowprops=dict(arrowstyle="<->"))
ax.text(35,-9,"70 mm",ha="center")
ax.annotate("",(-8,0),(-8,110),arrowprops=dict(arrowstyle="<->"))
ax.text(-11,55,"110 mm",ha="center",va="center",rotation=90)
ax.text(0,-18,"DATN: PPG-Simulator | V-cut panel",fontsize=17,weight="bold")
ax.text(0,-13,"TOP VIEW - 3 DIFFERENT DESIGNS / 1 COPY EACH",fontsize=9)
notes = ["FR-4 1.6 mm | 2 copper layers | 1 oz copper | mask + silk both sides",
"2 full-width V-score centre-lines: Y = 30 mm and 60 mm from top edge.",
"Score BOTH sides. Factory selects depth / remaining web for 1.6 mm FR-4.",
"User_Comments Gerber = V-SCORE guide. Do NOT mill these into slots.",
"Edge_Cuts Gerber = outer 70 x 110 mm rectangle only. Zero routing gap.",
"Copper-to-score centre clearance >= 0.60 mm on EACH side.",
"No electrical connections cross a score. Depanel BEFORE assembly.",
"CAD origin (50,50) mm: score lines are at absolute Y=80 and Y=110 mm.",
"Factory to confirm scoring capability, tolerances and 3-design panel pricing.",
"Dimensions govern. Drawing NOT TO SCALE. See README and drill files."]
for i,line in enumerate(notes): ax.text(0,119+i*4.4,line,fontsize=8.2,va="top")
ax.set_xlim(-17,105);ax.set_ylim(167,-24);ax.set_aspect("equal");ax.axis("off")
fig.tight_layout()
for ext in ("pdf","png","svg"):fig.savefig(HERE / f"reports/vcut_drawing.{ext}",dpi=180)
plt.close(fig)
