"""Composable filter chain (docs/METHODS.md section 3, docs/UI_DESIGN.md Filters).

One object that holds the whole processing chain - band-pass, any number of
notches, a weighting curve - and can both apply it to a signal and report its
frequency response for a Bode plot, so the GUI shows exactly what feeds analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import butter, iirnotch, sosfilt, sosfiltfilt, sosfreqz, tf2sos

from . import weighting as _weighting


@dataclass
class FilterChain:
    """A cascade of: optional band-pass -> zero or more notches -> weighting.

    ``bandpass``: ``(low_hz, high_hz)`` or ``None``.
    ``notches``: list of ``(freq_hz, Q)``.
    ``weighting``: ``"A"``, ``"C"`` or ``"Z"`` (flat).
    """

    bandpass: tuple[float, float] | None = None
    bandpass_order: int = 4
    notches: list[tuple[float, float]] = field(default_factory=list)
    weighting: str = "Z"

    @classmethod
    def from_config(cls, cfg: dict) -> "FilterChain":
        ana = cfg["analysis"]
        bp = ana.get("bandpass_hz")
        return cls(
            bandpass=(float(bp[0]), float(bp[1])) if bp else None,
            bandpass_order=int(ana.get("bandpass_order", 4)),
            notches=[(float(f), float(q)) for f, q in ana.get("notches", [])],
            weighting=cfg.get("weighting", {}).get("default", "Z"),
        )

    def _stages(self, fs: float) -> list[np.ndarray]:
        nyq = 0.5 * fs
        stages: list[np.ndarray] = []

        if self.bandpass is not None:
            low, high = self.bandpass
            if not (0 < low < high < nyq):
                raise ValueError(f"FilterChain: bad band {self.bandpass} for fs={fs}")
            stages.append(
                butter(self.bandpass_order, [low / nyq, high / nyq], btype="band", output="sos")
            )

        for f0, q in self.notches:
            if not (0 < f0 < nyq) or q <= 0:
                raise ValueError(f"FilterChain: bad notch ({f0}, {q}) for fs={fs}")
            b, a = iirnotch(f0 / nyq, q)
            stages.append(tf2sos(b, a))

        w = self.weighting.upper()
        if w in ("A", "C"):
            stages.append(_weighting.weighting_sos(w, fs))
        elif w != "Z":
            raise ValueError("weighting must be 'A', 'C' or 'Z'")

        return stages

    def apply(self, x: np.ndarray, fs: float, zero_phase: bool = True) -> np.ndarray:
        """Filter ``x`` through the chain.

        ``zero_phase`` (default) uses ``filtfilt`` so peaks are not shifted in
        time - the right choice for analysis. It falls back to a causal pass on
        signals too short for the filter's edge padding.
        """
        y = np.asarray(x, dtype=np.float64)
        for sos in self._stages(fs):
            padlen = 3 * (sos.shape[0] * 2 + 1)
            if zero_phase and y.size > padlen:
                y = sosfiltfilt(sos, y)
            else:
                y = sosfilt(sos, y)
        return y

    def frequency_response(self, fs: float, n: int = 2048) -> tuple[np.ndarray, np.ndarray]:
        """Combined single-pass magnitude response, as ``(freqs_hz, mag_db)``.

        With ``zero_phase=True`` at ``apply`` time the effective attenuation in
        dB is doubled; this returns the nominal (single-pass) curve.
        """
        w = np.linspace(0.0, np.pi, n, endpoint=False)[1:]
        h = np.ones(w.size, dtype=complex)
        for sos in self._stages(fs):
            _, hi = sosfreqz(sos, worN=w)
            h *= hi
        freqs = w * fs / (2.0 * np.pi)
        mag_db = 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))
        return freqs, mag_db

    def describe(self) -> list[str]:
        """Human-readable one-line-per-stage summary, for the UI."""
        out: list[str] = []
        if self.bandpass:
            out.append(
                f"band-pass {self.bandpass[0]:.0f}-{self.bandpass[1]:.0f} Hz "
                f"(order {self.bandpass_order})"
            )
        for f0, q in self.notches:
            out.append(f"notch {f0:.0f} Hz (Q {q:g})")
        w = self.weighting.upper()
        out.append("Z weighting (flat)" if w == "Z" else f"{w} weighting")
        return out
