"""RingBuffer: a window cut by wall-clock time returns exactly the samples captured then."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.io.audio_ring import RingBuffer

FS = 1000
T0 = 5000.0


def _fill(rb: RingBuffer, n_blocks: int, block: int = 100, start_index: int = 0, t_jump: float = 0.0):
    """Blocks whose sample VALUE is its global index, with wall time T0 + index/FS (+ an optional clock jump)."""
    for b in range(n_blocks):
        i = start_index + b * block
        rb.append(np.arange(i, i + block, dtype=np.float32), T0 + i / FS + t_jump)


def test_window_returns_the_samples_captured_in_that_time():
    rb = RingBuffer(FS, 5.0)
    _fill(rb, 30)                                           # 3 s of audio, nothing overwritten yet
    w = rb.window(T0 + 1.0, T0 + 1.5)
    assert w.size == 500 and w[0] == 1000 and w[-1] == 1499
    assert rb.latest_time == pytest.approx(T0 + 3.0)


def test_window_across_the_ring_wrap_is_contiguous():
    rb = RingBuffer(FS, 2.0)                                # holds 2000 samples
    _fill(rb, 35)                                           # 3500 samples: the ring has wrapped
    w = rb.window(T0 + 2.6, T0 + 3.4)                       # straddles the wrap point
    assert w.size == 800 and w[0] == 2600 and np.all(np.diff(w) == 1)


def test_data_already_overwritten_or_not_yet_arrived_is_refused():
    rb = RingBuffer(FS, 2.0)
    _fill(rb, 35)
    assert rb.window(T0 + 0.5, T0 + 1.0) is None            # too old: overwritten
    assert rb.window(T0 + 3.0, T0 + 3.8) is None            # runs past what has arrived
    assert rb.window(T0 + 3.0, T0 + 3.0) is None           # empty / reversed
    assert RingBuffer(FS, 1.0).window(0, 1) is None         # nothing yet
    assert RingBuffer(FS, 1.0).latest_time is None


def test_a_clock_jump_between_blocks_is_followed_by_the_nearest_earlier_block():
    rb = RingBuffer(FS, 5.0)
    _fill(rb, 10)                                           # samples 0..999 on the original clock
    _fill(rb, 10, start_index=1000, t_jump=0.250)           # the clock steps forward 250 ms
    w = rb.window(T0 + 1.0 + 0.250, T0 + 1.1 + 0.250)       # the 100 samples after the step
    assert w[0] == 1000 and w.size == 100
    early = rb.window(T0 + 0.3, T0 + 0.4)                   # before the step: unaffected
    assert early[0] == 300


def test_a_block_longer_than_the_ring_keeps_only_its_tail():
    rb = RingBuffer(FS, 1.0)                                # 1000 samples
    rb.append(np.arange(2500, dtype=np.float32), T0)        # 2.5 s in one block
    assert rb.total == 2500
    w = rb.window(T0 + 1.6, T0 + 2.0)
    assert w[0] == 1600 and w[-1] == 1999
    assert rb.window(T0 + 0.5, T0 + 1.0) is None


def test_empty_blocks_are_ignored():
    rb = RingBuffer(FS, 1.0)
    rb.append(np.array([]), T0)
    assert rb.total == 0 and rb.latest_time is None


def test_the_strike_lands_where_it_was_cut_for():
    """A click at a known wall time ends up at pre_s inside a window cut pre_s before it."""
    rb = RingBuffer(FS, 10.0)
    sig = np.zeros(6000, dtype=np.float32)
    t_click = T0 + 3.200
    sig[int(3.200 * FS)] = 1.0
    for i in range(0, 6000, 100):
        rb.append(sig[i:i + 100], T0 + i / FS)
    w = rb.window(t_click - 0.5, t_click + 1.0)
    assert w.size == 1500 and int(np.argmax(w)) == 500
