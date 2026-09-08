"""Tests for acoustic_analysis.dsp.sound_level."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.dsp import sound_level as sl
from tests.synth import make_tone, make_white_noise

_FS = 48000


def test_leq_of_unit_sine_relative():
    x = make_tone(1000.0, 0.5, _FS, amplitude=1.0)
    assert sl.leq(x) == pytest.approx(10 * np.log10(0.5), abs=0.05)  # ~ -3.01 dB


def test_leq_with_reference_pressure_gives_db_spl():
    # 1 Pa amplitude sine -> mean square 0.5 Pa^2
    x = make_tone(1000.0, 0.5, _FS, amplitude=1.0)
    expected = 10 * np.log10(0.5 / (20e-6) ** 2)
    assert sl.leq(x, ref_pressure=20e-6) == pytest.approx(expected, abs=0.05)


def test_lpeak_of_unit_sine_is_zero_db_relative():
    x = make_tone(1000.0, 0.2, _FS, amplitude=1.0)
    assert sl.lpeak(x) == pytest.approx(0.0, abs=0.05)


def test_leq_empty_raises():
    with pytest.raises(ValueError):
        sl.leq(np.array([]))


def test_time_weighting_converges_to_mean_square():
    # 6 s is > 5 time constants even for Slow (tau = 1 s), so both settle to 0.5
    x = make_tone(1000.0, 6.0, _FS, amplitude=1.0)
    for mode in ("fast", "slow"):
        trace = sl.exp_time_weight(x, _FS, mode)
        assert trace[-1] == pytest.approx(0.5, rel=0.05)


def test_fast_settles_quicker_than_slow():
    x = make_tone(1000.0, 1.0, _FS, amplitude=1.0)
    fast = sl.exp_time_weight(x, _FS, "fast")
    slow = sl.exp_time_weight(x, _FS, "slow")
    n = int(0.125 * _FS)  # one fast time constant
    assert fast[n] > slow[n]


def test_impulse_holds_after_a_burst():
    fs = _FS
    burst = make_tone(1000.0, 0.03, fs, amplitude=1.0)
    clip = np.concatenate([burst, np.zeros(int(1.0 * fs))])
    imp = sl.exp_time_weight(clip, fs, "impulse")
    fast = sl.exp_time_weight(clip, fs, "fast")
    at = int(0.3 * fs)  # 300 ms after the burst ends
    assert imp[len(burst) + at] > 20.0 * fast[len(burst) + at]


def test_time_weighted_max():
    x = make_tone(1000.0, 1.0, _FS, amplitude=1.0)
    assert sl.time_weighted_max(x, _FS, "fast") == pytest.approx(10 * np.log10(0.5), abs=0.3)


def test_percentile_levels_ordering():
    fs = _FS
    loud = make_tone(1000.0, 0.6, fs, amplitude=1.0)
    quiet = make_tone(1000.0, 0.6, fs, amplitude=0.1)
    clip = np.concatenate([quiet, loud, quiet, loud])
    ln = sl.percentile_levels(clip, fs, percentiles=(5, 50, 95), mode="fast")
    assert ln[5] > ln[50] > ln[95]      # L5 (loud events) > median > L95 (background)
    assert ln[5] == pytest.approx(10 * np.log10(0.5), abs=1.0)


def test_exp_time_weight_bad_mode():
    with pytest.raises(ValueError):
        sl.exp_time_weight(make_tone(1000.0, 0.2, _FS), _FS, "medium")
