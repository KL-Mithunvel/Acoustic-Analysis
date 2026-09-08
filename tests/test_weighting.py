"""Tests for acoustic_analysis.dsp.weighting."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.dsp import weighting
from acoustic_analysis.dsp.conditioning import rms
from tests.synth import make_tone

_FS = 48000


def _gain_db(kind: str, freq: float) -> float:
    x = make_tone(freq, 0.6, _FS, amplitude=1.0)
    y = weighting.apply_weighting(x, _FS, kind)
    settle = slice(int(0.1 * _FS), -int(0.02 * _FS))  # skip filter start-up
    return 20.0 * np.log10(rms(y[settle]) / rms(x[settle]))


# IEC 61672-1 reference values (dB). Tested where bilinear warping is small.
_A_REF = {250.0: -8.6, 500.0: -3.2, 1000.0: 0.0, 2000.0: 1.2, 4000.0: 1.0}
_C_REF = {250.0: 0.0, 500.0: 0.0, 1000.0: 0.0, 2000.0: -0.2, 4000.0: -0.8}


@pytest.mark.parametrize("freq,expected", list(_A_REF.items()))
def test_a_weighting_matches_iec(freq, expected):
    assert _gain_db("A", freq) == pytest.approx(expected, abs=1.0)


@pytest.mark.parametrize("freq,expected", list(_C_REF.items()))
def test_c_weighting_matches_iec(freq, expected):
    assert _gain_db("C", freq) == pytest.approx(expected, abs=1.0)


def test_a_weighting_is_zero_at_1khz():
    assert _gain_db("A", 1000.0) == pytest.approx(0.0, abs=0.1)


def test_a_weighting_attenuates_low_frequencies():
    assert _gain_db("A", 100.0) < -15.0


def test_z_weighting_is_identity():
    x = make_tone(500.0, 0.2, _FS)
    assert np.array_equal(weighting.apply_weighting(x, _FS, "Z"), x)


def test_bad_kind():
    with pytest.raises(ValueError):
        weighting.apply_weighting(make_tone(1000.0, 0.2, _FS), _FS, "B")


def test_short_input_rejected():
    with pytest.raises(ValueError):
        weighting.apply_weighting(np.zeros(4), _FS, "A")
