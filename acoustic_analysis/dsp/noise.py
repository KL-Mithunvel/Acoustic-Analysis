"""Noise profiling and reduction (docs/METHODS.md, docs/UI_DESIGN.md Noise).

Capture a noise-only recording, characterise it, and optionally subtract it from
another clip. Spectral subtraction / gating is useful as a listening and
inspection aid; features taken from a denoised signal should be treated with
care (the process can invent structure) - config ``noise.apply_in_analysis``
gates that and the UI labels it.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import istft, stft

from . import octave_bands as _ob
from . import sound_level as _sl


def average_magnitude_spectrum(
    x: np.ndarray, fs: float, nperseg: int = 2048
) -> tuple[np.ndarray, np.ndarray]:
    """Mean STFT magnitude across time - the shape used for subtraction.

    Returns ``(freqs_hz, magnitude)``.
    """
    x = np.asarray(x, dtype=np.float64)
    if x.size < nperseg:
        raise ValueError(f"average_magnitude_spectrum: need >= {nperseg} samples")
    noverlap = nperseg * 3 // 4
    f, _, z = stft(x, fs=fs, nperseg=nperseg, noverlap=noverlap)
    return f, np.mean(np.abs(z), axis=1)


def noise_profile(noise: np.ndarray, fs: float, cfg: dict) -> dict:
    """Characterise a noise-only recording.

    Returns broadband level, statistical levels, the octave spectrum, and the
    average magnitude spectrum (``_magnitude`` / ``_freqs_hz``) used by
    ``reduce_noise``.
    """
    noise = np.asarray(noise, dtype=np.float64)
    nperseg = int(cfg.get("noise", {}).get("stft_nperseg", 2048))
    ref_p = cfg["octave"].get("reference_pressure_pa") if cfg["calibration"].get("enabled") else None

    freqs, mag = average_magnitude_spectrum(noise, fs, nperseg)
    centres, levels = _ob.fractional_octave_levels(
        noise, fs, fraction=cfg["octave"]["fraction"],
        f_min=cfg["octave"]["f_min_hz"], f_max=cfg["octave"]["f_max_hz"], ref_pressure=ref_p,
    )
    return {
        "duration_s": round(noise.size / fs, 3),
        "broadband_rms": float(np.sqrt(np.mean(noise**2))),
        "broadband_level_db": round(_sl.leq(noise, ref_pressure=ref_p), 2),
        "percentile_levels_db": {
            k: round(v, 2)
            for k, v in _sl.percentile_levels(noise, fs, (5, 50, 90, 95), "fast", ref_p).items()
        },
        "octave_centres_hz": [round(float(c), 2) for c in centres],
        "octave_levels_db": [None if not np.isfinite(v) else round(float(v), 2) for v in levels],
        "_freqs_hz": freqs,
        "_magnitude": mag,
    }


def reduce_noise(
    x: np.ndarray,
    fs: float,
    noise: np.ndarray,
    strength: float = 1.0,
    method: str = "subtraction",
    nperseg: int = 2048,
    floor_db: float = -25.0,
) -> np.ndarray:
    """Remove stationary noise from ``x`` using a noise-only reference.

    ``method='subtraction'`` subtracts ``strength`` x the noise magnitude from
    each STFT bin; ``method='gate'`` zeroes bins that do not exceed
    ``(1 + strength)`` x the noise. ``floor_db`` sets how far below the input a
    bin may be pushed (limits musical-noise artefacts).
    """
    x = np.asarray(x, dtype=np.float64)
    noise = np.asarray(noise, dtype=np.float64)
    if method not in ("subtraction", "gate"):
        raise ValueError("method must be 'subtraction' or 'gate'")
    if x.size < nperseg or noise.size < nperseg:
        raise ValueError(f"reduce_noise: need >= {nperseg} samples in both signals")

    noverlap = nperseg * 3 // 4
    f, t, z = stft(x, fs=fs, nperseg=nperseg, noverlap=noverlap)
    _, nmag = average_magnitude_spectrum(noise, fs, nperseg)
    nmag = nmag[:, None]

    mag = np.abs(z)
    phase = np.angle(z)
    floor = 10.0 ** (floor_db / 20.0)

    if method == "subtraction":
        cleaned = np.maximum(mag - strength * nmag, floor * mag)
    else:  # gate
        gain = np.where(mag > (1.0 + strength) * nmag, 1.0, floor)
        cleaned = mag * gain

    _, y = istft(cleaned * np.exp(1j * phase), fs=fs, nperseg=nperseg, noverlap=noverlap)
    return np.asarray(y[: x.size], dtype=np.float64)
