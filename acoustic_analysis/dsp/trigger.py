"""Continuous sound trigger - cuts a clip out of a live stream each time a loud
event happens, with no knowledge of the striker.

Pure: feed it one block at a time, it returns a finished clip or ``None``. The
microphone wrapper (``io/recorder.SessionRecorder``) just calls ``process_block``.

The threshold can be **adaptive**: ``floor_mult`` x a slowly tracked estimate of
the background level. A running motor raises that floor, and the trigger rises
with it, so the user does not have to hand-tune an absolute RMS for every room
and motor speed. A fixed ``threshold`` overrides it.
"""

from __future__ import annotations

from collections import deque

import numpy as np


class SoundTrigger:
    def __init__(
        self,
        fs: float,
        block_size: int,
        pre_trigger_ms: float,
        capture_duration_s: float,
        cooldown_s: float,
        threshold: float | None = None,
        floor_mult: float = 6.0,
        min_threshold: float = 1e-4,
        floor_tau_s: float = 2.0,
        warmup_s: float = 0.5,
    ):
        if block_size <= 0 or fs <= 0:
            raise ValueError("fs and block_size must be positive")
        self.fs = float(fs)
        self.block = int(block_size)
        self.fixed_threshold = threshold
        self.floor_mult = float(floor_mult)
        self.min_threshold = float(min_threshold)
        self._pre_blocks = max(1, int(np.ceil(pre_trigger_ms / 1000.0 * fs / block_size)))
        self._total_n = int(round(capture_duration_s * fs))
        self._cooldown_blocks = int(np.ceil(cooldown_s * fs / block_size))
        self._alpha = min(1.0, block_size / (floor_tau_s * fs))
        self._warmup_blocks = int(np.ceil(warmup_s * fs / block_size))
        self.reset()

    def reset(self) -> None:
        self._ring: deque = deque(maxlen=self._pre_blocks)
        self._chunks: list[np.ndarray] = []
        self._collected = 0
        self._cooldown = 0
        self._seen = 0
        self.floor: float | None = None
        self.level = 0.0
        self.state = "warming up"       # warming up | listening | capturing | cooldown
        self.captured = 0

    @property
    def threshold(self) -> float:
        if self.fixed_threshold is not None:
            return float(self.fixed_threshold)
        if self.floor is None:
            return self.min_threshold
        return max(self.min_threshold, self.floor_mult * self.floor)

    def process_block(self, block: np.ndarray) -> np.ndarray | None:
        block = np.asarray(block, dtype=np.float64)
        rms = float(np.sqrt(np.mean(block**2))) if block.size else 0.0
        self.level = rms
        self._seen += 1

        if self._chunks:                                  # mid-capture
            self._chunks.append(block)
            self._collected += block.size
            if self._collected >= self._total_n:
                clip = np.concatenate(self._chunks)[: self._total_n]
                self._chunks, self._collected = [], 0
                self._cooldown = self._cooldown_blocks
                self.state = "cooldown"
                self.captured += 1
                self._ring.clear()
                return clip
            return None

        if self._cooldown > 0:
            self._cooldown -= 1
            self.state = "cooldown" if self._cooldown else "listening"
            return None

        # idle: track the background only from quiet blocks so a strike cannot
        # drag the floor (and so the threshold) up after itself
        if self.floor is None:
            self.floor = rms
        elif rms < self.threshold:
            self.floor += self._alpha * (rms - self.floor)

        if self._seen <= self._warmup_blocks:
            self.state = "warming up"
            self._ring.append(block)
            return None
        self.state = "listening"

        if rms >= self.threshold:
            self._chunks = list(self._ring) + [block]
            self._collected = sum(c.size for c in self._chunks)
            self.state = "capturing"
            if self._collected >= self._total_n:          # very short clip lengths
                return self.process_block(np.zeros(0))
            return None
        self._ring.append(block)
        return None
