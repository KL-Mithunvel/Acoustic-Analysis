"""Sound level metrics (docs/METHODS.md section 3.4).

L_eq, L_peak, exponential time weighting (Fast / Slow / Impulse) and statistical
levels Ln. With ``ref_pressure`` (e.g. 20e-6 Pa) and a calibrated signal these
are dB SPL; without it they are dB relative to unit amplitude.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

_MS_FLOOR = 1.0e-30


def _ref_squared(ref_pressure: float | None) -> float:
    return (ref_pressure**2) if ref_pressure else 1.0


def leq(x: np.ndarray, ref_pressure: float | None = None) -> float:
    """Equivalent-continuous level: the steady level with the same energy as
    ``x`` over its whole length.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        raise ValueError("leq: empty input")
    mean_square = float(np.mean(x * x))
    if mean_square <= 0.0:
        return float("-inf")
    return 10.0 * np.log10(mean_square / _ref_squared(ref_pressure))


def lpeak(x: np.ndarray, ref_pressure: float | None = None) -> float:
    """Peak level - the largest instantaneous absolute sample."""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        raise ValueError("lpeak: empty input")
    peak = float(np.max(np.abs(x)))
    if peak <= 0.0:
        return float("-inf")
    ref = ref_pressure if ref_pressure else 1.0
    return 20.0 * np.log10(peak / ref)


def _alpha(dt: float, tau: float) -> float:
    return 1.0 - np.exp(-dt / tau)


def exp_time_weight(x: np.ndarray, fs: float, mode: str = "fast") -> np.ndarray:
    """Running exponentially time-weighted mean square (linear, per sample).

    ``mode``: ``fast`` (tau = 125 ms), ``slow`` (1 s), or ``impulse`` (35 ms
    attack, 1500 ms release - fast to rise, slow to fall).
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        raise ValueError("exp_time_weight: empty input")
    dt = 1.0 / fs
    sq = x * x
    mode = mode.lower()

    if mode in ("fast", "slow"):
        tau = 0.125 if mode == "fast" else 1.0
        a = _alpha(dt, tau)
        return lfilter([a], [1.0, -(1.0 - a)], sq)

    if mode == "impulse":
        a_rise = _alpha(dt, 0.035)
        a_fall = _alpha(dt, 1.5)
        out = np.empty_like(sq)
        y = sq[0]
        for i in range(sq.size):
            a = a_rise if sq[i] > y else a_fall
            y += a * (sq[i] - y)
            out[i] = y
        return out

    raise ValueError("mode must be 'fast', 'slow' or 'impulse'")


def time_weighted_level(
    x: np.ndarray, fs: float, mode: str = "fast", ref_pressure: float | None = None
) -> np.ndarray:
    """The time-weighted level trace in dB, one value per sample."""
    ms = exp_time_weight(x, fs, mode)
    return 10.0 * np.log10(np.maximum(ms, _MS_FLOOR) / _ref_squared(ref_pressure))


def time_weighted_max(
    x: np.ndarray, fs: float, mode: str = "fast", ref_pressure: float | None = None
) -> float:
    """Maximum of the time-weighted level trace (e.g. L_AFmax, L_AImax)."""
    return float(np.max(time_weighted_level(x, fs, mode, ref_pressure)))


def percentile_levels(
    x: np.ndarray,
    fs: float,
    percentiles: tuple[int, ...] = (1, 5, 50, 95),
    mode: str = "fast",
    ref_pressure: float | None = None,
) -> dict[int, float]:
    """Statistical levels: ``Ln`` is the level exceeded ``n`` % of the time.

    The filter start-up transient is discarded before the percentiles are taken.
    Returns ``{n: level_db}``.
    """
    trace = time_weighted_level(x, fs, mode, ref_pressure)
    skip = min(trace.size // 4, int(0.5 * fs))
    seg = trace[skip:] if trace.size - skip > 10 else trace
    return {int(n): float(np.percentile(seg, 100.0 - n)) for n in percentiles}
