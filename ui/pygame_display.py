"""
pygame_display.py — Full-screen Pygame GUI for PPG Signal Simulator.

Replaces the 160×128 TFT ST7735 with a premium 1024×600 HDMI display.
Features:
  - Dual waveform: IR (green, top) and Red (red, bottom)
  - Sweep-line rendering with auto-scaling
  - Header: HR, PI, SpO2, RR, condition name
  - Footer: edit mode / condition selector
  - Mouse/keyboard parameter control
  - Grid lines, smooth rendering, dark theme
"""

import pygame
import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_FULLSCREEN, DISPLAY_FPS,
    HEADER_HEIGHT, FOOTER_HEIGHT,
    WAVEFORM_Y_START, WAVEFORM_HEIGHT, WAVEFORM_WIDTH,
    WAVEFORM_IR_HEIGHT, WAVEFORM_RED_Y_START, WAVEFORM_RED_HEIGHT,
    COLOR_BG, COLOR_WAVEFORM_IR, COLOR_WAVEFORM_RED, COLOR_GRID,
    COLOR_HEADER_BG, COLOR_FOOTER_BG, COLOR_TEXT, COLOR_TEXT_VALUE,
    COLOR_TEXT_LABEL, COLOR_HIGHLIGHT, COLOR_ACCENT, COLOR_SEPARATOR,
    COLOR_BUTTON_BG, COLOR_BUTTON_HOVER, COLOR_BUTTON_ACTIVE,
    FONT_SIZE_HEADER, FONT_SIZE_VALUE, FONT_SIZE_FOOTER,
    FONT_SIZE_LABEL, FONT_SIZE_SMALL,
    DEVICE_NAME, FIRMWARE_VERSION,
)
from comm.logger import log


class PygameDisplay:
    """Full-screen Pygame GUI for the PPG Signal Simulator."""

    def __init__(self):
        self.screen = None
        self.clock = None
        self.running = False

        # Fonts
        self.font_header = None
        self.font_value = None
        self.font_footer = None
        self.font_label = None
        self.font_small = None

        # Sweep state (IR channel)
        self._sweep_x_ir = 0
        self._prev_y_ir = WAVEFORM_Y_START + WAVEFORM_IR_HEIGHT // 2
        self._first_point_ir = True

        # Sweep state (Red channel)
        self._sweep_x_red = 0
        self._prev_y_red = WAVEFORM_RED_Y_START + WAVEFORM_RED_HEIGHT // 2
        self._first_point_red = True

        # Auto-scaling
        self._sweep_min_ir = 9999.0
        self._sweep_max_ir = -9999.0
        self._disp_min_ir = -20.0
        self._disp_max_ir = 150.0

        self._sweep_min_red = 9999.0
        self._sweep_max_red = -9999.0
        self._disp_min_red = -20.0
        self._disp_max_red = 150.0

        # Cached metrics
        self._cached_hr = -1
        self._cached_pi = -1
        self._cached_spo2 = -1
        self._cached_rr = -1
        self._cached_condition = ""

        # Waveform surfaces (for efficient erasing)
        self._waveform_surface_ir = None
        self._waveform_surface_red = None

    def begin(self) -> bool:
        """Initialize Pygame and create the display window."""
        pygame.init()
        pygame.display.set_caption(f"{DEVICE_NAME} v{FIRMWARE_VERSION}")

        flags = 0
        if DISPLAY_FULLSCREEN:
            flags = pygame.FULLSCREEN

        try:
            self.screen = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT), flags)
        except pygame.error:
            log.warning("Fullscreen failed, using windowed mode")
            self.screen = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))

        self.clock = pygame.time.Clock()

        # Load fonts
        try:
            self.font_header = pygame.font.SysFont("dejavusans", FONT_SIZE_HEADER, bold=True)
            self.font_value = pygame.font.SysFont("dejavusans", FONT_SIZE_VALUE, bold=True)
            self.font_footer = pygame.font.SysFont("dejavusans", FONT_SIZE_FOOTER)
            self.font_label = pygame.font.SysFont("dejavusans", FONT_SIZE_LABEL)
            self.font_small = pygame.font.SysFont("dejavusans", FONT_SIZE_SMALL)
        except Exception:
            self.font_header = pygame.font.Font(None, FONT_SIZE_HEADER)
            self.font_value = pygame.font.Font(None, FONT_SIZE_VALUE)
            self.font_footer = pygame.font.Font(None, FONT_SIZE_FOOTER)
            self.font_label = pygame.font.Font(None, FONT_SIZE_LABEL)
            self.font_small = pygame.font.Font(None, FONT_SIZE_SMALL)

        # Create waveform surfaces
        self._waveform_surface_ir = pygame.Surface((WAVEFORM_WIDTH, WAVEFORM_IR_HEIGHT))
        self._waveform_surface_ir.fill(COLOR_BG)
        self._waveform_surface_red = pygame.Surface((WAVEFORM_WIDTH, WAVEFORM_RED_HEIGHT))
        self._waveform_surface_red.fill(COLOR_BG)

        self.screen.fill(COLOR_BG)
        self._draw_layout()
        pygame.display.flip()

        self.running = True
        log.info(f"[Display] Pygame initialized: {DISPLAY_WIDTH}x{DISPLAY_HEIGHT}")
        return True

    # ─────────────────────── LAYOUT ───────────────────────
    def _draw_layout(self):
        """Draw the initial screen layout."""
        self._draw_header_bg()
        self._draw_footer_bg()
        self._draw_grid(self._waveform_surface_ir, WAVEFORM_IR_HEIGHT)
        self._draw_grid(self._waveform_surface_red, WAVEFORM_RED_HEIGHT)
        self.screen.blit(self._waveform_surface_ir, (0, WAVEFORM_Y_START))
        self.screen.blit(self._waveform_surface_red, (0, WAVEFORM_RED_Y_START))
        # Separator between IR and Red
        pygame.draw.line(self.screen, COLOR_SEPARATOR,
                         (0, WAVEFORM_RED_Y_START), (DISPLAY_WIDTH, WAVEFORM_RED_Y_START), 2)
        # Channel labels
        lbl_ir = self.font_small.render("IR", True, COLOR_WAVEFORM_IR)
        lbl_red = self.font_small.render("RED", True, COLOR_WAVEFORM_RED)
        self.screen.blit(lbl_ir, (DISPLAY_WIDTH - 40, WAVEFORM_Y_START + 5))
        self.screen.blit(lbl_red, (DISPLAY_WIDTH - 40, WAVEFORM_RED_Y_START + 5))

    def _draw_header_bg(self):
        pygame.draw.rect(self.screen, COLOR_HEADER_BG, (0, 0, DISPLAY_WIDTH, HEADER_HEIGHT))
        pygame.draw.line(self.screen, COLOR_SEPARATOR,
                         (0, HEADER_HEIGHT - 1), (DISPLAY_WIDTH, HEADER_HEIGHT - 1), 1)

    def _draw_footer_bg(self):
        y = DISPLAY_HEIGHT - FOOTER_HEIGHT
        pygame.draw.rect(self.screen, COLOR_FOOTER_BG, (0, y, DISPLAY_WIDTH, FOOTER_HEIGHT))
        pygame.draw.line(self.screen, COLOR_SEPARATOR, (0, y), (DISPLAY_WIDTH, y), 1)

    def _draw_grid(self, surface, height):
        """Draw grid lines on a waveform surface."""
        w = WAVEFORM_WIDTH
        mid_y = height // 2
        # Center line
        pygame.draw.line(surface, COLOR_GRID, (0, mid_y), (w, mid_y), 1)
        # Quarter lines (dotted)
        q1 = height // 4
        q3 = 3 * height // 4
        for x in range(0, w, 6):
            surface.set_at((x, q1), COLOR_GRID)
            surface.set_at((x, q3), COLOR_GRID)
        # Vertical lines
        for x in range(80, w, 80):
            for y in range(0, height, 6):
                surface.set_at((x, y), COLOR_GRID)

    # ─────────────────────── WAVEFORM DRAWING ───────────────────────
    def draw_waveform_point_ir(self, ac_value: float):
        """Draw a single IR waveform point using sweep-line approach."""
        self._draw_point_on_surface(
            self._waveform_surface_ir, ac_value,
            WAVEFORM_IR_HEIGHT, COLOR_WAVEFORM_IR,
            "ir"
        )
        self.screen.blit(self._waveform_surface_ir, (0, WAVEFORM_Y_START))

    def draw_waveform_point_red(self, ac_value: float):
        """Draw a single Red waveform point using sweep-line approach."""
        self._draw_point_on_surface(
            self._waveform_surface_red, ac_value,
            WAVEFORM_RED_HEIGHT, COLOR_WAVEFORM_RED,
            "red"
        )
        self.screen.blit(self._waveform_surface_red, (0, WAVEFORM_RED_Y_START))

    def _draw_point_on_surface(self, surface, ac_value, height, color, channel):
        """Generic sweep-line waveform drawing on a surface."""
        if channel == "ir":
            sweep_x = self._sweep_x_ir
            prev_y = self._prev_y_ir
            first = self._first_point_ir
            s_min, s_max = self._sweep_min_ir, self._sweep_max_ir
            d_min, d_max = self._disp_min_ir, self._disp_max_ir
        else:
            sweep_x = self._sweep_x_red
            prev_y = self._prev_y_red
            first = self._first_point_red
            s_min, s_max = self._sweep_min_red, self._sweep_max_red
            d_min, d_max = self._disp_min_red, self._disp_max_red

        # Track min/max for auto-scaling
        if ac_value < s_min: s_min = ac_value
        if ac_value > s_max: s_max = ac_value

        # Map to Y
        y = self._map_to_y(ac_value, d_min, d_max, height)

        # Erase ahead
        erase_x1 = (sweep_x + 2) % WAVEFORM_WIDTH
        erase_x2 = (sweep_x + 3) % WAVEFORM_WIDTH
        pygame.draw.line(surface, COLOR_BG, (erase_x1, 0), (erase_x1, height - 1), 1)
        pygame.draw.line(surface, COLOR_BG, (erase_x2, 0), (erase_x2, height - 1), 1)

        # Sweep cursor
        cursor_x = (sweep_x + 1) % WAVEFORM_WIDTH
        pygame.draw.line(surface, COLOR_GRID, (cursor_x, 0), (cursor_x, height - 1), 1)

        # Draw waveform
        if first:
            surface.set_at((sweep_x, y), color)
            first = False
        else:
            pygame.draw.line(surface, color, (sweep_x - 1, prev_y), (sweep_x, y), 2)

        prev_y = y
        sweep_x += 1

        if sweep_x >= WAVEFORM_WIDTH:
            sweep_x = 0
            first = True
            d_min = s_min
            d_max = s_max
            s_min = 9999.0
            s_max = -9999.0
            surface.fill(COLOR_BG)
            self._draw_grid(surface, height)

        # Write back state
        if channel == "ir":
            self._sweep_x_ir = sweep_x
            self._prev_y_ir = prev_y
            self._first_point_ir = first
            self._sweep_min_ir = s_min
            self._sweep_max_ir = s_max
            self._disp_min_ir = d_min
            self._disp_max_ir = d_max
        else:
            self._sweep_x_red = sweep_x
            self._prev_y_red = prev_y
            self._first_point_red = first
            self._sweep_min_red = s_min
            self._sweep_max_red = s_max
            self._disp_min_red = d_min
            self._disp_max_red = d_max

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
        """Update the header metrics display."""
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

        # HR
        x = 20
        lbl = self.font_label.render("HR", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 8))
        val = self.font_value.render(f"{hr_int}", True, COLOR_WAVEFORM_IR)
        self.screen.blit(val, (x, 26))
        unit = self.font_small.render("BPM", True, COLOR_TEXT_LABEL)
        self.screen.blit(unit, (x + val.get_width() + 4, 34))

        # PI
        x = 200
        lbl = self.font_label.render("PI", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 8))
        val = self.font_value.render(f"{pi_x10 // 10}.{pi_x10 % 10}", True, COLOR_TEXT_VALUE)
        self.screen.blit(val, (x, 26))
        unit = self.font_small.render("%", True, COLOR_TEXT_LABEL)
        self.screen.blit(unit, (x + val.get_width() + 4, 34))

        # SpO2
        x = 370
        lbl = self.font_label.render("SpO₂", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 8))
        val = self.font_value.render(f"{spo2_int}", True, COLOR_ACCENT)
        self.screen.blit(val, (x, 26))
        unit = self.font_small.render("%", True, COLOR_TEXT_LABEL)
        self.screen.blit(unit, (x + val.get_width() + 4, 34))

        # RR
        x = 530
        lbl = self.font_label.render("RR", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 8))
        val = self.font_value.render(f"{rr_int}", True, COLOR_TEXT_VALUE)
        self.screen.blit(val, (x, 26))
        unit = self.font_small.render("BPM", True, COLOR_TEXT_LABEL)
        self.screen.blit(unit, (x + val.get_width() + 4, 34))

        # Condition name
        x = 720
        lbl = self.font_label.render("Condition", True, COLOR_TEXT_LABEL)
        self.screen.blit(lbl, (x, 8))
        val = self.font_header.render(condition_name, True, COLOR_HIGHLIGHT)
        self.screen.blit(val, (x, 28))

    # ─────────────────────── FOOTER ───────────────────────
    def show_param_edit(self, param_name, value, min_val, max_val):
        """Show parameter editing info in footer."""
        y = DISPLAY_HEIGHT - FOOTER_HEIGHT
        self._draw_footer_bg()
        txt = f"◀  {param_name}: {value:.1f}  ({min_val:.0f}–{max_val:.0f})  ▶"
        rendered = self.font_footer.render(txt, True, COLOR_HIGHLIGHT)
        self.screen.blit(rendered, (DISPLAY_WIDTH // 2 - rendered.get_width() // 2, y + 10))

    def show_condition_select(self, condition_name, condition_index):
        """Show condition selection in footer."""
        y = DISPLAY_HEIGHT - FOOTER_HEIGHT
        self._draw_footer_bg()
        txt = f"◀  {condition_index + 1}: {condition_name}  ▶    [SPACE] = Start"
        rendered = self.font_footer.render(txt, True, COLOR_HIGHLIGHT)
        self.screen.blit(rendered, (DISPLAY_WIDTH // 2 - rendered.get_width() // 2, y + 10))

    def show_status(self, text):
        """Show status text in footer."""
        y = DISPLAY_HEIGHT - FOOTER_HEIGHT
        self._draw_footer_bg()
        rendered = self.font_footer.render(text, True, COLOR_TEXT)
        self.screen.blit(rendered, (DISPLAY_WIDTH // 2 - rendered.get_width() // 2, y + 10))

    # ─────────────────────── CLEAR ───────────────────────
    def clear_waveform(self):
        """Clear both waveform areas and reset sweep state."""
        self._waveform_surface_ir.fill(COLOR_BG)
        self._waveform_surface_red.fill(COLOR_BG)
        self._draw_grid(self._waveform_surface_ir, WAVEFORM_IR_HEIGHT)
        self._draw_grid(self._waveform_surface_red, WAVEFORM_RED_HEIGHT)
        self.screen.blit(self._waveform_surface_ir, (0, WAVEFORM_Y_START))
        self.screen.blit(self._waveform_surface_red, (0, WAVEFORM_RED_Y_START))

        self._sweep_x_ir = 0; self._first_point_ir = True
        self._prev_y_ir = WAVEFORM_IR_HEIGHT // 2
        self._sweep_x_red = 0; self._first_point_red = True
        self._prev_y_red = WAVEFORM_RED_HEIGHT // 2

        self._sweep_min_ir = 9999.0; self._sweep_max_ir = -9999.0
        self._disp_min_ir = -20.0; self._disp_max_ir = 150.0
        self._sweep_min_red = 9999.0; self._sweep_max_red = -9999.0
        self._disp_min_red = -20.0; self._disp_max_red = 150.0

        # Redraw channel labels
        lbl_ir = self.font_small.render("IR", True, COLOR_WAVEFORM_IR) if self.font_small else None
        lbl_red = self.font_small.render("RED", True, COLOR_WAVEFORM_RED) if self.font_small else None
        if lbl_ir:
            self.screen.blit(lbl_ir, (DISPLAY_WIDTH - 40, WAVEFORM_Y_START + 5))
        if lbl_red:
            self.screen.blit(lbl_red, (DISPLAY_WIDTH - 40, WAVEFORM_RED_Y_START + 5))

    def flip(self):
        """Update the display."""
        pygame.display.flip()

    def tick(self, fps=None):
        """Limit frame rate."""
        self.clock.tick(fps or DISPLAY_FPS)

    def quit(self):
        """Shut down Pygame."""
        pygame.quit()
