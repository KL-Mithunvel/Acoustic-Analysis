"""Background analysis worker.

Screens call ``submit(clip_index)``; the worker thread runs feature extraction
and grading and puts the result on a queue that the Tk thread drains with
``poll()`` from a periodic ``after()`` callback. Keeps all DSP off the UI thread.
"""

from __future__ import annotations

import queue
import threading
import traceback

from ..features import extract_features
from .state import SharedState

_STOP = object()


class AnalysisService:
    def __init__(self, state: SharedState):
        self.state = state
        self._jobs: queue.Queue = queue.Queue()
        self._results: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="analysis", daemon=True)
        self._thread.start()

    def submit(self, clip_index: int) -> None:
        self._jobs.put(clip_index)

    def submit_selection(self) -> None:
        for i in self.state.selection():
            self._jobs.put(i)

    def poll(self) -> list[dict]:
        """Non-blocking: return every finished result since the last call.

        Each item: ``{"index", "features", "grade", "error"}``. Results are also
        written back into ``SharedState`` before being returned.
        """
        out = []
        while True:
            try:
                item = self._results.get_nowait()
            except queue.Empty:
                break
            if item.get("error") is None:
                self.state.set_analysis(item["index"], item["features"], item["grade"])
            out.append(item)
        return out

    def stop(self) -> None:
        self._jobs.put(_STOP)

    # -- worker ------------------------------------------------------
    def _loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is _STOP:
                return
            try:
                clip = self.state.clip(job)
                feats = extract_features(clip.samples, clip.fs, self.state.cfg)
                grade_result = None
                if self.state.profile is not None:
                    from ..classify.rules import grade

                    grade_result = grade(feats, self.state.profile, self.state.cfg)
                self._results.put(
                    {"index": job, "features": feats, "grade": grade_result, "error": None}
                )
            except Exception:  # noqa: BLE001 - report, don't crash the worker
                self._results.put(
                    {"index": job, "features": None, "grade": None, "error": traceback.format_exc()}
                )
