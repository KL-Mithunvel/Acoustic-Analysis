"""Fractional-octave-band analysis (docs/METHODS.md section 3.1).

Band centre frequencies and edges follow the base-2 (G = 2) system of
IEC 61260-1 / ANSI S1.11, referenced to 1000 Hz. Band levels are computed by
integrating the windowed power spectrum over each band - an FFT approximation
of a 1/N-octave filter bank, which is accurate enough for a feature vector and
far simpler to test than a real per-band Butterworth bank.
"""

from __future__ import annotations

import numpy as np

_G = 2.0          # octave frequency ratio (base-2 system)
_F_REF = 1000.0   # reference frequency
_VALID_FRACTIONS = (1, 3, 6, 12)


def octave_band_frequencies(
    fraction: int, f_min: float, f_max: float, f_ref: float = _F_REF
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centre, lower-edge and upper-edge frequencies for every 1/``fraction``
    octave band whose centre lies in ``[f_min, f_max]``.

    Returns ``(centres, lower_edges, upper_edges)`` as ascending arrays.
    """
    if fraction not in _VALID_FRACTIONS:
        raise ValueError(f"fraction must be one of {_VALID_FRACTIONS}")
    if not (0 < f_min < f_max):
        raise ValueError("octave_band_frequencies: need 0 < f_min < f_max")

    n = fraction
    x_lo = int(np.floor(n * np.log2(f_min / f_ref)))
    x_hi = int(np.ceil(n * np.log2(f_max / f_ref)))
    x = np.arange(x_lo, x_hi + 1)
    centres = f_ref * _G ** (x / n)
    half_step = _G ** (1.0 / (2 * n))
    lower = centres / half_step
    upper = centres * half_step

    keep = (centres >= f_min) & (centres <= f_max)
    return centres[keep], lower[keep], upper[keep]


def fractional_octave_levels(
    x: np.ndarray,
    fs: float,
    fraction: int = 3,
    f_min: float = 25.0,
    f_max: float = 20000.0,
    ref_pressure: float | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Band levels in dB for a clip.

    With ``ref_pressure`` (e.g. 20e-6 Pa) and a calibrated signal in pascals the
    result is dB SPL per band; without it the result is dB relative to unit
    amplitude. Bands with no energy come back as ``-inf``.

    Returns ``(centres, levels_db)``.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size < 16:
        raise ValueError("fractional_octave_levels: input too short")

    nyq = 0.5 * fs
    centres, lower, upper = octave_band_frequencies(fraction, f_min, min(f_max, 0.99 * nyq))
    if centres.size == 0:
        raise ValueError("fractional_octave_levels: no bands in range")

    n = x.size
    w = np.hanning(n)
    mag2 = np.abs(np.fft.rfft(x * w)) ** 2
    mag2[1:] *= 2.0  # one-sided (Nyquist double is negligible)
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    # scale so summing mag2 reproduces the mean square of x (undo window energy)
    scale = 1.0 / (n**2 * np.mean(w**2))
    ref2 = (ref_pressure**2) if ref_pressure else 1.0

    levels = np.full(centres.size, -np.inf)
    for i in range(centres.size):
        band = (freqs >= lower[i]) & (freqs < upper[i])
        mean_square = scale * mag2[band].sum()
        if mean_square > 0:
            levels[i] = 10.0 * np.log10(mean_square / ref2)
    return centres, levels


def band_shape(levels_db: np.ndarray) -> np.ndarray:
    """Re-reference band levels to the overall level, so total gain drops out.

    The result is the spectral *shape* - what discriminates a clean ring from a
    dull one regardless of how hard the part was struck or the mic gain.
    """
    levels_db = np.asarray(levels_db, dtype=np.float64)
    finite = levels_db[np.isfinite(levels_db)]
    if finite.size == 0:
        raise ValueError("band_shape: every band level is -inf")
    total_db = 10.0 * np.log10(np.sum(10.0 ** (finite / 10.0)))
    return levels_db - total_db


def band_power_in_range(
    centres: np.ndarray, levels_db: np.ndarray, f_lo: float, f_hi: float
) -> float:
    """Summed linear power of the bands whose centre is in ``[f_lo, f_hi)``."""
    centres = np.asarray(centres, dtype=np.float64)
    levels_db = np.asarray(levels_db, dtype=np.float64)
    mask = (centres >= f_lo) & (centres < f_hi) & np.isfinite(levels_db)
    return float(np.sum(10.0 ** (levels_db[mask] / 10.0)))


def band_ratios(
    centres: np.ndarray,
    levels_db: np.ndarray,
    low: tuple[float, float] = (0.0, 1000.0),
    mid: tuple[float, float] = (1000.0, 3000.0),
    high: tuple[float, float] = (3000.0, 1.0e9),
) -> dict:
    """Energy ratios between low / mid / high band groups.

    A crack drains the high bands, so ``high_to_low`` and ``high_to_total`` fall.
    """
    eps = 1.0e-30
    lo = band_power_in_range(centres, levels_db, *low)
    md = band_power_in_range(centres, levels_db, *mid)
    hi = band_power_in_range(centres, levels_db, *high)
    total = lo + md + hi
    return {
        "high_to_low": hi / (lo + eps),
        "mid_to_low": md / (lo + eps),
        "high_to_total": hi / (total + eps),
    }
