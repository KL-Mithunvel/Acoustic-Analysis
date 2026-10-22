"""Save each strike the Test Tile screen hears as a session the labelling tool can open.

The layout is the tile-line station's own (``strikes.json`` + ``clips/S0001_strike.wav`` + ``manifest.json``), so
``python main.py label data/sessions`` shows your own tests next to the station's, with the same
plots and the same label buttons. Files are written as they happen: a crash loses at most the strike in flight.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf


def _atomic_json(path: Path, data) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class StrikeLogger:
    def __init__(self, root: str | Path, fs: int, note: str = "", clock=time.time):
        root = Path(root)
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(clock()))
        folder, n = root / stamp, 1
        while folder.exists():
            n += 1
            folder = root / f"{stamp}_{n}"
        (folder / "clips").mkdir(parents=True)
        self.folder, self.fs, self._clock = folder, int(fs), clock
        self._events: list[dict] = []
        self._manifest = {"schema": 1, "id": folder.name, "status": "recording", "started": clock(),
                          "started_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(clock())),
                          "run_type": "tile", "note": note or "tests from the Test Tile screen",
                          "audio": {"sample_rate": self.fs, "channels": 1, "format": "float32 WAV"}}
        _atomic_json(folder / "manifest.json", self._manifest)
        _atomic_json(folder / "strikes.json", self._events)

    def add(self, samples: np.ndarray, *, source: str, tile_present: bool | None, tof_mm: int | None = None,
            t: float | None = None, nano_seq: int | None = None, nano_ms: int | None = None, verdict: str | None = None) -> str:
        """Write one strike's clip and record it. Returns its id (``S0001``...)."""
        sid = f"S{len(self._events) + 1:04d}"
        x = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
        sf.write(self.folder / "clips" / f"{sid}_strike.wav", x.astype(np.float32), self.fs, subtype="FLOAT")
        self._events.append({
            "id": sid, "kind": "strike", "source": source, "t": t if t is not None else self._clock(),
            "nano_ms": nano_ms, "nano_seq": nano_seq, "tile_present": tile_present, "tof_mm": tof_mm,
            "tile_id": None, "app_verdict": verdict,
            "labels": {"condition": "no_tile" if tile_present is False else "tile", "defect": None,
                       "tier": None, "tile_ref": None, "note": None},
        })
        _atomic_json(self.folder / "strikes.json", self._events)
        return sid

    @property
    def count(self) -> int:
        return len(self._events)

    def close(self) -> None:
        self._manifest["status"] = "complete"
        self._manifest["ended"] = self._clock()
        _atomic_json(self.folder / "manifest.json", self._manifest)
