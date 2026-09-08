"""Feature extraction - the single orchestration point.

``extract_features`` runs the whole chain from a raw clip to one flat dict:
condition -> detect impact -> window the ring -> run every ``dsp`` module ->
collect the numbers. The dict it returns is both the dataset row and the input
to the classifier. See ``docs/METHODS.md`` sections 1-4.
"""

from __future__ import annotations

import numpy as np

from .dsp import conditioning as cond
from .dsp import decay as dec
from .dsp import octave_bands as ob
from .dsp import sound_level as sl
from .dsp import spectrum as spec
from .dsp import weighting as wt


def _to_mono(clip) -> np.ndarray:
    x = np.asarray(clip, dtype=np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)
    elif x.ndim != 1:
        raise ValueError("extract_features: clip must be 1-D or 2-D")
    return x


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError:
        return None


def _round_or_none(value, ndigits):
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), ndigits)


def extract_features(clip, fs: float, cfg: dict) -> dict:
    """Extract the full feature set from one clip.

    Parameters
    ----------
    clip:
        Mono or stereo samples. Stereo is averaged to mono.
    fs:
        Sample rate in Hz.
    cfg:
        Parsed ``config.yaml`` (see ``acoustic_analysis.config.load_config``).

    Returns
    -------
    dict
        Always contains ``valid`` (bool), ``status`` ("OK" / "RETEST") and
        ``reasons`` (list of str). When the strike cannot be located the dict is
        returned early with only the validity fields plus ``impact_index=None``.
    """
    ana = cfg["analysis"]
    cap = cfg["capture"]
    oct_cfg = cfg["octave"]
    cal = cfg["calibration"]

    x = _to_mono(clip)
    if x.size < 256:
        raise ValueError("extract_features: clip too short")

    counts_per_pascal = cal.get("counts_per_pascal") if cal.get("enabled") else None
    x = cond.remove_dc(cond.apply_calibration(x, counts_per_pascal))
    ref_p = oct_cfg.get("reference_pressure_pa") if counts_per_pascal else None

    pre_samples = int(round(cap["pre_trigger_ms"] / 1000.0 * fs))
    pre_samples = max(8, min(pre_samples, x.size // 4))
    noise_rms = cond.rms(x[:pre_samples])

    reasons: list[str] = []
    out: dict = {
        "sample_rate": int(fs),
        "n_samples": int(x.size),
        "noise_rms": float(noise_rms),
        "valid": True,
        "status": "OK",
        "reasons": reasons,
    }

    try:
        impact = cond.detect_impact(x, pre_samples, ana["impact_threshold_mult"])
    except ValueError as exc:
        out.update(valid=False, status="RETEST", impact_index=None)
        reasons.append(f"impact detection failed: {exc}")
        return out
    out["impact_index"] = int(impact)

    ring = cond.window_relative(x, impact, fs, *ana["ring_window_ms"])
    decay_win = cond.window_relative(x, impact, fs, *ana["decay_window_ms"])

    signal_rms = cond.rms(ring)
    snr_db = 20.0 * np.log10(signal_rms / noise_rms) if noise_rms > 0 else float("inf")
    out["snr_db"] = float(snr_db)
    if snr_db < ana["min_snr_db"]:
        out["valid"] = False
        out["status"] = "RETEST"
        reasons.append(f"low SNR ({snr_db:.1f} dB < {ana['min_snr_db']} dB)")

    low, high = ana["bandpass_hz"]
    order = ana["bandpass_order"]
    ring_bp = cond.bandpass(ring, fs, low, high, order)
    decay_bp = cond.bandpass(decay_win, fs, low, high, order)
    fmin = max(20.0, float(low))

    # --- spectrum ---
    freqs, mag = spec.fft_magnitude(ring_bp, fs)
    out["dominant_freq_hz"] = round(spec.dominant_frequency(freqs, mag, fmin=fmin), 2)
    out["peaks"] = [
        {
            "freq_hz": round(p["freq"], 2),
            "amplitude": round(p["amplitude"], 6),
            "q": _round_or_none(p["q"], 2),
        }
        for p in spec.pick_peaks(freqs, mag, cfg["spectrum"]["n_peaks"], fmin=fmin, fmax=float(high))
    ]
    out["spectral_centroid_hz"] = round(spec.spectral_centroid(freqs, mag), 2)
    out["spectral_bandwidth_hz"] = round(spec.spectral_bandwidth(freqs, mag), 2)
    out["spectral_rolloff_hz"] = round(
        spec.spectral_rolloff(freqs, mag, cfg["spectrum"]["rolloff_fraction"]), 2
    )
    out["spectral_flatness"] = round(spec.spectral_flatness(mag), 5)

    # --- octave bands ---
    centres, levels = ob.fractional_octave_levels(
        ring_bp,
        fs,
        fraction=oct_cfg["fraction"],
        f_min=oct_cfg["f_min_hz"],
        f_max=oct_cfg["f_max_hz"],
        ref_pressure=ref_p,
    )
    shape = ob.band_shape(levels)
    out["octave_centres_hz"] = [round(float(c), 2) for c in centres]
    out["octave_band_shape_db"] = [_round_or_none(v, 3) for v in shape]
    out["band_ratios"] = {k: round(v, 4) for k, v in ob.band_ratios(centres, levels).items()}

    # --- decay ---
    out["t20_s"] = _round_or_none(dec.reverb_time(decay_bp, fs, 20.0), 4)
    out["t30_s"] = _round_or_none(dec.reverb_time(decay_bp, fs, 30.0), 4)
    out["decay_rate_db_s"] = _round_or_none(_safe(dec.decay_rate, decay_bp, fs), 2)
    out["time_to_drop_s"] = {
        int(d): _round_or_none(dec.time_to_drop(decay_bp, fs, float(d)), 4)
        for d in cfg["decay"]["db_drop_points"]
    }
    band_c, band_r = dec.per_band_decay(
        decay_bp,
        fs,
        fraction=oct_cfg["fraction"],
        f_min=max(float(low), 250.0),
        f_max=min(float(high), 16000.0),
    )
    out["per_band_decay_db_s"] = {
        round(float(c), 1): _round_or_none(r, 2) for c, r in zip(band_c, band_r)
    }
    finite = band_r[np.isfinite(band_r)]
    out["fastest_band_decay_db_s"] = round(float(np.min(finite)), 2) if finite.size else None

    # --- levels ---
    wkind = cfg["weighting"]["default"].upper()
    out["leq_z_db"] = _round_or_none(sl.leq(ring_bp, ref_pressure=ref_p), 2)
    out[f"leq_{wkind.lower()}_db"] = _round_or_none(
        sl.leq(wt.apply_weighting(ring_bp, fs, wkind), ref_pressure=ref_p), 2
    )
    out["lpeak_db"] = _round_or_none(sl.lpeak(x[impact:], ref_pressure=ref_p), 2)
    out["l_fast_max_db"] = _round_or_none(sl.time_weighted_max(ring_bp, fs, "fast", ref_p), 2)
    out["l_impulse_max_db"] = _round_or_none(
        sl.time_weighted_max(decay_bp, fs, "impulse", ref_p), 2
    )
    out["crest_factor"] = (
        round(float(np.max(np.abs(ring_bp)) / signal_rms), 3) if signal_rms > 0 else None
    )

    return out
