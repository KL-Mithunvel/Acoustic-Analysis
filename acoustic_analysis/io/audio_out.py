"""Speaker playback for A/B listening (original vs filtered / denoised) and for
auditioning snippets while slicing a recording.

Thin wrapper around ``sounddevice``; not unit-tested.
"""

from __future__ import annotations

import threading

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
        Player.stop_all()


class Player:  # pragma: no cover - hardware
    """Playback that can say where it is.

    ``sd.play`` is fire-and-forget: it cannot report a position, which is
    exactly what a moving playhead over a waveform needs. This drives an
    ``OutputStream`` instead and counts the frames it has handed to the device,
    so the GUI can ask ``position_s`` on its normal refresh tick.

    One clip at a time. Starting a new one stops the old, because two taps
    playing over each other tells the operator nothing.

    The frame counter is written from PortAudio's callback thread and read from
    the Tk thread. It is a single int, and Python's int assignment is atomic
    under the GIL, so it is read without a lock - a one-block-stale playhead is
    invisible at 60 ms and a lock in an audio callback is not worth it.
    """

    _active: "Player | None" = None
    _active_lock = threading.Lock()

    def __init__(self, samples, fs: float, start_frame: int = 0, device=None):
        if _sd is None:
            raise RuntimeError("sounddevice / PortAudio is not available on this machine")
        data = np.asarray(samples, dtype=np.float32).reshape(-1)
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        self._data = data / peak if peak > 1.0 else data
        self._fs = int(fs)
        self._offset = max(0, int(start_frame))
        self._cursor = self._offset
        self._finished = threading.Event()
        self._stream = _sd.OutputStream(
            samplerate=self._fs,
            channels=1,
            dtype="float32",
            callback=self._callback,
            finished_callback=self._finished.set,
            device=device,
        )

    # -- stream -----------------------------------------------------------
    def _callback(self, outdata, frames, _time, _status):
        end = self._cursor + frames
        chunk = self._data[self._cursor:end]
        outdata[: chunk.size, 0] = chunk
        if chunk.size < frames:
            outdata[chunk.size:, 0] = 0.0
            self._cursor = self._data.size
            raise _sd.CallbackStop
        self._cursor = end

    def start(self) -> "Player":
        with Player._active_lock:
            if Player._active is not None and Player._active is not self:
                Player._active.stop()
            Player._active = self
        self._stream.start()
        return self

    def stop(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:  # noqa: BLE001 - closing an already-dead stream
            pass
        self._finished.set()
        with Player._active_lock:
            if Player._active is self:
                Player._active = None

    @classmethod
    def stop_all(cls) -> None:
        with cls._active_lock:
            active = cls._active
        if active is not None:
            active.stop()

    # -- state ------------------------------------------------------------
    @property
    def position_frames(self) -> int:
        return int(self._cursor)

    @property
    def position_s(self) -> float:
        return self._cursor / self._fs

    @property
    def is_playing(self) -> bool:
        return not self._finished.is_set() and self._cursor < self._data.size


def play_region(samples, fs: float, start_s: float = 0.0, end_s: float | None = None) -> Player:  # pragma: no cover
    """Play ``samples`` between two times and return the running Player.

    The slice is taken here rather than inside ``Player`` so the returned
    positions are relative to the region, which is what a per-snippet audition
    wants to show.
    """
    data = np.asarray(samples).reshape(-1)
    start = max(0, int(round(start_s * fs)))
    end = data.size if end_s is None else min(data.size, int(round(end_s * fs)))
    if end <= start:
        raise ValueError(f"play_region: empty region {start_s}-{end_s}s")
    return Player(data[start:end], fs).start()
