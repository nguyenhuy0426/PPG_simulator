"""
pygame_display.py — Full-screen Pygame GUI for PPG Signal Simulator.

Responsive display that auto-adapts to any screen resolution.
Features:
  - Overlaid dual waveform: IR (green) and Red (red-orange) on single panel
  - Sweep-line rendering with combined auto-scaling
  - Time axis with second markers (0s, 1s, 2s, 3s, 4s, 5s)
  - Header: HR, PI, SpO2, RR, condition name (proportionally spaced)
  - Footer: edit mode / condition selector
  - Channel amplitude legend (IR: xx.x mV, Red: xx.x mV)
  - Grid lines, smooth rendering, dark theme
  - Proportional font scaling for all screen sizes
"""

import pygame
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_FULLSCREEN, DISPLAY_FPS,
    WAVEFORM_DISPLAY_DURATION, WAVEFORM_UPDATE_MS,
    COLOR_BG, COLOR_WAVEFORM_IR, COLOR_WAVEFORM_RED, COLOR_GRID,
    COLOR_HEADER_BG, COLOR_FOOTER_BG, COLOR_TEXT, COLOR_TEXT_VALUE,
    COLOR_TEXT_LABEL, COLOR_HIGHLIGHT, COLOR_ACCENT, COLOR_SEPARATOR,
    COLOR_TIME_AXIS,
    DEVICE_NAME, FIRMWARE_VERSION,
    compute_layout,
)
from comm.logger import log


class PygameDisplay:
    """Full-screen Pygame GUI for the PPG Signal Simulator.

    Auto-detects screen resolution and adapts layout proportionally.
    Supports any screen size from 7" (1024×600) to 27" (2560×1440+).
    """

    def __init__(self):
        self.screen = None
        self.clock = None
        self.running = False

        # Layout (computed at runtime)
        self._layout = None
        self._screen_w = 0
        self._screen_h = 0

        # Fonts
        self.font_header = None
        self.font_value = None
        self.font_footer = None
        self.font_label = None
        self.font_small = None

        # Sweep state (unified for both channels)
        self._sweep_x = 0
        self._prev_y_ir = 0
        self._prev_y_red = 0
        self._first_point = True
        self._last_draw_time = 0       # Wall-clock time of last draw call
        self._last_ir = 0.0            # Previous IR sample for interpolation
        self._last_red = 0.0           # Previous Red sample for interpolation

        # Auto-scaling (combined range for both channels)
        self._sweep_min = 9999.0
        self._sweep_max = -9999.0
        self._disp_min = -20.0
        self._disp_max = 150.0

        # Amplitude tracking for legend
        self._peak_ir = 0.0
        self._peak_red = 0.0
        self._cycle_peak_ir = 0.0
        self._cycle_peak_red = 0.0
        self._last_beat_count = 0

        # Cached metrics
        self._cached_hr = -1
        self._cached_pi = -1
        self._cached_spo2 = -1
        self._cached_rr = -1
        self._cached_condition = ""

        # Waveform surface (single combined panel)
        self._waveform_surface = None

    def begin(self) -> bool:
        """Initialize Pygame, auto-detect resolution, and create the display."""
        pygame.init()
        pygame.display.set_caption(f"{DEVICE_NAME} v{FIRMWARE_VERSION}")

        # Auto-detect screen resolution
        if DISPLAY_WIDTH > 0 and DISPLAY_HEIGHT > 0:
            screen_w, screen_h = DISPLAY_WIDTH, DISPLAY_HEIGHT
        else:
            info = pygame.display.Info()
            screen_w = info.current_w
            screen_h = info.current_h

        self._screen_w = screen_w
        self._screen_h = screen_h

        # Compute layout
        self._layout = compute_layout(screen_w, screen_h)
        L = self._layout

        # Create display
        flags = 0
        if DISPLAY_FULLSCREEN:
            flags = pygame.FULLSCREEN

        try:
            self.screen = pygame.display.set_mode((screen_w, screen_h), flags)
        except pygame.error:
            log.warning("Fullscreen failed, using windowed mode")
            self.screen = pygame.display.set_mode((screen_w, screen_h))

        self.clock = pygame.time.Clock()

        # Load fonts (scaled proportionally)
        try:
            self.font_header = pygame.font.SysFont("dejavusans", L["font_header"], bold=True)
            self.font_value = pygame.font.SysFont("dejavusans", L["font_value"], bold=True)
            self.font_footer = pygame.font.SysFont("dejavusans", L["font_footer"])
            self.font_label = pygame.font.SysFont("dejavusans", L["font_label"])
            self.font_small = pygame.font.SysFont("dejavusans", L["font_small"])
        except Exception:
            self.font_header = pygame.font.Font(None, L["font_header"])
            self.font_value = pygame.font.Font(None, L["font_value"])
            self.font_footer = pygame.font.Font(None, L["font_footer"])
            self.font_label = pygame.font.Font(None, L["font_label"])
            self.font_small = pygame.font.Font(None, L["font_small"])

        # Create waveform surface (single panel for both IR + Red)
        self._waveform_surface = pygame.Surface((L["waveform_w"], L["waveform_h"]))
        self._waveform_surface.fill(COLOR_BG)

        # Initialize sweep state
        self._sweep_x = 0
        self._prev_y_ir = L["waveform_h"] // 2
        self._prev_y_red = L["waveform_h"] // 2
        self._first_point = True

        # Draw initial layout
        self.screen.fill(COLOR_BG)
        self._draw_layout()
        pygame.display.flip()

        self.running = True
        log.info(f"[Display] Pygame initialized: {screen_w}×{screen_h} "
                 f"(header={L['header_h']}px, waveform={L['waveform_h']}px, "
                 f"footer={L['footer_h']}px, font_scale={L['font_scale']:.2f})")
        return True

    # ─────────────────────── LAYOUT ───────────────────────
    def _draw_layout(self):
        """Draw the initial screen layout."""
        L = self._layout
        self._draw_header_bg()
        self._draw_footer_bg()
        self._draw_grid(self._waveform_surface, L["waveform_h"], L["waveform_w"])
        self.screen.blit(self._waveform_surface, (0, L["waveform_y"]))
        self._draw_time_axis_overlay()
        # Channel labels
        self._draw_channel_labels()

    def _draw_header_bg(self):
        L = self._layout
        pygame.draw.rect(self.screen, COLOR_HEADER_BG,
                         (0, 0, L["screen_w"], L["header_h"]))
        pygame.draw.line(self.screen, COLOR_SEPARATOR,
                         (0, L["header_h"] - 1), (L["screen_w"], L["header_h"] - 1), 1)

    def _draw_footer_bg(self):
        L = self._layout
        y = L["screen_h"] - L["footer_h"]
        pygame.draw.rect(self.screen, COLOR_FOOTER_BG,
                         (0, y, L["screen_w"], L["footer_h"]))
        pygame.draw.line(self.screen, COLOR_SEPARATOR,
                         (0, y), (L["screen_w"], y), 1)

    def _draw_grid(self, surface, height, width):
        """Draw grid lines on the waveform surface."""
        mid_y = height // 2
        # Center line (baseline)
        pygame.draw.line(surface, COLOR_GRID, (0, mid_y), (width, mid_y), 1)
        # Quarter lines (dotted)
        q1 = height // 4
        q3 = 3 * height // 4
        for x in range(0, width, 6):
            surface.set_at((x, q1), COLOR_GRID)
            surface.set_at((x, q3), COLOR_GRID)
        # Vertical grid lines — one per second (based on display duration)
        px_per_sec = width / WAVEFORM_DISPLAY_DURATION
        for i in range(1, int(WAVEFORM_DISPLAY_DURATION) + 1):
            gx = int(i * px_per_sec)
            if gx < width:
                for y in range(0, height, 4):
                    if gx < width:
                        surface.set_at((gx, y), COLOR_GRID)

    def _draw_time_axis_overlay(self):
        """Draw time axis labels dynamically over the waveform area so they aren't erased."""
        L = self._layout
        width = L["waveform_w"]
        height = L["waveform_h"]
        offset_y = L["waveform_y"]
        
        px_per_sec = width / WAVEFORM_DISPLAY_DURATION
        # Small font for time labels
        try:
            time_font = pygame.font.SysFont("dejavusans", max(10, L["font_small"] - 2))
        except Exception:
            time_font = pygame.font.Font(None, max(10, L["font_small"] - 2))

        for i in range(int(WAVEFORM_DISPLAY_DURATION) + 1):
            gx = int(i * px_per_sec)
            if gx >= width:
                gx = width - 1
            # Tick mark
            pygame.draw.line(self.screen, COLOR_TIME_AXIS, 
                             (gx, offset_y + height - 10), (gx, offset_y + height - 1), 1)
            # Label
            lbl = time_font.render(f"{i}s", True, COLOR_TIME_AXIS)
            lx = gx - lbl.get_width() // 2
            lx = max(2, min(width - lbl.get_width() - 2, lx))
            self.screen.blit(lbl, (lx, offset_y + height - 10 - lbl.get_height()))

    def _draw_channel_labels(self):
        """Draw IR/Red channel labels on the waveform area."""
        L = self._layout
        lbl_ir = self.font_small.render("IR", True, COLOR_WAVEFORM_IR)
        lbl_red = self.font_small.render("RED", True, COLOR_WAVEFORM_RED)
        x = L["waveform_w"] - max(lbl_ir.get_width(), lbl_red.get_width()) - 10
        self.screen.blit(lbl_ir, (x, L["waveform_y"] + 5))
        self.screen.blit(lbl_red, (x, L["waveform_y"] + 5 + lbl_ir.get_height() + 2))

    # ─────────────────────── WAVEFORM DRAWING ───────────────────────
    def draw_waveform_point(self, ac_ir: float, ac_red: float, current_beat_count: int = 0):
        """Draw waveform sample for both IR and Red on the overlaid display.

        Uses wall-clock time to compute how many pixels to advance,
        matching the HTML reference's approach.
        
        Updates the displayed peak amplitudes (mV) for each cycle based
        on current_beat_count from the PPG model.
        """
        import time as _time

        L = self._layout
        wh = L["waveform_h"]
        ww = L["waveform_w"]
        surface = self._waveform_surface

        # Calculate how many pixels to advance based on wall-clock time
        now = _time.time()
        if self._last_draw_time == 0:
            self._last_draw_time = now
            self._last_ir = ac_ir
            self._last_red = ac_red
            return

        wall_dt = min(now - self._last_draw_time, 0.05)  # Cap at 50ms like HTML
        self._last_draw_time = now

        # Update cycle peaks at the start of a new beat
        if current_beat_count != self._last_beat_count:
            # We have finished a beat, update the legend with the previous beat's peak
            if self._cycle_peak_ir > 0:
                self._peak_ir = self._cycle_peak_ir
                self._peak_red = self._cycle_peak_red
            # Reset for the new beat
            self._cycle_peak_ir = 0.0
            self._cycle_peak_red = 0.0
            self._last_beat_count = current_beat_count

        px_per_sec = ww / WAVEFORM_DISPLAY_DURATION  # e.g., 1920 / 15 = 128 px/s
        px_target = wall_dt * px_per_sec
        steps = max(1, round(px_target))

        # Interpolate between previous sample and current for smooth rendering
        prev_ir = self._last_ir
        prev_red = self._last_red

        for s in range(steps):
            t = (s + 1) / steps
            ir_val = prev_ir + (ac_ir - prev_ir) * t
            red_val = prev_red + (ac_red - prev_red) * t

            # Track combined min/max for auto-scaling
            if ir_val < self._sweep_min:
                self._sweep_min = ir_val
            if ir_val > self._sweep_max:
                self._sweep_max = ir_val

            # Track peak amplitudes for legend
            if abs(ir_val) > self._cycle_peak_ir:
                self._cycle_peak_ir = abs(ir_val)
            if abs(red_val) > self._cycle_peak_red:
                self._cycle_peak_red = abs(red_val)

            # Smoothly expand display scale if signal exceeds bounds during sweep
            # This prevents prolonged clipping when time axis is long (15s)
            val_max = max(ir_val, red_val)
            val_min = min(ir_val, red_val)
            if val_max > self._disp_max:
                self._disp_max += (val_max - self._disp_max) * 0.05
            if val_min < self._disp_min:
                self._disp_min -= (self._disp_min - val_min) * 0.05

            # Map to Y coordinates (shared scale)
            y_ir = self._map_to_y(ir_val, self._disp_min, self._disp_max, wh)
            y_red = self._map_to_y(red_val, self._disp_min, self._disp_max, wh)

            # Erase ahead (cursor effect) — matches HTML eraseW=4
            erase_w = 4
            ex = (self._sweep_x + 2) % ww
            if ex + erase_w <= ww:
                pygame.draw.rect(surface, COLOR_BG, (ex, 0, erase_w, wh))
            else:
                pygame.draw.rect(surface, COLOR_BG, (ex, 0, ww - ex, wh))
                pygame.draw.rect(surface, COLOR_BG, (0, 0, erase_w - (ww - ex), wh))

            # Sweep cursor line
            cx = (self._sweep_x + 1) % ww
            pygame.draw.line(surface, COLOR_GRID, (cx, 0), (cx, wh - 1), 1)

            # Draw waveform lines
            if self._first_point:
                surface.set_at((self._sweep_x % ww, y_ir), COLOR_WAVEFORM_IR)
                surface.set_at((self._sweep_x % ww, y_red), COLOR_WAVEFORM_RED)
                self._first_point = False
            else:
                px = (self._sweep_x - 1) % ww
                sx = self._sweep_x % ww
                # Draw Red first (behind, thinner), then IR on top (thicker)
                pygame.draw.line(surface, COLOR_WAVEFORM_RED,
                                 (px, self._prev_y_red), (sx, y_red), 1)
                pygame.draw.line(surface, COLOR_WAVEFORM_IR,
                                 (px, self._prev_y_ir), (sx, y_ir), 2)

            self._prev_y_ir = y_ir
            self._prev_y_red = y_red
            self._sweep_x += 1

            # End of sweep — reset, rescale smoothly, redraw grid
            if self._sweep_x >= ww:
                self._sweep_x = 0
                self._first_point = True

                # Smooth auto-scale (lerp factor 0.4) — matches HTML reference
                margin = (self._sweep_max - self._sweep_min) * 0.12 + 5
                self._disp_min += ((self._sweep_min - margin) - self._disp_min) * 0.4
                self._disp_max += ((self._sweep_max + margin) - self._disp_max) * 0.4

                # Reset tracking
                self._sweep_min = 9999.0
                self._sweep_max = -9999.0

                # Redraw grid
                surface.fill(COLOR_BG)
                self._draw_grid(surface, wh, ww)

        self._last_ir = ac_ir
        self._last_red = ac_red

        # Blit to screen
        self.screen.blit(surface, (0, L["waveform_y"]))

        # Redraw timeline overlay, channel labels, and amplitude legend
        self._draw_time_axis_overlay()
        self._draw_channel_labels()
        self._draw_amplitude_legend()

    def _draw_amplitude_legend(self):
        """Draw current amplitude values for each channel."""
        L = self._layout
        x = 10
        y = L["waveform_y"] + 5
        # IR amplitude
        txt_ir = self.font_small.render(f"IR: {self._peak_ir:.1f}mV", True, COLOR_WAVEFORM_IR)
        self.screen.blit(txt_ir, (x, y))
        # Red amplitude
        txt_red = self.font_small.render(f"Red: {self._peak_red:.1f}mV", True, COLOR_WAVEFORM_RED)
        self.screen.blit(txt_red, (x, y + txt_ir.get_height() + 2))

    @staticmethod
    def _map_to_y(value, d_min, d_max, height):
        r_min = d_min
        r_max = d_max
        if r_max - r_min < 10.0:
            r_max = r_min + 10.0
        padding = (r_max - r_min) * 0.1
        r_max += padding
        r_min -= padding
        normalized = (value - r_min) / (r_max - r_min)
        normalized = max(0.0, min(1.0, normalized))
        y = int((height - 1) * (1.0 - normalized))
        return max(0, min(height - 1, y))

    # ─────────────────────── METRICS HEADER ───────────────────────
    def update_metrics(self, hr, pi, spo2, rr, condition_name):
        """Update the header metrics display (proportionally spaced)."""
        hr_int = int(hr + 0.5)
        pi_x10 = int(pi * 10 + 0.5)
        spo2_int = int(spo2 + 0.5)
        rr_int = int(rr + 0.5)

        if (hr_int == self._cached_hr and pi_x10 == self._cached_pi and
                spo2_int == self._cached_spo2 and rr_int == self._cached_rr and
                condition_name == self._cached_condition):
            return

        self._cached_hr = hr_int
        self._cached_pi = pi_x10
        self._cached_spo2 = spo2_int
        self._cached_rr = rr_int
        self._cached_condition = condition_name

        self._draw_header_bg()

        L = self._layout
        sw = L["screen_w"]

        # Proportionally space 5 metrics across screen width
        # Sections: HR | PI | SpO2 | RR | Condition
        section_w = sw // 5

        # HR
        x = int(section_w * 0) + 20
        lbl = self.font_label.render("HR", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 6))
        val = self.font_value.render(f"{hr_int}", True, COLOR_WAVEFORM_IR)
        self.screen.blit(val, (x, L["header_h"] // 2))
        unit = self.font_small.render("BPM", True, COLOR_TEXT_LABEL)
        self.screen.blit(unit, (x + val.get_width() + 4, L["header_h"] // 2 + 8))

        # PI
        x = int(section_w * 1) + 10
        lbl = self.font_label.render("PI", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 6))
        val = self.font_value.render(f"{pi_x10 // 10}.{pi_x10 % 10}", True, COLOR_TEXT_VALUE)
        self.screen.blit(val, (x, L["header_h"] // 2))
        unit = self.font_small.render("%", True, COLOR_TEXT_LABEL)
        self.screen.blit(unit, (x + val.get_width() + 4, L["header_h"] // 2 + 8))

        # SpO2
        x = int(section_w * 2) + 10
        lbl = self.font_label.render("SpO\u2082", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 6))
        val = self.font_value.render(f"{spo2_int}", True, COLOR_ACCENT)
        self.screen.blit(val, (x, L["header_h"] // 2))
        unit = self.font_small.render("%", True, COLOR_TEXT_LABEL)
        self.screen.blit(unit, (x + val.get_width() + 4, L["header_h"] // 2 + 8))

        # RR
        x = int(section_w * 3) + 10
        lbl = self.font_label.render("RR", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 6))
        val = self.font_value.render(f"{rr_int}", True, COLOR_TEXT_VALUE)
        self.screen.blit(val, (x, L["header_h"] // 2))
        unit = self.font_small.render("BPM", True, COLOR_TEXT_LABEL)
        self.screen.blit(unit, (x + val.get_width() + 4, L["header_h"] // 2 + 8))

        # Condition name
        x = int(section_w * 4) + 10
        lbl = self.font_label.render("Condition", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 6))
        val = self.font_header.render(condition_name, True, COLOR_HIGHLIGHT)
        self.screen.blit(val, (x, L["header_h"] // 2))

    # ─────────────────────── FOOTER ───────────────────────
    def show_param_edit(self, param_name, value, min_val, max_val):
        """Show parameter editing info in footer."""
        L = self._layout
        self._draw_footer_bg()
        y = L["screen_h"] - L["footer_h"]
        txt = f"\u25c0  {param_name}: {value:.1f}  ({min_val:.0f}\u2013{max_val:.0f})  \u25b6"
        rendered = self.font_footer.render(txt, True, COLOR_HIGHLIGHT)
        self.screen.blit(rendered,
                         (L["screen_w"] // 2 - rendered.get_width() // 2,
                          y + (L["footer_h"] - rendered.get_height()) // 2))

    def show_condition_select(self, condition_name, condition_index):
        """Show condition selection in footer."""
        L = self._layout
        self._draw_footer_bg()
        y = L["screen_h"] - L["footer_h"]
        txt = f"\u25c0  {condition_index + 1}: {condition_name}  \u25b6    [SPACE] = Start"
        rendered = self.font_footer.render(txt, True, COLOR_HIGHLIGHT)
        self.screen.blit(rendered,
                         (L["screen_w"] // 2 - rendered.get_width() // 2,
                          y + (L["footer_h"] - rendered.get_height()) // 2))

    def show_status(self, text):
        """Show status text in footer."""
        L = self._layout
        self._draw_footer_bg()
        y = L["screen_h"] - L["footer_h"]
        rendered = self.font_footer.render(text, True, COLOR_TEXT)
        self.screen.blit(rendered,
                         (L["screen_w"] // 2 - rendered.get_width() // 2,
                          y + (L["footer_h"] - rendered.get_height()) // 2))

    # ─────────────────────── CLEAR ───────────────────────
    def clear_waveform(self):
        """Clear the waveform area and reset sweep state."""
        L = self._layout
        self._waveform_surface.fill(COLOR_BG)
        self._draw_grid(self._waveform_surface, L["waveform_h"], L["waveform_w"])
        self.screen.blit(self._waveform_surface, (0, L["waveform_y"]))
        self._draw_time_axis_overlay()

        self._sweep_x = 0
        self._first_point = True
        self._prev_y_ir = L["waveform_h"] // 2
        self._prev_y_red = L["waveform_h"] // 2
        self._last_draw_time = 0
        self._last_ir = 0.0
        self._last_red = 0.0

        self._sweep_min = 9999.0
        self._sweep_max = -9999.0
        self._disp_min = -20.0
        self._disp_max = 150.0

        self._peak_ir = 0.0
        self._peak_red = 0.0
        self._cycle_peak_ir = 0.0
        self._cycle_peak_red = 0.0
        self._last_beat_count = 0

        # Redraw channel labels
        self._draw_channel_labels()

    # ─────────────────────── COMPATIBILITY STUBS ───────────────────────
    def draw_waveform_point_ir(self, ac_value: float):
        """Legacy stub — use draw_waveform_point() instead.
        Stores value; actual drawing happens in draw_waveform_point_red().
        """
        self._pending_ir = ac_value

    def draw_waveform_point_red(self, ac_value: float):
        """Legacy stub — draws both channels using stored IR + this Red value."""
        ir_val = getattr(self, '_pending_ir', 0.0)
        self.draw_waveform_point(ir_val, ac_value)

    def flip(self):
        """Update the display."""
        pygame.display.flip()

    def tick(self, fps=None):
        """Limit frame rate."""
        self.clock.tick(fps or DISPLAY_FPS)

    def quit(self):
        """Shut down Pygame."""
        pygame.quit()
