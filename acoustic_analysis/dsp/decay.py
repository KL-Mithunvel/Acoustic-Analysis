"""Decay / damping analysis (docs/METHODS.md section 3.3).

A sound part rings; a cracked one damps fast, and often only in certain
frequency bands. These functions measure that from the envelope of the ring.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import hilbert

from .conditioning import bandpass
from .octave_bands import octave_band_frequencies

_DB_FLOOR = 1.0e-6  # -120 dB relative to the envelope peak


def envelope(x: np.ndarray, smooth_samples: int = 1) -> np.ndarray:
    """Amplitude envelope via the analytic signal (Hilbert transform).

    ``smooth_samples`` > 1 applies a moving average to tame the ripple at the
    carrier frequency.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2:
        raise ValueError("envelope: need at least 2 samples")
    env = np.abs(hilbert(x))
    if smooth_samples and smooth_samples > 1:
        k = int(smooth_samples)
        env = np.convolve(env, np.ones(k) / k, mode="same")
    return env


def _envelope_db_from_peak(x: np.ndarray) -> tuple[np.ndarray, int]:
    env = envelope(x)
    peak_idx = int(np.argmax(env))
    peak = env[peak_idx]
    if peak <= 0:
        raise ValueError("signal is silent")
    env_db = 20.0 * np.log10(np.maximum(env, peak * _DB_FLOOR) / peak)
    return env_db, peak_idx


def time_to_drop(x: np.ndarray, fs: float, db_drop: float) -> float | None:
    """Seconds from the envelope peak until it first falls ``db_drop`` dB below
    the peak. ``None`` if it never drops that far within the signal.
    """
    if db_drop <= 0:
        raise ValueError("time_to_drop: db_drop must be positive")
    env_db, peak_idx = _envelope_db_from_peak(x)
    hit = np.nonzero(env_db[peak_idx:] <= -db_drop)[0]
    if hit.size == 0:
        return None
    return float(hit[0] / fs)


def reverb_time(x: np.ndarray, fs: float, use_drop_db: float = 20.0) -> float | None:
    """T20 / T30-style reverberation time.

    Measures how long the envelope takes to fall ``use_drop_db`` dB and
    extrapolates that rate to a full 60 dB decay. ``use_drop_db=20`` gives T20,
    ``30`` gives T30. ``None`` if the envelope never drops ``use_drop_db``.
    """
    t = time_to_drop(x, fs, use_drop_db)
    if t is None:
        return None
    return float(t * 60.0 / use_drop_db)


def decay_rate(x: np.ndarray, fs: float, fit_drop_db: float = 30.0) -> float:
    """Decay rate of the envelope in dB per second (negative for a decaying
    signal), from a straight-line fit between the peak and ``fit_drop_db`` below
    it (or the end of the signal, whichever comes first).
    """
    env_db, peak_idx = _envelope_db_from_peak(x)
    seg = env_db[peak_idx:]
    below = np.nonzero(seg <= -fit_drop_db)[0]
    stop = int(below[0]) if below.size else seg.size
    if stop < 4:
        raise ValueError("decay_rate: decay too short to fit")
    t = np.arange(stop) / fs
    slope = np.polyfit(t, seg[:stop], 1)[0]
    return float(slope)


def per_band_decay(
    x: np.ndarray,
    fs: float,
    fraction: int = 3,
    f_min: float = 250.0,
    f_max: float = 16000.0,
    fit_drop_db: float = 30.0,
    filter_order: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """Decay rate (dB/s) inside each fractional-octave band.

    A crack often collapses one or two bands far faster than the rest - that
    contrast is the discriminating feature. Returns ``(centres, rates)``; a rate
    is ``NaN`` for a band that could not be filtered or fit.
    """
    x = np.asarray(x, dtype=np.float64)
    centres, lower, upper = octave_band_frequencies(fraction, f_min, min(f_max, 0.45 * fs))
    rates = np.full(centres.size, np.nan)
    for i in range(centres.size):
        lo, hi = float(lower[i]), float(upper[i])
        if not (0 < lo < hi < 0.5 * fs):
            continue
        try:
            band = bandpass(x, fs, lo, hi, order=filter_order)
            rates[i] = decay_rate(band, fs, fit_drop_db=fit_drop_db)
        except (ValueError, FloatingPointError):
            pass
    return centres, rates
