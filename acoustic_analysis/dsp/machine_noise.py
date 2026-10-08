"""Removing the machine's own sound from a tap clip.

Two different noises, two different tools:

* **Motor hum** is steady -> the existing spectral profile (``noise.reduce_noise``).
* **The striker without a tile** (solenoid click, mechanism rattle, ball landing
  on an empty fixture) is short, sharp and repeats nearly identically every
  cycle -> a *time-domain template*: record the striker firing with no tile,
  align every strike on its onset, average. Averaging keeps what repeats (the
  striker) and cancels what does not (motor, room). The template is then lined
  up with each real strike and subtracted; what is left is the tile.

If the dry strikes are not repeatable the template is untrustworthy, so
``build_striker_template`` reports a repeatability score instead of pretending.
A strike whose residual is barely above the floor had no tile in it
(``verdict == "no_tile"``) - which doubles as a noise-vs-tap check.

Pure numpy; thresholds come from ``config.yaml`` ``machine:``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import noise as _noise
from .conditioning import detect_impact


@dataclass
class StrikerTemplate:
    samples: np.ndarray        # template waveform, onset at index pre_n
    pre_n: int                 # samples before the onset
    fs: int
    repeatability: float       # 0..1 mean correlation of dry strikes with the template
    n_used: int
    n_rejected: int


@dataclass
class CleanResult:
    samples: np.ndarray        # cleaned clip, same length as the input
    onset: int | None          # detected strike index (None if none found)
    scale: float               # fitted template amplitude (1.0 = identical strike)
    residual_snr_db: float | None
    verdict: str               # "tile" | "no_tile" | "no_strike"


def _onset(x: np.ndarray, fs: float, pre_ms: float, mult: float) -> int | None:
    try:
        return detect_impact(x, int(pre_ms / 1000.0 * fs), mult)
    except ValueError:
        return None


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    den = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / den) if den > 0 else 0.0


def build_striker_template(clips: list[np.ndarray], fs: int, cfg: dict) -> StrikerTemplate:
    """Average dry-strike clips (striker firing, no tile) aligned on onset.

    Raises ValueError if fewer than ``machine.min_dry_strikes`` clips contain a
    detectable strike.
    """
    m = cfg["machine"]
    pre_ms = float(cfg["capture"]["pre_trigger_ms"])
    pre_n = int(m["template_pre_ms"] / 1000.0 * fs)
    len_n = int(m["template_ms"] / 1000.0 * fs)

    windows = []
    for clip in clips:
        clip = np.asarray(clip, dtype=np.float64)
        on = _onset(clip, fs, min(pre_ms, m["template_pre_ms"] * 4), m["onset_threshold_mult"])
        if on is None or on - pre_n < 0 or on + len_n > clip.size:
            continue
        windows.append(clip[on - pre_n : on + len_n])
    if len(windows) < int(m["min_dry_strikes"]):
        raise ValueError(
            f"only {len(windows)} usable dry strike(s) of {len(clips)}; "
            f"need at least {m['min_dry_strikes']}"
        )

    stack = np.vstack(windows)
    template = stack.mean(axis=0)
    # repeatability over the strike itself, not the quiet lead-in
    body = slice(pre_n, pre_n + int(m["fit_ms"] / 1000.0 * fs))
    rep = float(np.mean([_corr(w[body], template[body]) for w in windows]))
    return StrikerTemplate(template, pre_n, int(fs), max(0.0, rep), len(windows), len(clips) - len(windows))


def subtract_striker(
    x: np.ndarray, fs: int, template: StrikerTemplate, onset: int, cfg: dict
) -> tuple[np.ndarray, float]:
    """Fit the template to the strike at ``onset`` and subtract it.

    Alignment is refined +/- ``machine.max_shift_ms`` by cross-correlation over
    the first ``fit_ms`` (the click, which a tile's slower ring barely affects),
    then amplitude is least-squares fitted on that same span and clamped to
    ``[0, machine.max_scale]`` so a bad fit cannot add energy. Returns
    ``(cleaned, scale)``.
    """
    m = cfg["machine"]
    x = np.asarray(x, dtype=np.float64)
    t = template.samples
    fit_n = int(m["fit_ms"] / 1000.0 * fs)
    shift_n = int(m["max_shift_ms"] / 1000.0 * fs)
    t_fit = t[template.pre_n : template.pre_n + fit_n]

    best_shift, best_c = 0, -np.inf
    for s in range(-shift_n, shift_n + 1):
        a = onset + s
        if a < 0 or a + fit_n > x.size:
            continue
        c = _corr(x[a : a + fit_n], t_fit)
        if c > best_c:
            best_c, best_shift = c, s

    start = onset + best_shift - template.pre_n
    seg_lo, seg_hi = max(0, start), min(x.size, start + t.size)
    if seg_lo >= seg_hi:
        return x.copy(), 0.0
    t_seg = t[seg_lo - start : seg_hi - start]

    a0 = onset + best_shift
    xf = x[a0 : a0 + fit_n]
    tf = t_fit[: xf.size]
    denom = float(np.dot(tf, tf))
    scale = float(np.dot(xf, tf) / denom) if denom > 0 else 0.0
    scale = float(np.clip(scale, 0.0, m["max_scale"]))

    out = x.copy()
    out[seg_lo:seg_hi] -= scale * t_seg
    return out, scale


def clean_clip(
    x: np.ndarray,
    fs: int,
    cfg: dict,
    template: StrikerTemplate | None = None,
    motor_noise: np.ndarray | None = None,
) -> CleanResult:
    """Full machine-noise removal for one captured clip.

    1. find the strike; 2. subtract the striker template (time domain);
    3. subtract the motor profile (spectral); 4. judge whether anything but the
    machine is left in the ring window.
    """
    m = cfg["machine"]
    x = np.asarray(x, dtype=np.float64)
    pre_ms = float(cfg["capture"]["pre_trigger_ms"])
    onset = _onset(x, fs, pre_ms, m["onset_threshold_mult"])
    if onset is None:
        return CleanResult(x.copy(), None, 0.0, None, "no_strike")

    y, scale = x.copy(), 0.0
    if template is not None:
        y, scale = subtract_striker(y, fs, template, onset, cfg)
    if motor_noise is not None:
        nper = int(cfg["noise"].get("stft_nperseg", 2048))
        if y.size >= nper and len(motor_noise) >= nper:
            y = _noise.reduce_noise(
                y, fs, motor_noise,
                strength=float(m["motor_strength"]), method=cfg["noise"].get("method", "subtraction"),
                nperseg=nper, floor_db=float(cfg["noise"].get("floor_db", -25.0)),
            )

    lo = onset + int(m["residual_skip_ms"] / 1000.0 * fs)
    hi = min(y.size, onset + int(m["residual_window_ms"] / 1000.0 * fs))
    pre = y[: max(1, int(pre_ms / 1000.0 * fs) // 2)]
    noise_rms = float(np.sqrt(np.mean(pre**2)))
    if hi <= lo or noise_rms <= 0:
        return CleanResult(y, onset, scale, None, "no_tile")
    res_rms = float(np.sqrt(np.mean(y[lo:hi] ** 2)))
    snr = float(20.0 * np.log10(max(res_rms, 1e-12) / noise_rms))
    verdict = "tile" if snr >= float(m["min_residual_snr_db"]) else "no_tile"
    return CleanResult(y, onset, scale, snr, verdict)
