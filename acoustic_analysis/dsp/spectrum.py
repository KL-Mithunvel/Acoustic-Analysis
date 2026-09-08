"""FFT spectrum and spectral descriptors (docs/METHODS.md section 3.2).

All functions take a magnitude spectrum as produced by ``fft_magnitude`` -
frequencies in Hz and linear magnitude, both 1-D and the same length.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import find_peaks, peak_widths


def fft_magnitude(x: np.ndarray, fs: float) -> tuple[np.ndarray, np.ndarray]:
    """Single-sided Hann-windowed magnitude spectrum.

    Returns ``(frequencies_hz, magnitude)``. The magnitude is scaled so a pure
    sine of amplitude ``A`` produces a peak of height ``~A`` regardless of clip
    length.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size < 2:
        raise ValueError("fft_magnitude: need at least 2 samples")
    window = np.hanning(x.size)
    spectrum = np.fft.rfft(x * window)
    freqs = np.fft.rfftfreq(x.size, d=1.0 / fs)
    magnitude = np.abs(spectrum) / (window.sum() / 2.0)
    return freqs, magnitude


def _band_bounds(freqs: np.ndarray, fmin: float, fmax: float | None) -> tuple[int, int]:
    fmax = float(freqs[-1]) if fmax is None else fmax
    mask = (freqs >= fmin) & (freqs <= fmax)
    if not np.any(mask):
        raise ValueError(f"no frequency bins in [{fmin}, {fmax}]")
    lo = int(np.argmax(mask))
    hi = int(freqs.size - np.argmax(mask[::-1]))
    return lo, hi


def dominant_frequency(
    freqs: np.ndarray, magnitude: np.ndarray, fmin: float = 20.0, fmax: float | None = None
) -> float:
    """Frequency of the highest-magnitude bin within ``[fmin, fmax]``.

    ``fmin`` defaults to 20 Hz so DC / near-DC leakage does not win the search.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    magnitude = np.asarray(magnitude, dtype=np.float64)
    if freqs.size < 2:
        raise ValueError("dominant_frequency: need at least 2 bins")
    lo, hi = _band_bounds(freqs, fmin, fmax)
    idx = lo + int(np.argmax(magnitude[lo:hi]))
    return float(freqs[idx])


def pick_peaks(
    freqs: np.ndarray,
    magnitude: np.ndarray,
    n_peaks: int = 3,
    fmin: float = 20.0,
    fmax: float | None = None,
) -> list[dict]:
    """The ``n_peaks`` strongest spectral peaks within ``[fmin, fmax]``.

    Returns a list of dicts sorted by descending amplitude, each with:

    ``freq``
        peak frequency in Hz
    ``amplitude``
        peak magnitude
    ``q``
        ``f0 / FWHM`` - resonance sharpness. A crack broadens peaks, lowering Q.
        ``None`` when the width cannot be estimated.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    magnitude = np.asarray(magnitude, dtype=np.float64)
    if freqs.size < 3:
        raise ValueError("pick_peaks: need at least 3 bins")
    lo, hi = _band_bounds(freqs, fmin, fmax)
    band_freq = freqs[lo:hi]
    band_mag = magnitude[lo:hi]

    idx, _ = find_peaks(band_mag)
    if idx.size == 0:
        idx = np.array([int(np.argmax(band_mag))])

    order = np.argsort(band_mag[idx])[::-1][: max(1, n_peaks)]
    chosen = idx[order]

    df = float(band_freq[1] - band_freq[0]) if band_freq.size > 1 else 1.0
    try:
        widths = peak_widths(band_mag, chosen, rel_height=0.5)[0]
    except Exception:
        widths = np.full(chosen.shape, np.nan)

    peaks: list[dict] = []
    for k, width in zip(chosen, widths):
        f0 = float(band_freq[k])
        fwhm = float(width) * df
        peaks.append(
            {
                "freq": f0,
                "amplitude": float(band_mag[k]),
                "q": (f0 / fwhm) if fwhm > 0 else None,
            }
        )
    return peaks


def spectral_centroid(freqs: np.ndarray, magnitude: np.ndarray) -> float:
    """Magnitude-weighted mean frequency - the spectrum's "brightness"."""
    freqs = np.asarray(freqs, dtype=np.float64)
    magnitude = np.asarray(magnitude, dtype=np.float64)
    total = magnitude.sum()
    if total <= 0:
        raise ValueError("spectral_centroid: spectrum has no energy")
    return float(np.sum(freqs * magnitude) / total)


def spectral_bandwidth(freqs: np.ndarray, magnitude: np.ndarray) -> float:
    """Magnitude-weighted spread of frequency about the centroid (Hz)."""
    centroid = spectral_centroid(freqs, magnitude)
    freqs = np.asarray(freqs, dtype=np.float64)
    magnitude = np.asarray(magnitude, dtype=np.float64)
    return float(np.sqrt(np.sum(magnitude * (freqs - centroid) ** 2) / magnitude.sum()))


def spectral_rolloff(freqs: np.ndarray, magnitude: np.ndarray, fraction: float = 0.85) -> float:
    """Frequency below which ``fraction`` of the total magnitude sits."""
    if not (0.0 < fraction < 1.0):
        raise ValueError("spectral_rolloff: fraction must be in (0, 1)")
    freqs = np.asarray(freqs, dtype=np.float64)
    magnitude = np.asarray(magnitude, dtype=np.float64)
    cumulative = np.cumsum(magnitude)
    if cumulative[-1] <= 0:
        raise ValueError("spectral_rolloff: spectrum has no energy")
    idx = int(np.searchsorted(cumulative, fraction * cumulative[-1]))
    return float(freqs[min(idx, freqs.size - 1)])


def spectral_flatness(magnitude: np.ndarray) -> float:
    """Geometric mean / arithmetic mean of the magnitude spectrum.

    Near 0 for a tonal (peaky) spectrum, near 1 for a flat / noise-like one -
    it rises when a crack turns a clean ring into broadband hash.
    """
    magnitude = np.asarray(magnitude, dtype=np.float64)
    positive = magnitude[magnitude > 0]
    if positive.size == 0:
        raise ValueError("spectral_flatness: spectrum has no energy")
    geo = np.exp(np.mean(np.log(positive)))
    arith = np.mean(positive)
    return float(geo / arith)
