"""Tests for acoustic_analysis.dsp.filters."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.config import load_config
from acoustic_analysis.dsp.conditioning import rms
from acoustic_analysis.dsp.filters import FilterChain
from tests.synth import make_multitone, make_tone

_FS = 48000


def test_bandpass_stage_passes_and_rejects():
    chain = FilterChain(bandpass=(300.0, 18000.0), bandpass_order=4)
    assert rms(chain.apply(make_tone(2000.0, 0.5, _FS), _FS)) > 0.6
    assert rms(chain.apply(make_tone(60.0, 0.5, _FS), _FS)) < 0.05


def test_notch_removes_its_frequency_only():
    chain = FilterChain(notches=[(1000.0, 30.0)])
    killed = chain.apply(make_tone(1000.0, 0.5, _FS), _FS)
    kept = chain.apply(make_tone(1300.0, 0.5, _FS), _FS)
    assert rms(killed) < 0.2
    assert rms(kept) > 0.6


def test_weighting_stage_attenuates_lows():
    chain = FilterChain(weighting="A")
    low = rms(chain.apply(make_tone(80.0, 0.5, _FS), _FS))
    mid = rms(chain.apply(make_tone(1000.0, 0.5, _FS), _FS))
    assert 20 * np.log10(low / mid) < -15.0


def test_frequency_response_shape_and_values():
    chain = FilterChain(bandpass=(300.0, 18000.0))
    freqs, mag_db = chain.frequency_response(_FS, n=4096)
    assert freqs.shape == mag_db.shape
    passband = mag_db[np.argmin(np.abs(freqs - 2000.0))]
    stopband = mag_db[np.argmin(np.abs(freqs - 50.0))]
    assert passband == pytest.approx(0.0, abs=1.0)
    assert stopband < -20.0


def test_full_chain_from_config():
    cfg = load_config()
    chain = FilterChain.from_config(cfg)
    assert chain.bandpass == (300.0, 18000.0)
    y = chain.apply(make_multitone([120.0, 2000.0], [1.0, 1.0], 0.5, _FS), _FS)
    assert rms(y) < rms(make_multitone([120.0, 2000.0], [1.0, 1.0], 0.5, _FS))  # 120 Hz removed
    assert isinstance(chain.describe(), list) and chain.describe()


def test_bad_band_raises():
    with pytest.raises(ValueError):
        FilterChain(bandpass=(18000.0, 300.0)).apply(np.zeros(4000), _FS)


def test_bad_notch_raises():
    with pytest.raises(ValueError):
        FilterChain(notches=[(1000.0, -1.0)]).apply(np.zeros(4000), _FS)
