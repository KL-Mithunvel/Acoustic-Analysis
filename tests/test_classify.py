"""Tests for acoustic_analysis.classify (reference + rules)."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.classify.reference import ReferenceProfile
from acoustic_analysis.classify.rules import grade
from acoustic_analysis.config import load_config
from acoustic_analysis.features import extract_features

_FS = 48000


def _clip(dominant, extras, tau, hi_gain, seed):
    rng = np.random.default_rng(seed)
    n, n_pre = int(0.6 * _FS), int(0.1 * _FS)
    clip = rng.normal(0.0, 1e-4, n)
    t = np.arange(n - n_pre) / _FS
    ring = np.exp(-t / tau) * np.sin(2 * np.pi * dominant * t)
    for f in extras:
        ring += hi_gain * np.exp(-t / tau) * np.sin(2 * np.pi * f * t)
    ring[: int(0.001 * _FS)] += 0.4
    clip[n_pre:] += ring
    return clip.astype(np.float64)


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def profile(cfg):
    goods = [
        extract_features(
            _clip(1800.0 + rng, [4200.0, 8000.0], 0.10 + 0.004 * i, 0.6, seed=i), _FS, cfg
        )
        for i, rng in enumerate((0, 8, -6, 5, -3, 2))
    ]
    return ReferenceProfile.build(goods, part_type="test-tile")


def test_build_requires_enough_samples(cfg):
    with pytest.raises(ValueError):
        ReferenceProfile.build([{"valid": True}, {"valid": True}])


def test_profile_has_expected_stats(profile):
    assert profile.n == 6
    assert "dominant_freq_hz" in profile.stats
    assert profile.stats["dominant_freq_hz"]["mean"] == pytest.approx(1800.0, abs=20.0)
    assert profile.octave_centres and len(profile.shape_mean) == len(profile.octave_centres)


def test_good_clip_grades_good(profile, cfg):
    f = extract_features(_clip(1800.0, [4200.0, 8000.0], 0.10, 0.6, seed=99), _FS, cfg)
    result = grade(f, profile, cfg)
    assert result["grade"] == "GOOD"
    assert result["deviation"] is not None


def test_cracked_clip_grades_defective(profile, cfg):
    f = extract_features(_clip(1400.0, [3000.0], 0.03, 0.15, seed=42), _FS, cfg)
    result = grade(f, profile, cfg)
    assert result["grade"] == "DEFECTIVE"
    assert result["reasons"]


def test_invalid_features_are_retest(profile, cfg):
    result = grade({"valid": False, "reasons": ["no impact detected"]}, profile, cfg)
    assert result["grade"] == "RETEST"


def test_no_profile_is_ungraded(cfg):
    f = extract_features(_clip(1800.0, [4200.0], 0.10, 0.6, seed=7), _FS, cfg)
    assert grade(f, None, cfg)["grade"] == "UNGRADED"


def test_profile_save_load_round_trip(profile, tmp_path, cfg):
    p = profile.save(tmp_path / "ref.json")
    loaded = ReferenceProfile.load(p)
    f = extract_features(_clip(1800.0, [4200.0, 8000.0], 0.10, 0.6, seed=5), _FS, cfg)
    assert loaded.compare(f)["aggregate"] == pytest.approx(profile.compare(f)["aggregate"], rel=1e-6)
