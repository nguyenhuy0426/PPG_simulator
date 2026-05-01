"""
state_machine.py — System state machine for PPG Signal Simulator.

Port of state_machine.cpp.
State flow: INIT → SELECT_CONDITION → SIMULATING ↔ PAUSED
"""

# ─── System States ───
STATE_INIT             = 0
STATE_SELECT_CONDITION = 1
STATE_SIMULATING       = 2
STATE_PAUSED           = 3
STATE_ERROR            = 4

# ─── System Events ───
EVT_INIT_COMPLETE     = 0
EVT_BTN_MODE_PRESS    = 1
EVT_BTN_UP_PRESS      = 2
EVT_BTN_DOWN_PRESS    = 3
EVT_SELECT_CONDITION  = 4
EVT_START_SIMULATION  = 5
EVT_PAUSE             = 6
EVT_RESUME            = 7
EVT_STOP              = 8
EVT_ERROR             = 9

# ─── UI Edit Modes ───
EDIT_CONDITION_SELECT = 0
EDIT_HR               = 1
EDIT_PI               = 2
EDIT_SPO2             = 3
EDIT_RR               = 4
EDIT_NOISE            = 5
EDIT_COUNT            = 6

_STATE_NAMES = {
    STATE_INIT: "INIT", STATE_SELECT_CONDITION: "SELECT_CONDITION",
    STATE_SIMULATING: "SIMULATING", STATE_PAUSED: "PAUSED", STATE_ERROR: "ERROR",
}

_EDIT_NAMES = {
    EDIT_CONDITION_SELECT: "Condition", EDIT_HR: "Heart Rate",
    EDIT_PI: "Perf. Index", EDIT_SPO2: "SpO2",
    EDIT_RR: "Resp. Rate", EDIT_NOISE: "Noise",
}

CONDITION_COUNT = 6


class StateMachine:
    """System state machine with edit mode cycling."""

    def __init__(self):
        self.state = STATE_INIT
        self.selected_condition = 0
        self.edit_mode = EDIT_CONDITION_SELECT
        self._on_state_change = None

    def set_state_change_callback(self, callback):
        """Set callback: callback(old_state, new_state)."""
        self._on_state_change = callback

    def process_event(self, event: int, param: int = 0):
        """Process a system event."""
        old = self.state
        new = old

        if old == STATE_INIT:
            if event == EVT_INIT_COMPLETE:
                new = STATE_SELECT_CONDITION

        elif old == STATE_SELECT_CONDITION:
            if event == EVT_SELECT_CONDITION:
                self.selected_condition = param
            elif event in (EVT_START_SIMULATION, EVT_BTN_MODE_PRESS):
                new = STATE_SIMULATING
            elif event == EVT_BTN_UP_PRESS:
                self.selected_condition = (self.selected_condition + 1) % CONDITION_COUNT
            elif event == EVT_BTN_DOWN_PRESS:
                self.selected_condition = (self.selected_condition - 1) % CONDITION_COUNT

        elif old == STATE_SIMULATING:
            if event == EVT_BTN_MODE_PRESS:
                self.edit_mode = (self.edit_mode + 1) % EDIT_COUNT
            elif event == EVT_PAUSE:
                new = STATE_PAUSED
            elif event == EVT_STOP:
                new = STATE_SELECT_CONDITION
                self.edit_mode = EDIT_CONDITION_SELECT

        elif old == STATE_PAUSED:
            if event in (EVT_RESUME, EVT_BTN_MODE_PRESS):
                new = STATE_SIMULATING
            elif event == EVT_STOP:
                new = STATE_SELECT_CONDITION
                self.edit_mode = EDIT_CONDITION_SELECT

        elif old == STATE_ERROR:
            if event == EVT_INIT_COMPLETE:
                new = STATE_SELECT_CONDITION

        if new != old:
            self.state = new
            if self._on_state_change:
                self._on_state_change(old, new)

    @staticmethod
    def state_to_string(state: int) -> str:
        return _STATE_NAMES.get(state, "UNKNOWN")

    @staticmethod
    def edit_mode_to_string(mode: int) -> str:
        return _EDIT_NAMES.get(mode, "Unknown")
