"""One strike clip in, everything the Test Tile screen shows out. Pure: arrays and dicts, no GUI, no hardware.

``analyse_strike`` is the whole pipeline for a clip cut around the Nano's strike: the strike features
(``strike_features``), the grade against the good-tile reference (``strike_reference``) and the curves to
plot. The screen only calls this and draws the result, so the same function can be run on a saved WAV.
"""

from __future__ import annotations

import numpy as np

from .strike_features import ring_envelope_db, ring_spectrum, strike_features, zoom_window
from .strike_reference import StrikeReference, grade_strike

# Strikes that are a tile's tap. "rest" (the striker lowering itself) and "safety" (a forced release) are not.
GRADED_SOURCES = ("tof", "manual")


def is_graded_source(src: str | None) -> bool:
    """A 4-field TAP has no source and is a ToF strike."""
    return src is None or src in GRADED_SOURCES


def analyse_strike(x: np.ndarray, fs: int, cfg: dict, reference: StrikeReference | None,
                   tile_present: bool | None = None) -> dict:
    """``{"features", "verdict", "spec", "env", "wave"}`` for one clip (strike expected ~``strike.expect_s`` in)."""
    x = np.asarray(x, float)
    feat = strike_features(x, fs, cfg)
    return {
        "features": feat,
        "verdict": grade_strike(feat, reference, cfg, tile_present),
        "spec": ring_spectrum(x, fs, cfg),
        "env": ring_envelope_db(x, fs, cfg),
        "wave": zoom_window(x, fs, cfg),
    }
