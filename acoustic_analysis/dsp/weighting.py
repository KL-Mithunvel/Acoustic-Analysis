"""Frequency weighting filters A / C / Z (docs/METHODS.md section 3.4).

The analog A- and C-weighting transfer functions of IEC 61672-1 are realised
digitally by the bilinear transform. The gain is normalised to exactly 0 dB at
1 kHz. Bilinear warping makes the response drift from the standard above a few
kHz - acceptable for a classification feature, not for a certified sound level
meter. Z ("zero") weighting is flat and returns the signal unchanged.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import bilinear_zpk, freqs_zpk, sosfilt, zpk2sos

_TWO_PI = 2.0 * np.pi
# IEC 61672-1 pole frequencies (Hz)
_A_POLE_HZ = (20.598997, 107.65265, 737.86223, 12194.217)
_C_POLE_HZ = (20.598997, 12194.217)


def _analog_zpk(kind: str) -> tuple[np.ndarray, np.ndarray, float]:
    if kind == "A":
        zeros = [0.0, 0.0, 0.0, 0.0]
        poles = [
            -_TWO_PI * _A_POLE_HZ[0], -_TWO_PI * _A_POLE_HZ[0],
            -_TWO_PI * _A_POLE_HZ[1],
            -_TWO_PI * _A_POLE_HZ[2],
            -_TWO_PI * _A_POLE_HZ[3], -_TWO_PI * _A_POLE_HZ[3],
        ]
    elif kind == "C":
        zeros = [0.0, 0.0]
        poles = [
            -_TWO_PI * _C_POLE_HZ[0], -_TWO_PI * _C_POLE_HZ[0],
            -_TWO_PI * _C_POLE_HZ[1], -_TWO_PI * _C_POLE_HZ[1],
        ]
    else:
        raise ValueError("kind must be 'A' or 'C'")
    # normalise so |H(1 kHz)| == 1
    _, h = freqs_zpk(zeros, poles, 1.0, worN=[_TWO_PI * 1000.0])
    gain = 1.0 / float(np.abs(h[0]))
    return np.asarray(zeros), np.asarray(poles), gain


def weighting_sos(kind: str, fs: float) -> np.ndarray:
    """Second-order-section digital filter for 'A' or 'C' weighting at ``fs``."""
    z, p, k = _analog_zpk(kind.upper())
    zd, pd, kd = bilinear_zpk(z, p, k, fs)
    return zpk2sos(zd, pd, kd)


def apply_weighting(x: np.ndarray, fs: float, kind: str = "Z") -> np.ndarray:
    """Apply A, C or Z frequency weighting to ``x``.

    Z is flat (returns a copy). A and C are causal IIR filtering (not zero-phase
    - weighting is defined as a real filter).
    """
    x = np.asarray(x, dtype=np.float64)
    kind = kind.upper()
    if kind == "Z":
        return x.copy()
    if kind not in ("A", "C"):
        raise ValueError("kind must be 'A', 'C' or 'Z'")
    if x.size < 8:
        raise ValueError("apply_weighting: input too short")
    return sosfilt(weighting_sos(kind, fs), x)
