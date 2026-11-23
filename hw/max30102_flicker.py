"""max30102_flicker.py — RED on/off writer of the MAX30102 mode (config.MAX30102_*).

The RED DAC is written MAX30102_WRITE_HZ times a second, alternating 0 and the PPG on-level, at regular
times: the toggle frequency has to stay where config puts it (away from multiples of the sensor sample
rate). Bench, 23 Nov 2026, 75 bpm: a Python thread inside the app could not keep the write times regular
(interval sd 100-130 us, gaps up to 12 ms; the sensor read NO SIGNAL), while a process of its own pacing
1500 writes/s read 20/20 seconds OK. On the hardware the writer is therefore this file run as a separate
process (FlickerProcess); ThreadFlicker does the same in the engine's DAC thread for dry runs and tests.

Process protocol: stdin carries the on-level as decimal DAC codes, one per line. A line "q" or the end
of stdin (the app exited) stops it: RED is parked at 0 and one line "writes <n> errors <n> seconds <s>"
is printed. SIGTERM (systemd stopping the app's unit signals every process in it) ends it the same way.
Arguments: <i2c bus> <red DAC address> <writes per second> <peak code>.
"""
import os
import signal
import subprocess
import sys
import time

SPIN_S = 0.0002        # spin the last 200 us before a deadline: sleep alone overshoots by ~100 us
STALL_PERIODS = 4      # behind by more than this: start the schedule again instead of a burst
STOP_TIMEOUT_S = 1.0   # the process answers "q" within one write; SignalEngine joins its thread for 2 s


def run(write, read_levels, rate_hz, peak, clock=time.perf_counter, sleep=time.sleep):
    """Toggle RED until read_levels() returns None. read_levels() returns the new on-levels (may be empty)."""
    period = 1.0 / rate_hz
    level, on, writes = 0, False, 0
    deadline = clock()
    while True:
        levels = read_levels()
        if levels is None:
            break
        if levels:
            level = max(0, min(peak, int(levels[-1])))
        wait = deadline - clock()
        if wait > SPIN_S:
            sleep(wait - SPIN_S)
        while clock() < deadline:
            pass
        deadline += period
        if clock() - deadline > STALL_PERIODS * period:
            deadline = clock() + period
        on = not on
        write(level if on else 0)
        writes += 1
    return writes


def _stdin_levels(fd):
    os.set_blocking(fd, False)
    pending = b""

    def read_levels():
        nonlocal pending
        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            return []
        if not chunk:
            return None
        pending += chunk
        *lines, pending = pending.split(b"\n")
        levels = []
        for line in lines:
            line = line.strip()
            if line == b"q":
                return None
            if line:
                levels.append(int(line))
        return levels

    return read_levels


def _terminate(signum, frame):
    raise SystemExit(0)   # unwinds through main()'s finally: RED parked, counts printed


def main(argv):
    from smbus2 import SMBus
    signal.signal(signal.SIGTERM, _terminate)
    bus_number, address, rate_hz, peak = int(argv[1]), int(argv[2], 0), float(argv[3]), int(argv[4])
    errors = 0
    started = time.monotonic()
    with SMBus(bus_number) as bus:
        def write(code):
            nonlocal errors
            try:   # MCP4725 fast-mode write: [0 0 PD1 PD0 D11..D8] [D7..D0], PD = 00 (normal)
                bus.write_byte_data(address, (code >> 8) & 0x0F, code & 0xFF)
            except OSError:
                errors += 1
        writes = 0
        try:
            writes = run(write, _stdin_levels(sys.stdin.fileno()), rate_hz, peak)
        finally:
            write(0)
            print(f"writes {writes} errors {errors} seconds {time.monotonic() - started:.1f}", flush=True)
    return 0


class FlickerProcess:
    """App side of the writer process. One instance per run of the MAX30102 output."""

    def __init__(self, bus_number, address, rate_hz, peak):
        self._proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__), str(bus_number), hex(address), str(rate_hz), str(peak)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self._last = None
        self.failed = False

    def set_level(self, code):
        if code == self._last or self.failed:
            return
        try:
            self._proc.stdin.write(f"{int(code)}\n")
            self._proc.stdin.flush()
            self._last = code
        except (BrokenPipeError, OSError, ValueError):
            self.failed = True   # the process is gone: stop() reports it

    def service(self):
        """Nothing to do in the app thread; the process keeps its own time."""
        return False

    def stop(self):
        """Stop the process; returns (writes, errors, exit status)."""
        try:
            self._proc.stdin.write("q\n")   # communicate() flushes and closes stdin
        except (BrokenPipeError, OSError, ValueError):
            pass
        try:
            out, _ = self._proc.communicate(timeout=STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            out, _ = self._proc.communicate()
        writes = errors = 0
        fields = (out or "").split()
        if len(fields) >= 4 and fields[0] == "writes":
            writes, errors = int(fields[1]), int(fields[3])
        return writes, errors, self._proc.returncode


class ThreadFlicker:
    """Same output from the engine's DAC thread, without a process: dry runs and tests."""

    def __init__(self, dac_manager, rate_hz, peak, ticker):
        self._dac, self._peak, self._ticker = dac_manager, peak, ticker
        self._level, self._on, self.writes = 0, False, 0
        self.failed = False

    def set_level(self, code):
        self._level = max(0, min(self._peak, int(code)))

    def service(self):
        """Write one toggle if it is due; returns True when it wrote."""
        if not self._ticker.due(time.perf_counter()):
            return False
        self._on = not self._on
        self._dac.set_red(self._level if self._on else 0)
        self.writes += 1
        return True

    def stop(self):
        return self.writes, 0, 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
