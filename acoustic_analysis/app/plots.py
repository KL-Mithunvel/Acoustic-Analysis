"""Drawing functions for the app's charts.

Each takes a matplotlib ``Axes`` and one or more ``ClipData`` and draws onto it -
no figure or canvas handling here, so they are testable with the Agg backend.
The signal shown is exactly the one analysis uses (``conditioned_windows``).
"""

from __future__ import annotations

import numpy as np

from ..dsp import decay as _dec
from ..dsp import octave_bands as _ob
from ..dsp import spectrum as _spec
from ..features import conditioned_windows

_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]


def _windows(clip, cfg):
    try:
        return conditioned_windows(clip.samples, clip.fs, cfg)
    except ValueError:
        return None


def draw_waveform(ax, clip, cfg) -> None:
    x = np.asarray(clip.samples, dtype=float)
    t = np.arange(x.size) / clip.fs
    ax.plot(t, x, lw=0.5, color=_COLORS[0])
    ax.set_title("Waveform")
    ax.set_xlabel("time (s)")
    ax.set_ylabel("amplitude")

    w = _windows(clip, cfg)
    if w is not None:
        t0 = w["impact_index"] / clip.fs
        rw = cfg["analysis"]["ring_window_ms"]
        ax.axvline(t0, color="#d62728", lw=1.0)
        ax.axvspan(t0 + rw[0] / 1000.0, t0 + rw[1] / 1000.0, color="#2ca02c", alpha=0.15)


def draw_spectrum(ax, clips, cfg) -> None:
    low, high = cfg["analysis"]["bandpass_hz"]
    for i, clip in enumerate(clips):
        w = _windows(clip, cfg)
        if w is None:
            continue
        freqs, mag = _spec.fft_magnitude(w["ring_bp"], clip.fs)
        ax.semilogx(
            freqs[1:], 20 * np.log10(np.maximum(mag[1:], 1e-9)),
            lw=0.7, color=_COLORS[i % len(_COLORS)], label=clip.name,
        )
    ax.set_title("Spectrum (ring window)")
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("magnitude (dB)")
    ax.set_xlim(low * 0.7, high * 1.3)
    if len(clips) > 1:
        ax.legend(fontsize=7)


def draw_octave(ax, clips, cfg, profile=None) -> None:
    oct_cfg = cfg["octave"]
    width = 0.8 / max(1, len(clips))
    for i, clip in enumerate(clips):
        w = _windows(clip, cfg)
        if w is None:
            continue
        centres, levels = _ob.fractional_octave_levels(
            w["ring_bp"], clip.fs, fraction=oct_cfg["fraction"],
            f_min=oct_cfg["f_min_hz"], f_max=oct_cfg["f_max_hz"],
        )
        shape = _ob.band_shape(levels)
        pos = np.arange(len(centres)) + i * width
        ax.bar(pos, shape, width=width, color=_COLORS[i % len(_COLORS)], label=clip.name)
        ax.set_xticks(np.arange(len(centres)))
        ax.set_xticklabels([f"{c:.0f}" for c in centres], rotation=90, fontsize=6)
    if profile is not None and profile.octave_centres:
        ax.plot(
            np.arange(len(profile.shape_mean)), profile.shape_mean,
            color="#333333", lw=1.2, marker="o", ms=3, label="reference",
        )
    ax.set_title(f"1/{oct_cfg['fraction']}-octave band shape")
    ax.set_ylabel("level re total (dB)")
    if len(clips) > 1 or profile is not None:
        ax.legend(fontsize=7)


def draw_energy_decay(ax, clips, cfg) -> None:
    for i, clip in enumerate(clips):
        w = _windows(clip, cfg)
        if w is None:
            continue
        edc = _dec.energy_decay_curve(w["decay_bp"])
        t = np.arange(edc.size) / clip.fs * 1000.0
        ax.plot(t, edc, lw=0.9, color=_COLORS[i % len(_COLORS)], label=clip.name)
    ax.set_title("Energy-decay curve")
    ax.set_xlabel("time after strike (ms)")
    ax.set_ylabel("energy remaining (dB)")
    ax.set_ylim(-65, 2)
    if len(clips) > 1:
        ax.legend(fontsize=7)


def draw_filter_response(ax, chain, fs) -> None:
    freqs, mag_db = chain.frequency_response(fs)
    ax.semilogx(freqs, mag_db, lw=1.0, color=_COLORS[0])
    ax.set_title("Filter chain frequency response")
    ax.set_xlabel("frequency (Hz)")
    ax.set_ylabel("gain (dB)")
    ax.set_ylim(-60, 6)
    ax.axhline(0, color="#999999", lw=0.6)


def draw_signal_pair(ax, fs, before, after, labels=("original", "filtered")) -> None:
    for sig, name, color in zip((before, after), labels, (_COLORS[0], _COLORS[1])):
        sig = np.asarray(sig, dtype=float)
        t = np.arange(sig.size) / fs
        ax.plot(t, sig, lw=0.5, color=color, label=name)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("amplitude")
    ax.legend(fontsize=7)
