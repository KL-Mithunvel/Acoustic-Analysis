"""Tests for acoustic_analysis.features."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.config import load_config
from acoustic_analysis.features import extract_features

_FS = 48000


def _synth_clip(dominant, extra_freqs, tau, hi_gain, dur=0.6, pre_ms=100.0, noise=1e-4, seed=0):
    """Tap-test-shaped clip: quiet pre-roll, sharp onset, decaying multi-mode ring."""
    rng = np.random.default_rng(seed)
    n = int(dur * _FS)
    n_pre = int(pre_ms / 1000.0 * _FS)
    clip = rng.normal(0.0, noise, n)
    t = np.arange(n - n_pre) / _FS
    ring = np.exp(-t / tau) * np.sin(2 * np.pi * dominant * t)
    for f in extra_freqs:
        ring += hi_gain * np.exp(-t / tau) * np.sin(2 * np.pi * f * t)
    ring[: int(0.001 * _FS)] += 0.4
    clip[n_pre:] += ring
    return clip.astype(np.float64)


@pytest.fixture
def cfg():
    return load_config()


def test_good_vs_cracked_feature_deltas(cfg):
    good = _synth_clip(1800.0, [4200.0, 8000.0], tau=0.10, hi_gain=0.6, seed=1)
    cracked = _synth_clip(1400.0, [3000.0], tau=0.03, hi_gain=0.15, seed=2)

    fg = extract_features(good, _FS, cfg)
    fc = extract_features(cracked, _FS, cfg)

    assert fg["valid"] and fg["status"] == "OK"
    assert fc["valid"] and fc["status"] == "OK"

    assert fg["dominant_freq_hz"] == pytest.approx(1800.0, abs=40.0)
    assert fc["dominant_freq_hz"] == pytest.approx(1400.0, abs=40.0)

    assert fg["t30_s"] is not None and fc["t30_s"] is not None
    assert fg["t30_s"] > fc["t30_s"]                      # good rings longer
    assert fg["decay_rate_db_s"] > fc["decay_rate_db_s"]  # cracked decays faster (more negative)
    assert fg["spectral_centroid_hz"] > fc["spectral_centroid_hz"]
    assert fg["band_ratios"]["high_to_low"] > fc["band_ratios"]["high_to_low"]


def test_feature_dict_is_serialisable_shape(cfg):
    f = extract_features(_synth_clip(2000.0, [5000.0], tau=0.1, hi_gain=0.5, seed=3), _FS, cfg)
    assert len(f["octave_band_shape_db"]) == len(f["octave_centres_hz"])
    assert set(f["band_ratios"]) == {"high_to_low", "mid_to_low", "high_to_total"}
    assert isinstance(f["peaks"], list) and f["peaks"]
    assert set(f["time_to_drop_s"]) == {10, 20, 30}


def test_no_impact_is_retest(cfg):
    rng = np.random.default_rng(0)
    quiet = rng.normal(0.0, 1e-4, int(0.6 * _FS))
    f = extract_features(quiet, _FS, cfg)
    assert f["valid"] is False
    assert f["status"] == "RETEST"
    assert f["impact_index"] is None
    assert any("impact" in r for r in f["reasons"])


def test_low_snr_is_retest(cfg):
    fs = _FS
    n = int(0.6 * fs)
    n_pre = int(0.1 * fs)
    rng = np.random.default_rng(5)
    clip = rng.normal(0.0, 0.01, n)          # loud background
    clip[n_pre : n_pre + 40] += 0.2          # a click that still crosses the trigger
    t = np.arange(n - n_pre) / fs
    clip[n_pre:] += 0.012 * np.exp(-t / 0.05) * np.sin(2 * np.pi * 2000 * t)  # ring near noise

    f = extract_features(clip, fs, cfg)
    assert f["impact_index"] is not None
    assert f["status"] == "RETEST"
    assert any("SNR" in r for r in f["reasons"])


def test_clip_too_short_raises(cfg):
    with pytest.raises(ValueError):
        extract_features(np.zeros(100), _FS, cfg)
