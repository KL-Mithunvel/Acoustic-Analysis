"""Tests for acoustic_analysis.io.wavstore."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.io import wavstore
from tests.synth import make_tone

_FS = 48000


def test_round_trip_preserves_signal_and_metadata(tmp_path):
    x = make_tone(1000.0, 0.25, _FS, amplitude=0.5)
    path = wavstore.save_clip(x, _FS, tmp_path / "clips" / "c1.wav", metadata={"tile_id": "A1"})
    assert path.exists()
    assert path.with_suffix(".wav.json").exists()

    y, fs, meta = wavstore.load_clip(path)
    assert fs == _FS
    assert y.shape == x.shape
    np.testing.assert_allclose(y, x, atol=1e-6)
    assert meta["tile_id"] == "A1"
    assert meta["sample_rate"] == _FS
    assert meta["n_samples"] == x.size


def test_stereo_is_averaged_to_mono(tmp_path):
    import soundfile as sf

    stereo = np.stack([make_tone(500.0, 0.1, _FS), make_tone(500.0, 0.1, _FS)], axis=1)
    p = tmp_path / "st.wav"
    sf.write(p, stereo.astype(np.float32), _FS, subtype="FLOAT")
    y, fs, meta = wavstore.load_clip(p)
    assert y.ndim == 1
    assert meta == {}  # no sidecar


def test_missing_file_raises(tmp_path):
    with pytest.raises(Exception):
        wavstore.load_clip(tmp_path / "nope.wav")
