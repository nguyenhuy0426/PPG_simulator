"""core.apft_range: the measured beat rate of a window, and the search that keeps only a window inside the range."""
import contextlib
import io
import json
import math
import sys
import types
from unittest import mock

import pytest

from core import apft_range, sequence_worker
from core.apft_preview import APFTSequenceGenerator, RangeMiss


def pulse_window(bpm, n=1200, fs=40, skip=()):
    """Min-max PPG-like window at bpm; beats whose index is in skip are left out (a missed beat)."""
    period = 60 / bpm
    out = []
    for i in range(n):
        t = i / fs
        k, phase = divmod(t, period)
        x = 0.0 if int(k) in skip else math.exp(-((phase / period - .2) / .08) ** 2) + \
            .35 * math.exp(-((phase / period - .5) / .1) ** 2)
        out.append(x)
    lo, hi = min(out), max(out)
    return [(v - lo) / (hi - lo) for v in out]


@pytest.mark.parametrize("bpm", [60, 72, 85, 100])
def test_window_rate_reads_the_beat_rate(bpm):
    check = apft_range.window_rate(pulse_window(bpm))
    assert check.bpm == pytest.approx(bpm, abs=.5)
    assert check.odd == 0 and check.beats >= apft_range.MIN_BEATS


def test_a_missed_beat_is_irregular_not_a_slower_rate():
    check = apft_range.window_rate(pulse_window(75, skip=(5, 12, 20)))
    assert check.odd > apft_range.MAX_ODD
    assert not apft_range.accepts(check, 60, 75)


def test_flat_window_has_no_rate():
    assert apft_range.window_rate([0.0] * 1199 + [1.0]).bpm is None


@pytest.mark.parametrize("lo,hi", [(55, 70), (90, 105), (80, 81), (80, 70)])
def test_range_outside_60_100_or_too_narrow_is_refused(lo, hi):
    with pytest.raises(ValueError, match="60-100"):
        apft_range.validate_range(lo, hi)


def fake_clock(step=1.0):
    t = [0.0]

    def clock():
        t[0] += step
        return t[0]
    return clock


def test_requests_spread_over_the_range_and_stay_in_limits():
    assert apft_range.spread(70, 78, 4) == [71.0, 73.0, 75.0, 77.0]
    assert apft_range.spread(96, 100, 2, shift=10) == [100.0, 100.0]


def test_search_keeps_the_in_range_window_nearest_the_middle():
    calls = []

    def make(seed, requests):
        calls.append((seed, list(requests)))
        rates = [88.0, 74.5, 71.2, 79.0] if seed == 10 else [88.0] * 4
        return [pulse_window(r) for r in rates]
    result = apft_range.search(make, 70, 76, seed=10, budget_s=100, batch=4, clock=fake_clock())
    assert (result.seed, result.index) == (10, 1)
    assert result.check.bpm == pytest.approx(74.5, abs=.5)            # 74.5 is nearer 73 than 71.2
    assert len(calls) == 1 and len(calls[0][1]) == 4
    assert all(70 <= r <= 76 for r in calls[0][1])


def test_search_shifts_the_next_batch_against_the_miss():
    calls = []

    def make(seed, requests):
        calls.append(list(requests))
        return [pulse_window(r + 12) for r in requests]                 # this generator always runs 12 bpm fast
    result = apft_range.search(make, 70, 76, seed=0, budget_s=100, batch=4, clock=fake_clock())
    assert result.window is not None and len(calls) == 2
    assert calls[1][1] == pytest.approx(calls[0][1] - 12, abs=.5)
    assert min(calls[1]) >= 60                                           # kept inside the generator's limits


def test_search_stops_inside_the_budget():
    calls = []
    result = apft_range.search(lambda seed, req: calls.append(seed) or [pulse_window(90)] * len(req), 70, 75,
                               seed=0, budget_s=8, batch=2, clock=fake_clock())
    assert result.window is None and len(calls) == 3 and len(result.tries) == 6
    assert all(t[3] == pytest.approx(90, abs=.5) for t in result.tries)


def test_worker_reports_a_miss_as_json_with_exit_2():
    class Fake:
        def generate_in_range(self, seed, lo, hi):
            raise RangeMiss(lo, hi, [(seed, 0, 73.0, 88.1, 0.0)])
    module = types.ModuleType("core.apft_preview")
    module.APFTSequenceGenerator, module.RangeMiss = Fake, RangeMiss
    out = io.StringIO()
    with mock.patch.dict(sys.modules, {"core.apft_preview": module}), contextlib.redirect_stdout(out):
        code = sequence_worker.main(["5", "APFT-GAN", "73", "--hr-range", "70", "76"])
    assert code == 2
    assert json.loads(out.getvalue()) == dict(error="hr_range", range=[70.0, 76.0], tries=[[5, 0, 73.0, 88.1, 0.0]])
    with pytest.raises(SystemExit):
        with contextlib.redirect_stderr(io.StringIO()):
            sequence_worker.main(["5", "PSF-GAN", "73", "--hr-range", "70", "76"])


def test_generator_marks_the_measured_rate():
    gen = APFTSequenceGenerator.__new__(APFTSequenceGenerator)
    gen.manifest = dict(sha256="x", checkpoint_step=1250)
    batches = iter([[95.0] * 8, [95.0] * 7 + [78.0]])
    gen.windows = lambda seed, requests: [pulse_window(r) for r in next(batches)]
    preview = gen.generate_in_range(3, 75, 80, budget_s=100)
    info = preview.provenance
    assert info["hr_range"] == [75.0, 80.0] and info["hr_measured_bpm"] == pytest.approx(78, abs=.5)
    assert len(info["tries"]) == 16 and (preview.seed, info["batch_index"]) == (4, 7)
    assert len(preview.samples) == 1200
    gen.windows = lambda seed, requests: [pulse_window(95)] * len(requests)
    with pytest.raises(RangeMiss, match="75-80 bpm after 8 tries"):
        gen.generate_in_range(3, 75, 80, budget_s=0)
