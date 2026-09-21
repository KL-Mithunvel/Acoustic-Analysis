"""Synthetic signal generators for the test suite.

These are ground-truth signals whose correct analysis output can be worked out
by hand, so every pure DSP function can be verified without any recorded audio.
No project imports here on purpose.
"""

from __future__ import annotations

import numpy as np


def make_tone(freq_hz, duration_s, sample_rate, amplitude=1.0, phase=0.0):
    """A pure sine: ``amplitude * sin(2*pi*freq*t + phase)``."""
    n = int(round(duration_s * sample_rate))
    t = np.arange(n) / sample_rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t + phase)).astype(np.float64)


def make_multitone(freqs_hz, amps, duration_s, sample_rate):
    """Sum of sines at the given frequencies and amplitudes."""
    n = int(round(duration_s * sample_rate))
    out = np.zeros(n, dtype=np.float64)
    for f, a in zip(freqs_hz, amps):
        out += make_tone(f, duration_s, sample_rate, amplitude=a)
    return out


def make_decay(freq_hz, tau_s, duration_s, sample_rate, amplitude=1.0):
    """Exponentially decaying sinusoid ``A * e^(-t/tau) * sin(2*pi*f*t)``.

    The envelope drops by ``20/ln(10) * (t/tau)`` dB, i.e. ~8.686 dB per tau,
    so time-to-(-20 dB) is ``tau * 20 / 8.686`` and T30 is ``tau * 30 / 8.686``.
    """
    n = int(round(duration_s * sample_rate))
    t = np.arange(n) / sample_rate
    env = np.exp(-t / tau_s)
    return (amplitude * env * np.sin(2 * np.pi * freq_hz * t)).astype(np.float64)


def make_white_noise(duration_s, sample_rate, rms=1.0, seed=0):
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * sample_rate))
    return rng.normal(0.0, rms, n).astype(np.float64)


def make_impact_clip(
    sample_rate,
    pre_ms=100.0,
    ring_freqs=(2000.0,),
    tau_s=0.15,
    duration_s=0.6,
    noise_rms=1e-4,
    onset_amplitude=0.5,
    seed=0,
):
    """A clip shaped like a real tap test.

    Quiet noise-only pre-roll, then a sharp onset spike, then a decaying
    multi-mode ring. Returns ``(clip, impact_index)`` where ``impact_index`` is
    the exact sample where the ring starts.
    """
    rng = np.random.default_rng(seed)
    n_total = int(round(duration_s * sample_rate))
    n_pre = int(round(pre_ms / 1000.0 * sample_rate))
    clip = rng.normal(0.0, noise_rms, n_total)

    ring_len = n_total - n_pre
    t = np.arange(ring_len) / sample_rate
    ring = np.zeros(ring_len, dtype=np.float64)
    for i, f in enumerate(ring_freqs):
        ring += (1.0 / (i + 1)) * np.exp(-t / tau_s) * np.sin(2 * np.pi * f * t)

    onset_len = max(1, int(round(0.001 * sample_rate)))
    ring[:onset_len] += onset_amplitude

    clip[n_pre:] += ring
    return clip.astype(np.float64), n_pre


def make_tap_sequence(
    sample_rate,
    tap_times_s,
    duration_s,
    ring_freq_hz=2500.0,
    tau_s=0.08,
    amplitude=0.6,
    noise_rms=2e-3,
    seed=0,
):
    """A long take with strikes at known times - a stand-in for tap-test video.

    Quiet room noise throughout, plus one decaying ring starting at each time in
    ``tap_times_s``. ``detect_onsets`` run over this must return those times
    back, which is the property the slicing tests assert.
    """
    rng = np.random.default_rng(seed)
    n = int(round(duration_s * sample_rate))
    x = rng.normal(0.0, noise_rms, n)

    for t0 in tap_times_s:
        start = int(round(t0 * sample_rate))
        if not 0 <= start < n:
            continue
        length = min(n - start, int(round(6 * tau_s * sample_rate)))
        t = np.arange(length) / sample_rate
        x[start:start + length] += (
            amplitude * np.exp(-t / tau_s) * np.sin(2 * np.pi * ring_freq_hz * t)
        )
    return x.astype(np.float64)
