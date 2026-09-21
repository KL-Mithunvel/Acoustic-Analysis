"""Drawing functions for the app's charts.

Each takes a matplotlib ``Axes`` and one or more ``ClipData`` and draws onto it -
no figure or canvas handling here, so they are testable with the Agg backend.
The signal shown is exactly the one analysis uses (``conditioned_windows``).
"""

from __future__ import annotations

import numpy as np

from ..dsp import decay as _dec
from ..dsp import octave_bands as _ob
from ..dsp import segmentation as _seg
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


# -- slicing a long take ---------------------------------------------------
# Colours for the Slice screen. Segments are drawn by state, because the one
# question an operator asks of the overview is "what have I not done yet".
_SEG_UNLABELLED = "#e6b053"   # cut, but no class yet
_SEG_LABELLED = "#4aa8ff"     # ready to save
_SEG_SAVED = "#4fc98a"        # already in the dataset
_ONSET = "#e85d52"
_PLAYHEAD = "#ededf1"


def _segment_color(seg) -> str:
    if getattr(seg, "saved", False):
        return _SEG_SAVED
    return _SEG_LABELLED if seg.labelled else _SEG_UNLABELLED


def _draw_segments(ax, segments, *, label_them: bool) -> None:
    for seg in segments:
        color = _segment_color(seg)
        ax.axvspan(seg.start_s, seg.end_s, color=color, alpha=0.22, lw=0)
        ax.axvline(seg.start_s, color=color, lw=0.8, alpha=0.8)
        if label_them:
            ax.annotate(
                str(seg.sid), xy=(seg.start_s, 0.96), xycoords=("data", "axes fraction"),
                color=color, fontsize=7, ha="left", va="top",
            )


def draw_take_overview(
    ax, mins, maxs, duration_s, *, segments=(), playhead_s=None, view=None
) -> None:
    """The whole recording at a glance: min/max envelope, every cut, the
    playhead, and a box round the part shown in the detail plot.

    Takes the decimated envelope rather than the signal itself - see
    ``dsp.segmentation.envelope_minmax`` for why plotting the raw samples is
    not an option at this length.
    """
    mins = np.asarray(mins, dtype=float)
    maxs = np.asarray(maxs, dtype=float)
    t = np.linspace(0.0, duration_s, mins.size, endpoint=False)
    ax.fill_between(t, mins, maxs, color=_COLORS[0], lw=0)

    _draw_segments(ax, segments, label_them=False)

    if view is not None:
        v0, v1 = view
        ax.axvspan(v0, v1, facecolor="none", edgecolor=_PLAYHEAD, lw=0.9, alpha=0.5)
    if playhead_s is not None:
        ax.axvline(playhead_s, color=_PLAYHEAD, lw=1.0)

    ax.set_xlim(0.0, max(duration_s, 1e-3))
    ax.set_xlabel("time (s)")
    ax.set_yticks([])
    ax.set_title("Whole take")


def draw_take_detail(
    ax, samples, fs, start_s, *, segments=(), onsets=(), playhead_s=None,
    selection=None, max_points=4000,
) -> None:
    """The zoomed view the operator actually cuts in.

    Detected strikes appear as dashed marks, existing snippets as bands, and
    the live selection as a brighter band on top.

    A wide view is drawn as a min/max envelope rather than as samples: at
    48 kHz even a 5-second window is 240 k points, and redrawing that while
    audio plays makes the screen stutter. Below ``max_points`` the real samples
    are drawn, which is what matters when trimming a cut to the millisecond.
    """
    x = np.asarray(samples, dtype=float)
    if x.size == 0:
        ax.text(0.5, 0.5, "no audio in view", ha="center", va="center", fontsize=8)
        return
    span_s = x.size / fs
    if x.size > max_points:
        lo, hi = _seg.envelope_minmax(x, max_points)
        t = start_s + np.linspace(0.0, span_s, lo.size, endpoint=False)
        ax.fill_between(t, lo, hi, color=_COLORS[0], lw=0)
    else:
        t = start_s + np.arange(x.size) / fs
        ax.plot(t, x, lw=0.5, color=_COLORS[0])

    _draw_segments(ax, segments, label_them=True)

    for onset in onsets:
        ax.axvline(onset, color=_ONSET, lw=0.9, ls=(0, (3, 2)), alpha=0.85)

    if selection is not None:
        s0, s1 = selection
        if s1 > s0:
            ax.axvspan(s0, s1, color=_PLAYHEAD, alpha=0.16, lw=0)
    if playhead_s is not None:
        ax.axvline(playhead_s, color=_PLAYHEAD, lw=1.0)

    # From the requested window, not the drawn points: decimation leaves the
    # last bucket short, and letting that set the limit would make the view
    # creep as the operator scrolls.
    ax.set_xlim(start_s, start_s + span_s)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("amplitude")
    ax.set_title("Detail - drag to select a snippet")
