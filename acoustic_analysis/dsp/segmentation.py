"""Carving a long recording into individual strike snippets.

A tap-test video is one continuous take holding dozens of strikes. Before any
of the per-clip analysis in this package can run, that take has to be cut into
one clip per strike. These are the pure signal functions behind that cut -
numpy array in, sample indices out, no file, audio-device or GUI I/O (see
.CLAUDE/CLAUDE.md Development Rule 1).

Distinct from ``dsp/conditioning.detect_impact``, which answers "where is *the*
strike in this already-cropped clip" using the clip's own pre-roll as the noise
reference. Here there is no pre-roll to trust: the recording contains many
strikes, long gaps, handling noise and talking, so the noise floor is estimated
from the quiet majority of the take itself.
"""

from __future__ import annotations

import numpy as np

_EPS = 1e-12


def moving_rms(x: np.ndarray, win_samples: int) -> np.ndarray:
    """Running RMS over a sliding window, same length as ``x``.

    Computed from a cumulative sum of squares, so cost does not grow with the
    window - a 10-minute take at 48 kHz is 29 M samples and a naive per-window
    loop would take minutes.

    Raises ValueError on an empty signal or a window below 1 sample.
    """
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    if x.size == 0:
        raise ValueError("moving_rms: empty signal")
    if win_samples < 1:
        raise ValueError(f"moving_rms: win_samples must be >= 1, got {win_samples}")

    win = int(min(win_samples, x.size))
    csum = np.concatenate(([0.0], np.cumsum(np.square(x))))
    # Centred window, clamped at both ends, so an onset is not reported half a
    # window late.
    half = win // 2
    idx = np.arange(x.size)
    lo = np.maximum(0, idx - half)
    hi = np.minimum(x.size, idx - half + win)
    return np.sqrt((csum[hi] - csum[lo]) / np.maximum(1, hi - lo))


def envelope_minmax(x: np.ndarray, n_buckets: int) -> tuple[np.ndarray, np.ndarray]:
    """Per-bucket (min, max) of ``x`` - the waveform overview for a plot.

    Drawing 29 M points is neither possible nor useful; drawing one vertical
    line per pixel column between that column's min and max looks identical and
    is instant. Plain subsampling is *not* equivalent - it would step over the
    one-sample peak of a strike and the taps would vanish from the overview.

    Returns two arrays of length ``min(n_buckets, len(x))``.
    """
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    if x.size == 0:
        raise ValueError("envelope_minmax: empty signal")
    if n_buckets < 1:
        raise ValueError(f"envelope_minmax: n_buckets must be >= 1, got {n_buckets}")

    n = int(min(n_buckets, x.size))
    edges = (np.arange(n) * (x.size / n)).astype(np.int64)
    # reduceat handles unevenly sized buckets without a Python loop.
    return np.minimum.reduceat(x, edges), np.maximum.reduceat(x, edges)


def noise_floor(envelope: np.ndarray, percentile: float = 25.0) -> float:
    """Background level of a take, as a percentile of its own RMS envelope.

    A percentile rather than a mean because the strikes themselves are in this
    signal: they are loud, brief and comparatively rare, so the low percentiles
    describe the room between them. Ignores non-finite values.
    """
    env = np.asarray(envelope, dtype=np.float64).reshape(-1)
    env = env[np.isfinite(env)]
    if env.size == 0:
        raise ValueError("noise_floor: empty envelope")
    if not 0.0 <= percentile <= 100.0:
        raise ValueError(f"noise_floor: percentile must be 0-100, got {percentile}")
    return float(np.percentile(env, percentile))


def detect_onsets(
    x: np.ndarray,
    fs: float,
    *,
    smooth_ms: float = 5.0,
    threshold_mult: float = 6.0,
    noise_percentile: float = 25.0,
    min_gap_s: float = 0.35,
    min_peak_ratio: float = 0.05,
) -> list[int]:
    """Sample index of every strike in a long recording, in time order.

    The detector is deliberately simple and explainable, because the operator
    corrects it by eye in the Slice screen rather than trusting it blindly:

    1. RMS envelope over ``smooth_ms`` - a strike is a step in short-term
       energy, which survives smoothing; a single clipped sample is not.
    2. Threshold at ``threshold_mult`` x the take's own noise floor.
    3. Keep rising edges only, then enforce ``min_gap_s`` between accepted
       onsets. Without the gap one strike reports two or three times as its
       ring fluctuates across the threshold.
    4. Drop anything whose local peak is below ``min_peak_ratio`` of the
       loudest strike found - this is what rejects footsteps, speech and
       setting a tile down, which clear the noise floor but are nowhere near
       as loud as a deliberate tap.

    Each returned index is walked back to the start of the attack, not left at
    the threshold crossing, so a snippet cut from it keeps the leading edge the
    feature extractor needs.

    Returns an empty list when nothing qualifies (a silent or strike-free
    take). Raises ValueError on an empty signal or a non-positive rate.
    """
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    if x.size == 0:
        raise ValueError("detect_onsets: empty signal")
    if fs <= 0:
        raise ValueError(f"detect_onsets: sample rate must be > 0, got {fs}")
    if threshold_mult <= 1.0:
        raise ValueError(f"detect_onsets: threshold_mult must be > 1, got {threshold_mult}")

    win = max(1, int(round(smooth_ms / 1000.0 * fs)))
    env = moving_rms(x, win)
    floor = noise_floor(env, noise_percentile)
    if floor <= _EPS:
        # A digitally silent majority (a synthetic file, or a gated recorder).
        # Fall back to a fraction of the peak so the take is still usable.
        peak = float(np.max(env))
        if peak <= _EPS:
            return []
        floor = peak * 0.01
    threshold = floor * threshold_mult

    above = env > threshold
    if not np.any(above):
        return []
    rising = np.nonzero(above[1:] & ~above[:-1])[0] + 1
    if above[0]:  # a take that starts mid-strike
        rising = np.concatenate(([0], rising))

    min_gap = max(1, int(round(min_gap_s * fs)))
    kept: list[int] = []
    for idx in rising.tolist():
        if kept and idx - kept[-1] < min_gap:
            continue
        kept.append(idx)

    if not kept:
        return []

    # Local peak per candidate, measured up to the next candidate (or the gap,
    # whichever is shorter) so one loud strike cannot mask the next.
    peaks = []
    for i, start in enumerate(kept):
        stop = min(kept[i + 1] if i + 1 < len(kept) else x.size, start + min_gap)
        peaks.append(float(np.max(env[start:max(start + 1, stop)])))
    loudest = max(peaks)
    onsets = [s for s, p in zip(kept, peaks) if p >= loudest * min_peak_ratio]

    return [_walk_back_to_attack(env, o, floor, win) for o in onsets]


def _walk_back_to_attack(env: np.ndarray, index: int, floor: float, win: int) -> int:
    """Move a threshold crossing back to where the level left the noise floor.

    The crossing happens partway up the attack, by however long the envelope
    window and the threshold margin delay it. Cutting there would clip the
    strike's leading edge, which is exactly the part ``detect_impact`` and the
    decay fit need.
    """
    limit = max(0, index - 4 * win)
    quiet = np.nonzero(env[limit:index] <= floor * 1.5)[0]
    return int(limit + quiet[-1]) if quiet.size else limit


def segments_from_onsets(
    onsets,
    n_samples: int,
    fs: float,
    *,
    pre_ms: float = 30.0,
    post_ms: float = 700.0,
    guard_ms: float = 20.0,
) -> list[tuple[int, int]]:
    """Turn strike indices into (start, end) sample windows, clamped and
    non-overlapping.

    ``pre_ms`` of lead-in is kept in front of every strike on purpose: the
    per-clip analysis measures its own noise floor from that pre-roll and
    ``detect_impact`` refuses a clip that has none.

    When two strikes land closer together than ``post_ms``, the earlier window
    is cut short rather than being allowed to swallow the next one - a clip
    containing two impacts would give a meaningless decay fit.

    That cut is placed ``max(pre_ms, guard_ms)`` before the next strike, not
    ``guard_ms``: the next window already begins ``pre_ms`` early to collect
    its own pre-roll, so trimming only by the guard would leave the two
    windows overlapping by the difference, and the same audio would be
    exported twice under two labels.
    """
    if n_samples <= 0:
        raise ValueError(f"segments_from_onsets: n_samples must be > 0, got {n_samples}")
    if fs <= 0:
        raise ValueError(f"segments_from_onsets: sample rate must be > 0, got {fs}")
    if pre_ms < 0 or post_ms <= 0:
        raise ValueError("segments_from_onsets: need pre_ms >= 0 and post_ms > 0")

    ordered = sorted(int(o) for o in onsets)
    pre = int(round(pre_ms / 1000.0 * fs))
    post = int(round(post_ms / 1000.0 * fs))
    guard = int(round(guard_ms / 1000.0 * fs))

    out: list[tuple[int, int]] = []
    for i, onset in enumerate(ordered):
        start = max(0, onset - pre)
        end = min(n_samples, onset + post)
        if i + 1 < len(ordered):
            boundary = ordered[i + 1] - max(pre, guard)
            end = min(end, max(start + 1, boundary))
        if end > start:
            out.append((start, end))
    return out
