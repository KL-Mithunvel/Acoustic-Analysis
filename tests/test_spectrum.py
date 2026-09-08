"""Tests for acoustic_analysis.dsp.spectrum."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.dsp import spectrum as spec
from tests.synth import make_multitone, make_tone, make_white_noise


def test_fft_magnitude_recovers_frequency_and_amplitude():
    fs = 48000
    x = make_tone(1000.0, 0.5, fs, amplitude=0.8)
    freqs, mag = spec.fft_magnitude(x, fs)
    peak = freqs[np.argmax(mag)]
    assert peak == pytest.approx(1000.0, abs=5.0)
    assert mag.max() == pytest.approx(0.8, rel=0.05)


def test_fft_magnitude_too_short():
    with pytest.raises(ValueError):
        spec.fft_magnitude(np.array([1.0]), 48000)


def test_dominant_frequency_ignores_dc():
    fs = 48000
    x = make_tone(2500.0, 0.3, fs) + 5.0  # big DC offset
    freqs, mag = spec.fft_magnitude(x, fs)
    assert spec.dominant_frequency(freqs, mag, fmin=20.0) == pytest.approx(2500.0, abs=5.0)


def test_pick_peaks_finds_both_tones_in_order():
    fs = 48000
    x = make_multitone([1000.0, 3000.0], [1.0, 0.5], 0.5, fs)
    freqs, mag = spec.fft_magnitude(x, fs)
    peaks = spec.pick_peaks(freqs, mag, n_peaks=2, fmin=100.0, fmax=20000.0)
    assert len(peaks) == 2
    assert peaks[0]["freq"] == pytest.approx(1000.0, abs=5.0)
    assert peaks[1]["freq"] == pytest.approx(3000.0, abs=5.0)
    assert peaks[0]["amplitude"] > peaks[1]["amplitude"]
    assert peaks[0]["q"] is not None and peaks[0]["q"] > 20.0


def test_pick_peaks_clamps_n_peaks_to_available():
    fs = 48000
    x = make_tone(1500.0, 0.3, fs)
    freqs, mag = spec.fft_magnitude(x, fs)
    peaks = spec.pick_peaks(freqs, mag, n_peaks=10, fmin=100.0)
    assert 1 <= len(peaks) <= 10
    assert peaks[0]["freq"] == pytest.approx(1500.0, abs=5.0)


def test_spectral_centroid_of_single_tone_is_that_tone():
    fs = 48000
    freqs, mag = spec.fft_magnitude(make_tone(1000.0, 0.3, fs), fs)
    assert spec.spectral_centroid(freqs, mag) == pytest.approx(1000.0, abs=30.0)


def test_spectral_centroid_between_two_tones():
    fs = 48000
    freqs, mag = spec.fft_magnitude(make_multitone([500.0, 5000.0], [1.0, 1.0], 0.3, fs), fs)
    c = spec.spectral_centroid(freqs, mag)
    assert 2000.0 < c < 3500.0


def test_spectral_bandwidth_wider_for_two_spread_tones():
    fs = 48000
    freqs1, mag1 = spec.fft_magnitude(make_tone(2000.0, 0.3, fs), fs)
    freqs2, mag2 = spec.fft_magnitude(
        make_multitone([500.0, 8000.0], [1.0, 1.0], 0.3, fs), fs
    )
    assert spec.spectral_bandwidth(freqs2, mag2) > 5 * spec.spectral_bandwidth(freqs1, mag1)


def test_spectral_rolloff_passes_the_high_tone():
    fs = 48000
    freqs, mag = spec.fft_magnitude(make_multitone([500.0, 5000.0], [1.0, 1.0], 0.3, fs), fs)
    assert spec.spectral_rolloff(freqs, mag, 0.85) > 4000.0


def test_spectral_rolloff_bad_fraction():
    freqs, mag = spec.fft_magnitude(make_tone(1000.0, 0.1, 48000), 48000)
    with pytest.raises(ValueError):
        spec.spectral_rolloff(freqs, mag, 1.5)


def test_spectral_flatness_tone_low_noise_high():
    fs = 48000
    _, mag_tone = spec.fft_magnitude(make_tone(1000.0, 0.3, fs), fs)
    _, mag_noise = spec.fft_magnitude(make_white_noise(0.3, fs, rms=1.0, seed=3), fs)
    assert spec.spectral_flatness(mag_tone) < 0.05
    assert spec.spectral_flatness(mag_noise) > 0.3


def test_spectral_centroid_zero_energy():
    with pytest.raises(ValueError):
        spec.spectral_centroid(np.array([0.0, 1.0, 2.0]), np.zeros(3))
