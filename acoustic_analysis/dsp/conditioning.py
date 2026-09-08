"""Signal conditioning: the steps that turn a raw clip into a windowed ring.

DC removal -> calibration -> band-pass -> impact detection -> windowing.
See ``docs/METHODS.md`` sections 1 and 2.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, sosfiltfilt


def rms(x: np.ndarray) -> float:
    """Linear root-mean-square level (not dB)."""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        raise ValueError("rms: empty input")
    return float(np.sqrt(np.mean(np.square(x))))


def remove_dc(x: np.ndarray) -> np.ndarray:
    """Subtract the mean so the waveform is centred on zero."""
    x = np.asarray(x, dtype=np.float64)
    if x.size == 0:
        raise ValueError("remove_dc: empty input")
    return x - x.mean()


def apply_calibration(x: np.ndarray, counts_per_pascal: float | None) -> np.ndarray:
    """Scale raw samples to pascals using a reference-tone calibration factor.

    When ``counts_per_pascal`` is None (no calibration performed) the signal is
    returned unchanged; any level derived from it is then relative, not dB SPL.
    """
    x = np.asarray(x, dtype=np.float64)
    if counts_per_pascal is None:
        return x
    if counts_per_pascal <= 0:
        raise ValueError("apply_calibration: counts_per_pascal must be positive")
    return x / counts_per_pascal


def bandpass(
    x: np.ndarray, fs: float, low_hz: float, high_hz: float, order: int = 4
) -> np.ndarray:
    """Zero-phase Butterworth band-pass (second-order sections + ``filtfilt``).

    Raises ValueError unless ``0 < low_hz < high_hz < fs/2`` and the input is
    long enough for the filter's edge padding.
    """
    x = np.asarray(x, dtype=np.float64)
    nyq = 0.5 * fs
    if not (0 < low_hz < high_hz < nyq):
        raise ValueError(f"bandpass: need 0 < {low_hz} < {high_hz} < {nyq}")
    padlen = 3 * (2 * order + 1)
    if x.size <= padlen:
        raise ValueError(f"bandpass: input too short ({x.size} samples <= {padlen})")
    sos = butter(order, [low_hz / nyq, high_hz / nyq], btype="band", output="sos")
    return sosfiltfilt(sos, x)


def detect_impact(
    x: np.ndarray, pre_samples: int, threshold_mult: float = 5.0
) -> int:
    """Absolute sample index of the strike.

    The strike is the first sample *after* the pre-trigger region whose
    magnitude exceeds ``threshold_mult`` times the RMS of that region. The
    electrical trigger and the real contact moment differ by a few ms, so this
    is measured from the waveform, not assumed.

    Raises ValueError if the pre region is out of range, silent, or nothing
    crosses the threshold (a missed or failed strike).
    """
    x = np.asarray(x, dtype=np.float64)
    if not (1 <= pre_samples < x.size):
        raise ValueError(
            f"detect_impact: pre_samples {pre_samples} out of range for {x.size} samples"
        )
    noise_rms = float(np.sqrt(np.mean(np.square(x[:pre_samples]))))
    if noise_rms == 0.0:
        raise ValueError("detect_impact: pre-trigger region is silent")
    threshold = threshold_mult * noise_rms
    crossings = np.nonzero(np.abs(x[pre_samples:]) > threshold)[0]
    if crossings.size == 0:
        raise ValueError("detect_impact: no sample crosses the impact threshold")
    return int(pre_samples + crossings[0])


def window_relative(
    x: np.ndarray, impact_index: int, fs: float, start_ms: float, end_ms: float
) -> np.ndarray:
    """Slice ``x`` from ``start_ms`` to ``end_ms`` relative to ``impact_index``.

    Times are milliseconds and may be negative (pre-impact). The slice is
    clamped to the array bounds. Raises ValueError if ``start_ms >= end_ms`` or
    the resulting window lies entirely outside the signal.
    """
    x = np.asarray(x, dtype=np.float64)
    if start_ms >= end_ms:
        raise ValueError("window_relative: start_ms must be < end_ms")
    start = impact_index + int(round(start_ms / 1000.0 * fs))
    end = impact_index + int(round(end_ms / 1000.0 * fs))
    start = max(0, start)
    end = min(x.size, end)
    if start >= end:
        raise ValueError("window_relative: window lies outside the signal")
    return x[start:end]
