"""Decay / damping analysis (docs/METHODS.md section 3.3).

A sound part rings; a cracked one damps fast, and often only in certain
frequency bands. Reverberation time and decay rate use Schroeder backward
integration of the energy (ISO 3382 method) - the integrated curve is monotonic,
so it is not fooled by the interference nulls in a multi-mode ring the way a
raw envelope is.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import hilbert

from .conditioning import bandpass
from .octave_bands import octave_band_frequencies

_DB_FLOOR = 1.0e-12


def envelope(x: np.ndarray, smooth_samples: int = 1) -> np.ndarray:
    """Amplitude envelope via the analytic signal (Hilbert transform).

    ``smooth_samples`` > 1 applies a moving average to tame the ripple at the
    carrier frequency and the nulls between modes.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2:
        raise ValueError("envelope: need at least 2 samples")
    env = np.abs(hilbert(x))
    if smooth_samples and smooth_samples > 1:
        k = int(smooth_samples)
        env = np.convolve(env, np.ones(k) / k, mode="same")
    return env


def energy_decay_curve(x: np.ndarray) -> np.ndarray:
    """Schroeder energy-decay curve in dB, normalised to 0 dB at the start.

    ``EDC[n] = 10*log10( sum(x[n:]**2) / sum(x**2) )`` - monotonically
    decreasing.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size < 4:
        raise ValueError("energy_decay_curve: need at least 4 samples")
    energy = x * x
    tail = np.cumsum(energy[::-1])[::-1]
    total = tail[0]
    if total <= 0:
        raise ValueError("energy_decay_curve: signal is silent")
    return 10.0 * np.log10(np.maximum(tail / total, _DB_FLOOR))


def _edc_slope_db_per_s(x: np.ndarray, fs: float, upper_db: float, lower_db: float) -> float | None:
    """Least-squares slope (dB/s) of the EDC between ``upper_db`` and ``lower_db``
    (both negative, ``upper_db`` closer to 0). ``None`` if that span is not
    covered by the curve.
    """
    edc = energy_decay_curve(x)
    if edc[-1] > lower_db:  # never decays far enough
        return None
    lo = int(np.argmax(edc <= upper_db))
    hi = int(np.argmax(edc <= lower_db))
    if hi <= lo + 3:
        return None
    t = np.arange(lo, hi) / fs
    slope, _ = np.polyfit(t, edc[lo:hi], 1)
    return float(slope)


def reverb_time(x: np.ndarray, fs: float, use_drop_db: float = 20.0) -> float | None:
    """T20 / T30-style reverberation time.

    Fits the energy-decay curve from -5 dB to ``-(5 + use_drop_db)`` dB and
    extrapolates that rate to a full 60 dB decay. ``use_drop_db=20`` gives T20,
    ``30`` gives T30. ``None`` if the curve does not span that range.
    """
    slope = _edc_slope_db_per_s(x, fs, -5.0, -(5.0 + use_drop_db))
    if slope is None or slope >= 0.0:
        return None
    return float(-60.0 / slope)


def decay_rate(x: np.ndarray, fs: float, fit_drop_db: float = 30.0) -> float:
    """Energy-decay rate in dB per second (negative), fitted from -5 dB to
    ``-(5 + fit_drop_db)`` dB, or as far as the curve reaches.
    """
    edc = energy_decay_curve(x)
    lo = int(np.argmax(edc <= -5.0)) if edc[-1] <= -5.0 else 0
    target = -(5.0 + fit_drop_db)
    hi = int(np.argmax(edc <= target)) if edc[-1] <= target else edc.size
    if hi <= lo + 3:
        raise ValueError("decay_rate: decay too short to fit")
    t = np.arange(lo, hi) / fs
    slope, _ = np.polyfit(t, edc[lo:hi], 1)
    return float(slope)


def time_to_drop(x: np.ndarray, fs: float, db_drop: float, smooth_ms: float = 10.0) -> float | None:
    """Seconds from the envelope peak until the (smoothed) envelope first falls
    ``db_drop`` dB below the peak. ``None`` if it never drops that far.
    """
    if db_drop <= 0:
        raise ValueError("time_to_drop: db_drop must be positive")
    smooth = max(1, int(round(smooth_ms / 1000.0 * fs)))
    env = envelope(x, smooth_samples=smooth)
    peak_idx = int(np.argmax(env))
    peak = env[peak_idx]
    if peak <= 0:
        raise ValueError("time_to_drop: signal is silent")
    env_db = 20.0 * np.log10(np.maximum(env[peak_idx:], peak * 1e-6) / peak)
    hit = np.nonzero(env_db <= -db_drop)[0]
    if hit.size == 0:
        return None
    return float(hit[0] / fs)


def per_band_decay(
    x: np.ndarray,
    fs: float,
    fraction: int = 3,
    f_min: float = 250.0,
    f_max: float = 16000.0,
    fit_drop_db: float = 25.0,
    filter_order: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    """Energy-decay rate (dB/s) inside each fractional-octave band.

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
