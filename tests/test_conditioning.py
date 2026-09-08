"""Tests for acoustic_analysis.dsp.conditioning."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.dsp import conditioning as cond
from tests.synth import make_impact_clip, make_tone, make_white_noise


def test_rms_of_unit_sine_is_root_half():
    x = make_tone(1000, 0.5, 48000, amplitude=1.0)
    assert cond.rms(x) == pytest.approx(1 / np.sqrt(2), rel=1e-3)


def test_rms_empty():
    with pytest.raises(ValueError):
        cond.rms(np.array([]))


def test_remove_dc_centres_waveform():
    x = make_tone(100, 0.1, 48000) + 3.0
    assert cond.remove_dc(x).mean() == pytest.approx(0.0, abs=1e-9)


def test_remove_dc_empty():
    with pytest.raises(ValueError):
        cond.remove_dc(np.array([]))


def test_apply_calibration_none_is_identity():
    x = make_tone(100, 0.05, 48000)
    assert np.array_equal(cond.apply_calibration(x, None), x)


def test_apply_calibration_scales_to_pascals():
    x = make_tone(100, 0.05, 48000)
    assert np.allclose(cond.apply_calibration(x, 4.0), x / 4.0)


def test_apply_calibration_rejects_nonpositive():
    with pytest.raises(ValueError):
        cond.apply_calibration(np.ones(10), 0.0)


def test_bandpass_passes_in_band_and_rejects_out_of_band():
    fs = 48000
    y_in = cond.bandpass(make_tone(2000, 0.5, fs), fs, 300, 18000)
    y_low = cond.bandpass(make_tone(50, 0.5, fs), fs, 300, 18000)
    y_high = cond.bandpass(make_tone(22000, 0.5, fs), fs, 300, 18000)
    assert cond.rms(y_in) > 0.6           # essentially unchanged
    assert cond.rms(y_low) < 0.05         # rumble strongly attenuated
    assert cond.rms(y_high) < 0.05        # HF hiss strongly attenuated


def test_bandpass_rejects_bad_band():
    with pytest.raises(ValueError):
        cond.bandpass(np.zeros(4000), 48000, 18000, 300)


def test_bandpass_rejects_short_input():
    with pytest.raises(ValueError):
        cond.bandpass(np.zeros(10), 48000, 300, 18000)


def test_detect_impact_locates_onset():
    fs = 48000
    clip, n_pre = make_impact_clip(fs, pre_ms=100, tau_s=0.15, noise_rms=1e-4, seed=1)
    idx = cond.detect_impact(clip, n_pre, threshold_mult=5.0)
    assert abs(idx - n_pre) < int(0.005 * fs)


def test_detect_impact_no_strike_raises():
    fs = 48000
    quiet = make_white_noise(0.3, fs, rms=1e-4, seed=2)
    with pytest.raises(ValueError):
        cond.detect_impact(quiet, int(0.1 * fs), threshold_mult=50.0)


def test_detect_impact_silent_preroll_raises():
    x = np.concatenate([np.zeros(1000), np.ones(1000)])
    with pytest.raises(ValueError):
        cond.detect_impact(x, 1000)


def test_detect_impact_pre_samples_out_of_range():
    with pytest.raises(ValueError):
        cond.detect_impact(np.ones(100), 100)


def test_window_relative_slices_from_impact():
    fs = 48000
    x = np.arange(fs, dtype=float)
    w = cond.window_relative(x, 1000, fs, 0, 10)
    assert w[0] == 1000
    assert len(w) == int(round(0.01 * fs))


def test_window_relative_clamps_to_bounds():
    fs = 48000
    x = np.arange(2000, dtype=float)
    w = cond.window_relative(x, 1500, fs, 0, 100)  # would end past the array
    assert w[0] == 1500
    assert w[-1] == 1999


def test_window_relative_rejects_empty_range():
    with pytest.raises(ValueError):
        cond.window_relative(np.arange(100.0), 10, 48000, 5, 5)
