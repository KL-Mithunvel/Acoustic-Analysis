"""Tests for acoustic_analysis.dsp.noise."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.config import load_config
from acoustic_analysis.dsp import noise as nz
from acoustic_analysis.dsp.conditioning import rms
from acoustic_analysis.dsp.spectrum import dominant_frequency, fft_magnitude
from tests.synth import make_tone, make_white_noise

_FS = 48000


@pytest.fixture
def cfg():
    return load_config()


def test_noise_profile_shape(cfg):
    prof = nz.noise_profile(make_white_noise(1.0, _FS, rms=0.05, seed=1), _FS, cfg)
    assert len(prof["octave_levels_db"]) == len(prof["octave_centres_hz"])
    assert np.isfinite(prof["broadband_level_db"])
    assert set(prof["percentile_levels_db"]) == {5, 50, 90, 95}
    assert prof["_magnitude"].shape == prof["_freqs_hz"].shape


def test_reduce_noise_subtraction_improves_snr():
    fs = _FS
    clean = make_tone(1200.0, 1.5, fs, amplitude=0.3)
    noise_a = make_white_noise(1.5, fs, rms=0.15, seed=2)
    noise_b = make_white_noise(1.5, fs, rms=0.15, seed=3)  # independent, same character
    noisy = clean + noise_a

    denoised = nz.reduce_noise(noisy, fs, noise_b, strength=1.5, method="subtraction")

    err_before = rms(noisy - clean)
    err_after = rms(denoised - clean[: denoised.size])
    assert err_after < err_before                     # closer to the clean tone
    # tone survives
    f, m = fft_magnitude(denoised, fs)
    assert dominant_frequency(f, m, fmin=100.0) == pytest.approx(1200.0, abs=5.0)


def test_reduce_noise_gate_runs_and_preserves_tone():
    fs = _FS
    noisy = make_tone(1000.0, 1.2, fs, amplitude=0.4) + make_white_noise(1.2, fs, rms=0.1, seed=4)
    noise_ref = make_white_noise(1.2, fs, rms=0.1, seed=5)
    out = nz.reduce_noise(noisy, fs, noise_ref, strength=1.0, method="gate")
    f, m = fft_magnitude(out, fs)
    assert dominant_frequency(f, m, fmin=100.0) == pytest.approx(1000.0, abs=6.0)


def test_reduce_noise_bad_method():
    x = make_white_noise(0.2, _FS, seed=6)
    with pytest.raises(ValueError):
        nz.reduce_noise(x, _FS, x, method="magic")
