"""Resolution-driven layout profiles for the Raspberry Pi display.

Physical diagonal size is not a reliable UI input: a 7-inch panel can expose
the same pixel dimensions as a much larger screen.  The application therefore
uses the current desktop resolution and scales from the original 1280x800
design reference.
"""
from dataclasses import dataclass


REFERENCE_WIDTH = 1280
REFERENCE_HEIGHT = 800


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class LayoutProfile:
    screen_width: int
    screen_height: int
    widget_scale: float
    compact: bool
    large: bool
    outer_pad: int
    outer_pady: int
    nav_width: int
    trace_height: int
    vital_min_width: int

    @property
    def setup_popup_size(self):
        """Keep the signal editor inside the usable desktop on every panel."""
        horizontal_margin = 24 if self.compact else 80
        vertical_margin = 42 if self.compact else 90
        maximum_width = 860 if not self.large else 980
        maximum_height = 620 if not self.large else 760
        return (max(1, min(maximum_width, self.screen_width - horizontal_margin)),
                max(1, min(maximum_height, self.screen_height - vertical_margin)))

    @property
    def geometry(self):
        return f"{self.screen_width}x{self.screen_height}+0+0"

    @property
    def minimum_size(self):
        # Never request a window larger than the connected display.
        return min(800, self.screen_width), min(480, self.screen_height)


def profile_for_screen(width, height):
    """Return a stable UI profile for one desktop resolution."""
    width, height = max(1, int(width)), max(1, int(height))
    ratio = min(width / REFERENCE_WIDTH, height / REFERENCE_HEIGHT)
    scale = _clamp(ratio, 0.75, 1.50)
    compact = width <= 1100 or height <= 650
    large = width >= 1920 and height >= 1000

    if compact:
        return LayoutProfile(width, height, scale, True, False,
                             outer_pad=8, outer_pady=6, nav_width=154,
                             trace_height=165, vital_min_width=188)
    if large:
        return LayoutProfile(width, height, scale, False, True,
                             outer_pad=22, outer_pady=16, nav_width=205,
                             trace_height=260, vital_min_width=238)
    return LayoutProfile(width, height, scale, False, False,
                         outer_pad=16, outer_pady=12, nav_width=190,
                         trace_height=220, vital_min_width=214)
