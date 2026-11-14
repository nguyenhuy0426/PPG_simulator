"""Drag with the left button via XTEST: xdrag.py X1 Y1 X2 Y2 (root coordinates)"""
import ctypes, sys, time
x11 = ctypes.CDLL("libX11.so.6"); xt = ctypes.CDLL("libXtst.so.6")
x11.XOpenDisplay.restype = ctypes.c_void_p
dpy = ctypes.c_void_p(x11.XOpenDisplay(None))
x1, y1, x2, y2 = map(int, sys.argv[1:5])
def move(x, y): xt.XTestFakeMotionEvent(dpy, -1, x, y, 0); x11.XFlush(dpy)
move(x1, y1); time.sleep(.15)
xt.XTestFakeButtonEvent(dpy, 1, 1, 0); x11.XFlush(dpy); time.sleep(.05)
for k in range(1, 21):
    move(x1 + (x2 - x1) * k // 20, y1 + (y2 - y1) * k // 20); time.sleep(.02)
time.sleep(.05); xt.XTestFakeButtonEvent(dpy, 1, 0, 0); x11.XFlush(dpy)
x11.XCloseDisplay(dpy); print("dragged", x1, y1, "->", x2, y2)
