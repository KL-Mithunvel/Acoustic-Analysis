"""Shared application state - the loaded clips, the selection, the reference
profile, the live input level. Thread-safe: the worker thread writes results,
the Tk thread reads. Change listeners are called (on whatever thread caused the
change) so screens can refresh.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np


@dataclass
class ClipData:
    name: str
    samples: np.ndarray
    fs: int
    source: str = "file"          # "file" | "recorded" | "synthetic"
    path: str | None = None
    features: dict | None = None
    grade: dict | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return len(self.samples) / self.fs


class SharedState:
    def __init__(self, cfg: dict):
        self._lock = threading.RLock()
        self.cfg = cfg
        self._clips: list[ClipData] = []
        self._selection: list[int] = []
        self.profile = None
        self.live_rms: float = 0.0
        self._listeners: list = []

    # -- listeners -----------------------------------------------------
    def add_listener(self, fn) -> None:
        with self._lock:
            self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            fn()

    # -- clips -------------------------------------------------------
    def add_clip(self, clip: ClipData, select: bool = True) -> int:
        with self._lock:
            self._clips.append(clip)
            index = len(self._clips) - 1
            if select:
                self._selection = [index]
        self._notify()
        return index

    def clips(self) -> list[ClipData]:
        with self._lock:
            return list(self._clips)

    def clip(self, index: int) -> ClipData:
        with self._lock:
            return self._clips[index]

    def remove_clip(self, index: int) -> None:
        with self._lock:
            if 0 <= index < len(self._clips):
                self._clips.pop(index)
                self._selection = [i for i in self._selection if i != index]
                self._selection = [i - 1 if i > index else i for i in self._selection]
        self._notify()

    def set_analysis(self, index: int, features: dict | None, grade: dict | None) -> None:
        with self._lock:
            if 0 <= index < len(self._clips):
                self._clips[index].features = features
                self._clips[index].grade = grade
        self._notify()

    # -- selection --------------------------------------------------
    def select(self, indices) -> None:
        with self._lock:
            self._selection = [i for i in indices if 0 <= i < len(self._clips)]
        self._notify()

    def selection(self) -> list[int]:
        with self._lock:
            return list(self._selection)

    def selected_clips(self) -> list[ClipData]:
        with self._lock:
            return [self._clips[i] for i in self._selection if 0 <= i < len(self._clips)]

    def primary(self) -> ClipData | None:
        with self._lock:
            if self._selection and 0 <= self._selection[0] < len(self._clips):
                return self._clips[self._selection[0]]
        return None
