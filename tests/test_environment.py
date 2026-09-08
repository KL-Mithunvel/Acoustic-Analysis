"""Tests for acoustic_analysis.dsp.environment."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.config import load_config
from acoustic_analysis.dsp import environment as env
from tests.synth import make_multitone, make_tone, make_white_noise

_FS = 48000
_NC_BANDS = [63.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0]


def test_nc_rating_recovers_a_known_curve():
    nc30 = [57, 48, 41, 35, 31, 29, 28, 27]
    value, limiting = env.nc_rating(_NC_BANDS, nc30)
    assert value == pytest.approx(30.0, abs=0.5)
    assert limiting in _NC_BANDS


def test_nc_rating_clamps_below_range():
    very_quiet = [10, 5, 2, 0, -5, -8, -10, -12]
    value, _ = env.nc_rating(_NC_BANDS, very_quiet)
    assert value == pytest.approx(15.0, abs=0.1)  # clamped to the lowest curve


def test_nc_rating_all_nan_raises():
    with pytest.raises(ValueError):
        env.nc_rating(_NC_BANDS, [np.nan] * 8)


def test_dominant_tones_finds_the_tone():
    x = make_tone(440.0, 1.0, _FS, amplitude=0.5) + make_white_noise(1.0, _FS, rms=0.02, seed=1)
    tones = env.dominant_tones(x, _FS, count=3, min_prominence_db=6.0)
    assert tones
    assert any(abs(t["freq_hz"] - 440.0) < 5.0 for t in tones)
    assert tones[0]["prominence_db"] >= 6.0


def test_dominant_tones_empty_for_pure_noise():
    x = make_white_noise(1.0, _FS, rms=0.1, seed=2)
    tones = env.dominant_tones(x, _FS, count=5, min_prominence_db=15.0)
    assert tones == []


def test_environmental_analysis_shape():
    cfg = load_config()
    x = make_multitone([120.0, 500.0, 2000.0], [0.3, 0.2, 0.1], 2.0, _FS)
    x = x + make_white_noise(2.0, _FS, rms=0.02, seed=3)
    result = env.environmental_analysis(x, _FS, cfg)
    assert result["l10_db"] > result["l50_db"] > result["l90_db"]
    assert len(result["octave_levels_db"]) == len(result["octave_centres_hz"])
    assert "nc_rating" in result
    assert isinstance(result["tones"], list)
