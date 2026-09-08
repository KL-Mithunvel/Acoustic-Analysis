"""Tests for acoustic_analysis.dsp.decay."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.dsp import decay
from tests.synth import make_decay, make_tone

# For A*e^(-t/tau): envelope drops 20/ln(10) ~= 8.6859 dB per tau.
_DB_PER_TAU = 20.0 / np.log(10.0)


def test_time_to_drop_matches_exponential():
    fs = 48000
    tau = 0.15
    x = make_decay(2000.0, tau, 0.6, fs)
    t20 = decay.time_to_drop(x, fs, 20.0)
    assert t20 == pytest.approx(tau * 20.0 / _DB_PER_TAU, rel=0.08)


def test_time_to_drop_returns_none_when_never_reached():
    fs = 48000
    x = make_decay(2000.0, tau_s=5.0, duration_s=0.2, sample_rate=fs)  # barely decays
    assert decay.time_to_drop(x, fs, 30.0) is None


def test_time_to_drop_bad_db():
    with pytest.raises(ValueError):
        decay.time_to_drop(make_tone(1000.0, 0.1, 48000), 48000, 0.0)


def test_reverb_time_extrapolates_to_60db():
    fs = 48000
    tau = 0.12
    x = make_decay(1500.0, tau, 0.7, fs)
    t20 = decay.reverb_time(x, fs, 20.0)
    expected = (tau * 20.0 / _DB_PER_TAU) * 3.0
    assert t20 == pytest.approx(expected, rel=0.1)


def test_decay_rate_matches_exponential_slope():
    fs = 48000
    tau = 0.15
    x = make_decay(2000.0, tau, 0.8, fs)
    rate = decay.decay_rate(x, fs, fit_drop_db=30.0)
    assert rate == pytest.approx(-_DB_PER_TAU / tau, rel=0.1)


def test_decay_rate_faster_for_shorter_tau():
    fs = 48000
    fast = decay.decay_rate(make_decay(2000.0, 0.05, 0.8, fs), fs)
    slow = decay.decay_rate(make_decay(2000.0, 0.30, 0.8, fs), fs)
    assert fast < slow < 0


def test_decay_rate_silent_raises():
    with pytest.raises(ValueError):
        decay.decay_rate(np.zeros(4800), 48000)


def test_envelope_needs_two_samples():
    with pytest.raises(ValueError):
        decay.envelope(np.array([1.0]))


def test_per_band_decay_isolates_the_fast_band():
    fs = 48000
    dur = 0.7
    fast_band = make_decay(1000.0, 0.05, dur, fs, amplitude=1.0)
    slow_band = make_decay(5000.0, 0.30, dur, fs, amplitude=1.0)
    x = fast_band + slow_band

    centres, rates = decay.per_band_decay(x, fs, fraction=3, f_min=500.0, f_max=8000.0)
    i_fast = int(np.argmin(np.abs(centres - 1000.0)))
    i_slow = int(np.argmin(np.abs(centres - 5000.0)))
    assert np.isfinite(rates[i_fast]) and np.isfinite(rates[i_slow])
    assert rates[i_fast] < rates[i_slow]          # 1 kHz band collapses faster
    assert rates[i_fast] < -100.0                 # steep
