"""A continuous microphone recording you can cut a clip out of *after* the event.

The striker Nano says "strike now" over serial; the strike's sound is already in (or about to reach)
the microphone stream. So the mic runs all the time into a ring buffer stamped with wall-clock times,
and when a ``TAP`` arrives the clip is cut around that moment - a window that starts before it, like
the station's own 1.5 s clips (strike about 0.5 s in), so the same features apply.

``RingBuffer`` is pure (numpy only) and is what the tests cover; ``AudioRing`` is the thin
``sounddevice`` wrapper around it and, like the other hardware wrappers here, is smoke-tested only.
"""

from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np

try:  # pragma: no cover - hardware dependent
    import sounddevice as _sd
except (OSError, ImportError):  # pragma: no cover
    _sd = None


class RingBuffer:
    """The last ``seconds`` of audio with a wall-clock time for every block.

    Each ``append`` says when its first sample was captured; times between blocks are interpolated
    from the nearest earlier block, so a late or jittery block cannot skew a window by more than its own error.
    """

    def __init__(self, fs: int, seconds: float):
        self.fs = int(fs)
        self.cap = int(seconds * self.fs)
        self._buf = np.zeros(self.cap, dtype=np.float32)
        self.total = 0                                   # samples ever appended
        self._anchors: deque[tuple[int, float]] = deque()   # (global index of a block's first sample, its wall time)
        self._lock = threading.Lock()

    def append(self, block: np.ndarray, t_start: float) -> None:
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        n = block.size
        if n == 0:
            return
        with self._lock:
            if n >= self.cap:                            # a block longer than the whole ring: keep its tail
                block, skipped = block[-self.cap:], n - self.cap
                t_start += skipped / self.fs
                self.total += skipped
                n = block.size
            pos = self.total % self.cap
            first = min(n, self.cap - pos)
            self._buf[pos:pos + first] = block[:first]
            if first < n:
                self._buf[: n - first] = block[first:]
            self._anchors.append((self.total, float(t_start)))
            self.total += n
            oldest = self.total - self.cap
            while len(self._anchors) > 1 and self._anchors[1][0] <= oldest:
                self._anchors.popleft()

    @property
    def latest_time(self) -> float | None:
        """Wall time just after the newest sample (``None`` before any audio)."""
        with self._lock:
            if not self._anchors:
                return None
            idx, t = self._anchors[-1]
            return t + (self.total - idx) / self.fs

    def _index_at(self, t: float) -> float:
        """Global (fractional) sample index for wall time ``t`` from the last anchor at or before it."""
        best = self._anchors[0]
        for a in self._anchors:
            if a[1] <= t:
                best = a
            else:
                break
        return best[0] + (t - best[1]) * self.fs

    def window(self, t0: float, t1: float) -> np.ndarray | None:
        """Audio between two wall times, or ``None`` if any of it is not (or no longer) in the buffer."""
        with self._lock:
            if not self._anchors or t1 <= t0:
                return None
            i0, i1 = int(round(self._index_at(t0))), int(round(self._index_at(t1)))
            if i0 < max(self.total - self.cap, 0) or i1 > self.total or i1 <= i0:
                return None
            idx = np.arange(i0, i1) % self.cap
            return self._buf[idx].astype(np.float64)


class AudioRing:  # pragma: no cover - hardware dependent
    """Open the microphone and keep ``RingBuffer`` fed. ``level`` is a live RMS for a meter."""

    def __init__(self, cfg: dict, device=None, seconds: float = 12.0):
        if _sd is None:
            raise RuntimeError("sounddevice / PortAudio is not available on this machine")
        audio = cfg["audio"]
        self.fs = int(audio["sample_rate"])
        self.block = int(audio.get("block_size", 1024))
        self.device = audio["device"] if device is None else device
        self.gain = float(cfg["capture"].get("input_gain", 1.0))
        self.ring = RingBuffer(self.fs, seconds)
        self.level = 0.0
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        mono = indata[:, 0].astype(np.float64) * self.gain
        now = time.time()
        try:                                             # the moment the block was actually captured, not when we got it
            t_adc = now - (time_info.currentTime - time_info.inputBufferAdcTime)
        except Exception:  # noqa: BLE001
            t_adc = now - frames / self.fs
        self.level = float(np.sqrt(np.mean(mono ** 2))) if mono.size else 0.0
        self.ring.append(mono, t_adc)

    def start(self) -> None:
        self._stream = _sd.InputStream(samplerate=self.fs, blocksize=self.block, channels=1,
                                       device=self.device, callback=self._callback)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    @property
    def running(self) -> bool:
        return self._stream is not None

    def cut_after(self, t_event: float, pre_s: float, post_s: float, wait_s: float = 3.0) -> np.ndarray | None:
        """Wait (blocking) until ``post_s`` after the event has been recorded, then return the window. Run off the GUI thread."""
        end = t_event + post_s
        deadline = time.time() + wait_s
        while time.time() < deadline:
            latest = self.ring.latest_time
            if latest is not None and latest >= end:
                break
            time.sleep(0.02)
        return self.ring.window(t_event - pre_s, end)
