"""RX display filter: removes the measured 1-3 sample spikes, keeps pulses and real dropouts."""
import math
import random

import pytest

from core.rx_filter import despike, filter_points, smooth


def pulse(n=800, hz=100.0, dc=640.0, ac=30.0, bpm=76):
    out = []
    for i in range(n):
        phase = (i / hz * bpm / 60) % 1
        out.append(dc + ac * math.exp(-((phase - .2) / .06) ** 2) + .5 * ac * math.exp(-((phase - .45) / .1) ** 2))
    return out


def test_isolated_spikes_of_one_to_three_samples_are_removed():
    clean = pulse()
    noisy = list(clean)
    for start, length, size in ((100, 1, 35), (300, 2, -70), (500, 3, 100), (650, 1, -103)):
        for i in range(start, start + length):
            noisy[i] += size
    out = despike(noisy)
    assert max(abs(a - b) for a, b in zip(out, clean)) < 6


def test_pulse_shape_is_kept():
    clean = pulse()
    out = smooth(despike(clean))
    assert max(out) == pytest.approx(max(clean), abs=2.5)    # systolic peak within 2.5 mV of 30 mV
    assert min(out) == pytest.approx(min(clean), abs=1.0)


def test_one_mv_background_noise_is_reduced():
    rng = random.Random(1)
    noisy = [700 + rng.gauss(0, 1.2) for _ in range(1000)]
    out = smooth(despike(noisy))
    spread = lambda v: (sorted(v)[-10] - sorted(v)[10])
    assert spread(out) < .55 * spread(noisy)


def test_a_real_dropout_to_zero_is_not_hidden():
    values = [700.0] * 200 + [4.0] * 50 + [700.0] * 200     # LED off for 0.5 s
    out = smooth(despike(values))
    assert min(out) < 10
    assert sum(1 for v in out if v < 10) >= 45


def test_points_are_filtered_per_gap_free_segment():
    points = [(i / 100, 700.0) for i in range(100)] + [(2 + i / 100, 100.0) for i in range(100)]
    out = filter_points(points, max_gap_s=.1)
    assert [t for t, _ in out] == [t for t, _ in points]
    assert out[99][1] == 700.0 and out[100][1] == 100.0      # no mixing across the 1 s hole
    assert filter_points([], .1) == []


def test_stream_filter_matches_the_full_window_filter():
    from core.rx_filter import StreamFilter
    rng = random.Random(3)
    values = [v + rng.gauss(0, 1) for v in pulse(1600)]
    for i in range(0, 1600, 97):
        values[i] += 60
    points = [(i / 100, v) for i, v in enumerate(values)]
    stream = StreamFilter()
    for end in range(50, 1600, 10):                    # 10 new samples per refresh, 8 s window
        window = points[max(0, end - 800):end]
        got = stream.update(window, .1)
        want = filter_points(window, .1)
        assert [t for t, _ in got] == [t for t, _ in window]
        # The full-window filter lacks left neighbours at the window's oldest edge; the stream keeps
        # values computed with full context there, so compare away from that edge.
        assert max(abs(a[1] - b[1]) for a, b in zip(got[10:], want[10:])) < 1.5
    assert stream.update([], .1) == []
