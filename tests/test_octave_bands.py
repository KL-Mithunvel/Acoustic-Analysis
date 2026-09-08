"""Tests for acoustic_analysis.dsp.octave_bands."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.dsp import octave_bands as ob
from tests.synth import make_decay, make_multitone, make_tone, make_white_noise


def test_centres_include_reference_and_octave_ratio():
    centres, lower, upper = ob.octave_band_frequencies(1, 100.0, 8000.0)
    # 1000 Hz is a band centre in the base-2 system
    assert np.any(np.isclose(centres, 1000.0))
    # consecutive 1/1-octave centres differ by a factor of 2
    ratios = centres[1:] / centres[:-1]
    assert np.allclose(ratios, 2.0, rtol=1e-6)
    # edges straddle the centre by 2**(+/-1/2)
    i = int(np.argmin(np.abs(centres - 1000.0)))
    assert lower[i] == pytest.approx(1000.0 / np.sqrt(2), rel=1e-6)
    assert upper[i] == pytest.approx(1000.0 * np.sqrt(2), rel=1e-6)


def test_third_octave_step():
    centres, _, _ = ob.octave_band_frequencies(3, 500.0, 2000.0)
    ratios = centres[1:] / centres[:-1]
    assert np.allclose(ratios, 2.0 ** (1 / 3), rtol=1e-6)


def test_invalid_fraction_and_range():
    with pytest.raises(ValueError):
        ob.octave_band_frequencies(5, 100.0, 1000.0)
    with pytest.raises(ValueError):
        ob.octave_band_frequencies(3, 1000.0, 100.0)


def test_tone_energy_lands_in_its_own_band():
    fs = 48000
    x = make_tone(1000.0, 0.5, fs, amplitude=1.0)
    centres, levels = ob.fractional_octave_levels(x, fs, fraction=3, f_min=100.0, f_max=10000.0)
    top = int(np.argmax(levels))
    assert centres[top] == pytest.approx(1000.0, rel=0.06)
    # unit-amplitude sine -> mean square 0.5 -> ~ -3 dB in the winning band
    assert levels[top] == pytest.approx(-3.0, abs=1.0)
    # neighbours at least 15 dB down
    assert levels[top] - levels[top - 1] > 15.0
    assert levels[top] - levels[top + 1] > 15.0


def test_levels_sum_to_signal_mean_square():
    fs = 48000
    x = make_multitone([800.0, 2500.0, 6000.0], [1.0, 0.6, 0.3], 0.5, fs)
    centres, levels = ob.fractional_octave_levels(x, fs, fraction=3, f_min=100.0, f_max=15000.0)
    summed = np.sum(10.0 ** (levels[np.isfinite(levels)] / 10.0))
    expected = np.mean(x**2)
    assert summed == pytest.approx(expected, rel=0.05)


def test_white_noise_octave_levels_rise_with_frequency():
    fs = 48000
    x = make_white_noise(1.0, fs, rms=1.0, seed=7)
    centres, levels = ob.fractional_octave_levels(x, fs, fraction=1, f_min=125.0, f_max=8000.0)
    # constant-percentage bandwidth -> each higher octave is ~3 dB louder for white noise
    assert levels[-1] - levels[0] > 6.0
    assert np.all(np.diff(levels) > 0)


def test_band_shape_is_gain_invariant():
    fs = 48000
    x = make_multitone([800.0, 2500.0], [1.0, 0.5], 0.4, fs)
    _, l1 = ob.fractional_octave_levels(x, fs, fraction=3, f_min=100.0, f_max=12000.0)
    _, l2 = ob.fractional_octave_levels(10.0 * x, fs, fraction=3, f_min=100.0, f_max=12000.0)
    assert np.allclose(ob.band_shape(l1), ob.band_shape(l2), atol=1e-6)


def test_band_ratios_high_low():
    fs = 48000
    bright = make_multitone([500.0, 6000.0], [1.0, 1.0], 0.4, fs)
    dull = make_multitone([500.0, 6000.0], [1.0, 0.1], 0.4, fs)
    cb, lb = ob.fractional_octave_levels(bright, fs, fraction=3, f_min=100.0, f_max=15000.0)
    cd, ld = ob.fractional_octave_levels(dull, fs, fraction=3, f_min=100.0, f_max=15000.0)
    assert ob.band_ratios(cb, lb)["high_to_low"] > ob.band_ratios(cd, ld)["high_to_low"]


def test_fractional_octave_levels_rejects_short_input():
    with pytest.raises(ValueError):
        ob.fractional_octave_levels(np.zeros(8), 48000)


def test_band_shape_all_inf():
    with pytest.raises(ValueError):
        ob.band_shape(np.array([-np.inf, -np.inf]))
