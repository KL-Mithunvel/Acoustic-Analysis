"""dsp/segmentation.py - cutting a long take into strike snippets.

Every case is a synthetic signal whose correct answer is known by construction:
taps are placed at chosen times and the detector has to give those times back.
"""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.dsp.segmentation import (
    detect_onsets,
    envelope_minmax,
    moving_rms,
    noise_floor,
    segments_from_onsets,
)
from tests.synth import make_tap_sequence, make_tone, make_white_noise

_FS = 48000


# -- moving_rms ------------------------------------------------------------
def test_moving_rms_of_constant_is_that_constant():
    x = np.full(1000, 0.5)
    out = moving_rms(x, 101)
    # Away from the clamped ends every window sees only 0.5.
    assert np.allclose(out[200:800], 0.5)


def test_moving_rms_of_sine_approaches_amplitude_over_root_two():
    x = make_tone(1000.0, 0.2, _FS, amplitude=1.0)
    out = moving_rms(x, _FS // 100)  # 10 ms - many cycles
    assert out[1000:-1000] == pytest.approx(1 / np.sqrt(2), abs=0.02)


def test_moving_rms_tracks_a_step():
    x = np.concatenate([np.full(5000, 0.01), np.full(5000, 1.0)])
    out = moving_rms(x, 201)
    assert out[1000] < 0.05
    assert out[9000] > 0.9


def test_moving_rms_window_larger_than_signal_is_clamped():
    out = moving_rms(np.ones(10), 1000)
    assert out.size == 10
    assert np.allclose(out, 1.0)


def test_moving_rms_rejects_empty_and_tiny_windows():
    with pytest.raises(ValueError):
        moving_rms(np.array([]), 10)
    with pytest.raises(ValueError):
        moving_rms(np.ones(10), 0)


# -- envelope_minmax -------------------------------------------------------
def test_envelope_minmax_keeps_the_extremes():
    x = np.zeros(10000)
    x[4321] = 3.0     # a one-sample spike, the thing subsampling would miss
    x[8765] = -2.0
    lo, hi = envelope_minmax(x, 100)
    assert hi.max() == pytest.approx(3.0)
    assert lo.min() == pytest.approx(-2.0)


def test_envelope_minmax_length_and_short_signal():
    lo, hi = envelope_minmax(np.arange(1000.0), 250)
    assert lo.size == hi.size == 250
    # Fewer samples than buckets: one bucket per sample, not padding.
    lo, hi = envelope_minmax(np.arange(7.0), 100)
    assert lo.size == 7


def test_envelope_minmax_bounds_bracket_the_signal():
    x = make_white_noise(1.0, _FS, rms=0.3, seed=3)
    lo, hi = envelope_minmax(x, 500)
    assert lo.min() == pytest.approx(x.min())
    assert hi.max() == pytest.approx(x.max())
    assert np.all(lo <= hi)


def test_envelope_minmax_rejects_bad_input():
    with pytest.raises(ValueError):
        envelope_minmax(np.array([]), 10)
    with pytest.raises(ValueError):
        envelope_minmax(np.ones(10), 0)


# -- noise_floor -----------------------------------------------------------
def test_noise_floor_ignores_the_loud_minority():
    env = np.concatenate([np.full(900, 0.01), np.full(100, 5.0)])
    # The strikes are 10% of the take; the 25th percentile must not see them.
    assert noise_floor(env, 25.0) == pytest.approx(0.01)


def test_noise_floor_rejects_bad_input():
    with pytest.raises(ValueError):
        noise_floor(np.array([]))
    with pytest.raises(ValueError):
        noise_floor(np.ones(10), percentile=140.0)


# -- detect_onsets ---------------------------------------------------------
def test_detect_onsets_finds_every_tap_at_the_right_time():
    taps = [0.5, 1.4, 2.6, 3.1, 4.8]
    x = make_tap_sequence(_FS, taps, duration_s=6.0)
    found = [i / _FS for i in detect_onsets(x, _FS)]

    assert len(found) == len(taps)
    for got, want in zip(found, taps):
        # Onsets are walked back to the start of the attack, so they may land
        # slightly early - never late, which would clip the strike.
        assert want - 0.02 <= got <= want + 0.005


def test_detect_onsets_does_not_report_one_strike_twice():
    # A long ring fluctuating across the threshold is the classic double-count.
    x = make_tap_sequence(_FS, [1.0], duration_s=3.0, tau_s=0.35)
    assert len(detect_onsets(x, _FS, min_gap_s=0.35)) == 1


def test_detect_onsets_separates_closely_spaced_taps():
    taps = [1.0, 1.5, 2.0]
    x = make_tap_sequence(_FS, taps, duration_s=3.0, tau_s=0.05)
    assert len(detect_onsets(x, _FS, min_gap_s=0.3)) == 3
    # A refractory period longer than the spacing must merge them, not error.
    assert len(detect_onsets(x, _FS, min_gap_s=0.8)) < 3


def test_detect_onsets_rejects_quiet_handling_noise():
    # One real strike plus a bump 40x quieter - a tile being set down.
    x = make_tap_sequence(_FS, [1.0], duration_s=4.0, amplitude=0.6)
    x += make_tap_sequence(_FS, [2.5], duration_s=4.0, amplitude=0.015, noise_rms=0.0, seed=9)
    found = detect_onsets(x, _FS, min_peak_ratio=0.05)
    assert len(found) == 1
    assert found[0] / _FS == pytest.approx(1.0, abs=0.02)


def test_detect_onsets_on_silence_and_noise_only_returns_nothing():
    assert detect_onsets(np.zeros(_FS), _FS) == []
    quiet = make_white_noise(2.0, _FS, rms=0.01, seed=5)
    assert detect_onsets(quiet, _FS, threshold_mult=6.0) == []


def test_detect_onsets_sensitivity_is_monotonic():
    taps = [0.5, 1.2, 2.0, 2.9]
    x = make_tap_sequence(_FS, taps, duration_s=4.0, amplitude=0.3)
    loose = len(detect_onsets(x, _FS, threshold_mult=3.0))
    tight = len(detect_onsets(x, _FS, threshold_mult=11.0))
    assert loose >= tight


def test_detect_onsets_rejects_bad_input():
    with pytest.raises(ValueError):
        detect_onsets(np.array([]), _FS)
    with pytest.raises(ValueError):
        detect_onsets(np.ones(100), 0)
    with pytest.raises(ValueError):
        detect_onsets(np.ones(100), _FS, threshold_mult=1.0)


# -- segments_from_onsets --------------------------------------------------
def test_segments_keep_pre_roll_and_ring():
    onset = int(1.0 * _FS)
    (start, end), = segments_from_onsets([onset], 3 * _FS, _FS, pre_ms=30, post_ms=700)
    assert (onset - start) / _FS == pytest.approx(0.030)
    assert (end - onset) / _FS == pytest.approx(0.700)


def test_segments_are_clamped_to_the_recording():
    onsets = [int(0.005 * _FS), int(2.99 * _FS)]
    out = segments_from_onsets(onsets, 3 * _FS, _FS, pre_ms=50, post_ms=700)
    assert out[0][0] == 0
    assert out[-1][1] == 3 * _FS


def test_segments_never_overlap_the_next_strike():
    onsets = [int(1.0 * _FS), int(1.2 * _FS)]
    out = segments_from_onsets(onsets, 3 * _FS, _FS, pre_ms=30, post_ms=700, guard_ms=20)
    assert out[0][1] <= out[1][0]
    # Trimmed by max(pre, guard) = 30 ms, which is exactly where the second
    # window starts - they touch, and no audio belongs to both.
    assert out[0][1] / _FS == pytest.approx(1.2 - 0.030, abs=1e-3)


def test_segments_are_trimmed_by_the_guard_when_it_exceeds_the_pre_roll():
    onsets = [int(1.0 * _FS), int(1.2 * _FS)]
    out = segments_from_onsets(onsets, 3 * _FS, _FS, pre_ms=10, post_ms=700, guard_ms=50)
    assert out[0][1] / _FS == pytest.approx(1.2 - 0.050, abs=1e-3)
    assert out[0][1] < out[1][0]   # a real gap, not just touching


def test_segments_sorts_unordered_onsets():
    out = segments_from_onsets([int(2 * _FS), int(1 * _FS)], 3 * _FS, _FS)
    assert out[0][0] < out[1][0]


def test_segments_rejects_bad_input():
    with pytest.raises(ValueError):
        segments_from_onsets([100], 0, _FS)
    with pytest.raises(ValueError):
        segments_from_onsets([100], 1000, _FS, post_ms=0)
