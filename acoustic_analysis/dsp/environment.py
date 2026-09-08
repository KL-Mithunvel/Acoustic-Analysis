"""Environmental noise analysis (docs/METHODS.md, docs/UI_DESIGN.md Noise).

For a longer recording of a room or a machine bay: the octave spectrum, the
statistical levels, a Noise Criterion (NC) rating, and the discrete tones that
stand out of the broadband floor.
"""

from __future__ import annotations

import numpy as np

from . import octave_bands as _ob
from . import sound_level as _sl
from . import spectrum as _spec

# NC curves - octave-band SPL limits (dB) at 63 .. 8000 Hz.
_NC_BANDS = np.array([63.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0])
_NC_CURVES: dict[int, list[float]] = {
    15: [47, 36, 29, 22, 17, 14, 12, 11],
    20: [51, 40, 33, 26, 22, 19, 17, 16],
    25: [54, 44, 37, 31, 27, 24, 22, 21],
    30: [57, 48, 41, 35, 31, 29, 28, 27],
    35: [60, 52, 45, 40, 36, 34, 33, 32],
    40: [64, 56, 50, 45, 41, 39, 38, 37],
    45: [67, 60, 54, 49, 46, 44, 43, 42],
    50: [71, 64, 58, 54, 51, 49, 48, 47],
    55: [74, 67, 62, 58, 56, 54, 53, 52],
    60: [77, 71, 67, 63, 61, 59, 58, 57],
    65: [80, 75, 71, 68, 66, 64, 63, 62],
    70: [83, 79, 75, 72, 71, 70, 69, 68],
}


def nc_rating(octave_centres, octave_levels_db) -> tuple[float, float]:
    """Noise Criterion rating by the tangency method.

    For each of the 63-8000 Hz octave bands, interpolate the measured level onto
    the family of NC curves to get that band's NC contribution; the rating is
    the maximum across bands. Returns ``(nc_value, limiting_band_hz)``.
    """
    centres = np.asarray(octave_centres, dtype=np.float64)
    levels = np.asarray(octave_levels_db, dtype=np.float64)
    nc_keys = np.array(sorted(_NC_CURVES))
    curve_matrix = np.array([_NC_CURVES[k] for k in nc_keys])  # (n_nc, 8)

    per_band = []
    for i, band in enumerate(_NC_BANDS):
        j = int(np.argmin(np.abs(centres - band)))
        if not np.isfinite(levels[j]):
            continue
        nc_i = float(np.interp(levels[j], curve_matrix[:, i], nc_keys))
        per_band.append((nc_i, band))
    if not per_band:
        raise ValueError("nc_rating: no finite octave levels in the 63-8000 Hz range")

    nc_value, limiting = max(per_band, key=lambda p: p[0])
    return round(nc_value, 1), float(limiting)


def dominant_tones(
    x: np.ndarray, fs: float, count: int = 5, min_prominence_db: float = 6.0, fmin: float = 20.0
) -> list[dict]:
    """Discrete tones that rise ``min_prominence_db`` above the local spectrum.

    Prominence is measured against a median-filtered version of the magnitude
    spectrum. Returns up to ``count`` dicts ``{freq_hz, level_db, prominence_db}``
    sorted by descending prominence.
    """
    freqs, mag = _spec.fft_magnitude(np.asarray(x, dtype=np.float64), fs)
    mag_db = 20.0 * np.log10(np.maximum(mag, 1e-12))

    k = max(3, int(round(len(mag_db) / 200)) | 1)  # odd window
    pad = k // 2
    padded = np.pad(mag_db, pad, mode="edge")
    local = np.array([np.median(padded[i : i + k]) for i in range(len(mag_db))])
    prominence = mag_db - local

    candidates = []
    for i in range(1, len(mag_db) - 1):
        if (
            freqs[i] >= fmin
            and mag_db[i] > mag_db[i - 1]
            and mag_db[i] >= mag_db[i + 1]
            and prominence[i] >= min_prominence_db
        ):
            candidates.append(
                {
                    "freq_hz": round(float(freqs[i]), 2),
                    "level_db": round(float(mag_db[i]), 2),
                    "prominence_db": round(float(prominence[i]), 2),
                }
            )
    candidates.sort(key=lambda c: c["prominence_db"], reverse=True)
    return candidates[:count]


def environmental_analysis(x: np.ndarray, fs: float, cfg: dict) -> dict:
    """Full environmental-noise summary for a room / machine recording."""
    x = np.asarray(x, dtype=np.float64)
    env = cfg.get("environment", {})
    ref_p = cfg["octave"].get("reference_pressure_pa") if cfg["calibration"].get("enabled") else None

    centres, levels = _ob.fractional_octave_levels(
        x, fs, fraction=1, f_min=45.0, f_max=11000.0, ref_pressure=ref_p
    )
    ln = _sl.percentile_levels(x, fs, (10, 50, 90), "fast", ref_p)

    out: dict = {
        "duration_s": round(x.size / fs, 3),
        "leq_db": round(_sl.leq(x, ref_pressure=ref_p), 2),
        "l10_db": round(ln[10], 2),
        "l50_db": round(ln[50], 2),
        "l90_db": round(ln[90], 2),
        "octave_centres_hz": [round(float(c), 2) for c in centres],
        "octave_levels_db": [None if not np.isfinite(v) else round(float(v), 2) for v in levels],
        "tones": dominant_tones(
            x, fs,
            count=int(env.get("tone_count", 5)),
            min_prominence_db=float(env.get("tone_min_prominence_db", 6.0)),
        ),
    }
    if env.get("nc_report", True):
        try:
            nc_value, limiting = nc_rating(centres, levels)
            out["nc_rating"] = nc_value
            out["nc_limiting_band_hz"] = limiting
        except ValueError:
            out["nc_rating"] = None
            out["nc_limiting_band_hz"] = None
    return out
