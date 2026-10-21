"""Features of a clip whose strike time is known roughly (a station session clip).

``features.extract_features`` finds the impact itself (``detect_impact``) and, on the real
2026-10-19 tile clips, locked onto something 0.3 s before the strike. Here the search for the
onset starts at the end of a quiet lead-in the caller trusts, so the retraction noise and
handling sounds before it cannot be mistaken for the tap.

Pure: arrays in, numbers out, no I/O. Every parameter is ``cfg["strike"]`` (provisional).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, hilbert, sosfiltfilt, welch

FEATURE_KEYS = (
    "peak", "snr_db", "centroid_hz", "peak_hz", "f_low", "f_mid", "f_high", "f_top",
    "slope_db_ms", "t20_ms",
)

# Plain-language names for the GUI (key -> label, unit).
FEATURE_LABELS = {
    "peak": ("Loudest point", ""),
    "snr_db": ("Strike over background", "dB"),
    "centroid_hz": ("Spectral centroid (brightness)", "Hz"),
    "peak_hz": ("Strongest frequency", "Hz"),
    "f_low": ("Energy below 1 kHz", "share"),
    "f_mid": ("Energy 1-3 kHz", "share"),
    "f_high": ("Energy 3-6 kHz", "share"),
    "f_top": ("Energy above 6 kHz", "share"),
    "slope_db_ms": ("Fade speed", "dB/ms"),
    "t20_ms": ("Time to fade 20 dB", "ms"),
}


def find_onset(x: np.ndarray, fs: int, cfg: dict) -> tuple[int | None, float]:
    """Index of the strike onset and the lead-in RMS. ``None`` when nothing rises above it."""
    c = cfg["strike"]
    lead = max(int(float(c["lead_in_s"]) * fs), 1)
    if x.size <= lead + 1:
        return None, 0.0
    noise_rms = float(np.sqrt(np.mean(x[:lead] ** 2))) + 1e-12
    above = np.flatnonzero(np.abs(x[lead:]) > float(c["onset_mult"]) * noise_rms)
    if above.size == 0:
        return None, noise_rms
    return lead + int(above[0]), noise_rms


def ring_window(x: np.ndarray, onset: int, fs: int, cfg: dict) -> np.ndarray:
    lo, hi = cfg["strike"]["ring_ms"]
    return x[onset + int(lo * fs / 1000): onset + int(hi * fs / 1000)]


def ring_spectrum(x: np.ndarray, fs: int, cfg: dict) -> tuple[np.ndarray, np.ndarray] | None:
    """Normalised power spectrum of the ring (sums to 1), or ``None`` without an onset."""
    x = np.asarray(x, float) - np.median(x)
    onset, _ = find_onset(x, fs, cfg)
    if onset is None:
        return None
    seg = ring_window(x, onset, fs, cfg)
    if seg.size < 64:
        return None
    f, p = welch(seg, fs, nperseg=min(4096, seg.size))
    f_lo, f_hi = cfg["strike"]["band_hz"]
    keep = (f >= f_lo) & (f <= f_hi)
    f, p = f[keep], p[keep]
    total = p.sum()
    return (f, p / total) if total > 0 else None


def _envelope_db(x: np.ndarray, onset: int, fs: int, cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    """Smoothed envelope of the band-passed ring in dB, time in ms from the onset."""
    c = cfg["strike"]
    b_lo, b_hi = c["decay_band_hz"]
    sos = butter(4, [b_lo, min(b_hi, 0.45 * fs)], "bandpass", fs=fs, output="sos")
    env = np.abs(hilbert(sosfiltfilt(sos, x)[onset: onset + int(float(c["ring_ms"][1]) * fs / 1000)]))
    k = max(int(float(c["smooth_ms"]) * fs / 1000), 1)
    env = np.convolve(env, np.ones(k) / k, "same") + 1e-12
    db = 20 * np.log10(env)
    return np.arange(db.size) / fs * 1000, db


def ring_envelope_db(x: np.ndarray, fs: int, cfg: dict) -> tuple[np.ndarray, np.ndarray] | None:
    """(time_ms, level_db) of the fade after the strike, level re its own start; ``None`` if no strike."""
    x = np.asarray(x, float) - np.median(x)
    onset, _ = find_onset(x, fs, cfg)
    if onset is None:
        return None
    t_ms, db = _envelope_db(x, onset, fs, cfg)
    if db.size < 8:
        return None
    return t_ms, db - float(np.max(db[: max(int(0.01 * fs), 1)]))      # 0 dB = the loudest point in the first 10 ms


def strike_features(x: np.ndarray, fs: int, cfg: dict) -> dict:
    """Flat feature dict. ``onset_found`` False means the rest are ``None`` (nothing struck)."""
    c = cfg["strike"]
    x = np.asarray(x, float) - np.median(x)
    out: dict = {"onset_found": False, "onset_s": None, **{k: None for k in FEATURE_KEYS}}
    onset, noise_rms = find_onset(x, fs, cfg)
    if onset is None:
        return out
    seg = ring_window(x, onset, fs, cfg)
    if seg.size < 64:
        return out
    out["onset_found"] = True
    out["onset_s"] = onset / fs

    peak = float(np.abs(x[onset: onset + int(0.05 * fs)]).max())
    out["peak"] = peak
    out["snr_db"] = float(20 * np.log10(peak / noise_rms))

    f, p = welch(seg, fs, nperseg=min(4096, seg.size))
    f_lo, f_hi = c["band_hz"]
    keep = (f >= f_lo) & (f <= f_hi)
    f, p = f[keep], p[keep]
    total = float(p.sum()) or 1e-30
    out["centroid_hz"] = float((f * p).sum() / total)
    out["peak_hz"] = float(f[int(np.argmax(p))])
    e1, e2, e3 = c["fraction_edges_hz"]
    out["f_low"] = float(p[f < e1].sum() / total)
    out["f_mid"] = float(p[(f >= e1) & (f < e2)].sum() / total)
    out["f_high"] = float(p[(f >= e2) & (f < e3)].sum() / total)
    out["f_top"] = float(p[f >= e3].sum() / total)

    # Envelope of the band-passed ring: fade speed (dB/ms line fit) and time to fall 20 dB.
    t_ms, db = _envelope_db(x, onset, fs, cfg)
    f0, f1 = c["decay_fit_ms"]
    sel = (t_ms >= f0) & (t_ms <= f1)
    if sel.sum() >= 4:
        out["slope_db_ms"] = float(np.polyfit(t_ms[sel], db[sel], 1)[0])
    i_ref = int(float(c["t20_ref_ms"]) * fs / 1000)
    if i_ref < db.size:
        fall = np.flatnonzero(db[i_ref:] < db[i_ref] - 20.0)
        out["t20_ms"] = float(fall[0] / fs * 1000) if fall.size else None   # None = did not fade 20 dB in the window
    return out


def zoom_window(x: np.ndarray, fs: int, cfg: dict, pre_ms: float = 60.0, post_ms: float = 320.0):
    """``(t_ms, samples, 0.0)`` around the strike with t = 0 at the onset (where it was expected if none was found)."""
    x = np.asarray(x, float) - np.median(x)
    onset, _ = find_onset(x, fs, cfg)
    if onset is None:
        onset = int(float(cfg["strike"]["expect_s"]) * fs)
    a, b = max(onset - int(pre_ms * fs / 1000), 0), min(onset + int(post_ms * fs / 1000), x.size)
    return (np.arange(a, b) - onset) / fs * 1000.0, x[a:b], 0.0


def percentile_of(value: float | None, population: list[float]) -> float | None:
    """Where ``value`` sits in ``population`` as 0-100 (None if either is missing)."""
    pop = [v for v in population if v is not None]
    if value is None or not pop:
        return None
    return 100.0 * sum(1 for v in pop if v < value) / len(pop)


def flags(feat: dict, tile_ref: dict | None = None, no_tile_ref: dict | None = None) -> list[str]:
    """Plain-language observations. References are ``{feature: median}`` of known groups.

    These describe the sound; they are not a grade."""
    notes: list[str] = []
    if not feat.get("onset_found"):
        return ["No strike found in this clip - nothing rose above the background."]
    if tile_ref and no_tile_ref and feat.get("f_mid") is not None:
        d_tile = abs(feat["f_mid"] - tile_ref["f_mid"]) + abs(feat["f_top"] - tile_ref["f_top"])
        d_none = abs(feat["f_mid"] - no_tile_ref["f_mid"]) + abs(feat["f_top"] - no_tile_ref["f_top"])
        notes.append("Sounds like a tile under the striker." if d_tile <= d_none
                     else "Sounds like the striker alone (no tile).")
    if feat.get("t20_ms") is None:
        notes.append("The ring did not fade 20 dB within the analysed window (long ring, or noise).")
    if feat.get("snr_db") is not None and feat["snr_db"] < 20:
        notes.append("Weak strike over the background - treat the numbers with care.")
    return notes
