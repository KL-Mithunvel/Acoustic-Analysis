"""Speaker playback for A/B listening (original vs filtered / denoised).

Thin wrapper around ``sounddevice``; not unit-tested.
"""

from __future__ import annotations

import numpy as np

try:  # pragma: no cover - hardware dependent
    import sounddevice as _sd
except (OSError, ImportError):  # pragma: no cover
    _sd = None


def is_available() -> bool:
    return _sd is not None


def play(samples, fs: float, blocking: bool = False, device=None) -> None:  # pragma: no cover
    """Play ``samples`` through the default (or given) output device.

    The signal is peak-normalised to <= 1.0 so a loud clip cannot blast the
    speakers.
    """
    if _sd is None:
        raise RuntimeError("sounddevice / PortAudio is not available on this machine")
    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak > 1.0:
        data = data / peak
    _sd.play(data, int(fs), blocking=blocking, device=device)


def stop() -> None:  # pragma: no cover
    if _sd is not None:
        _sd.stop()
