"""Read and write clip WAV files with a JSON metadata sidecar."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf


def _sidecar_path(wav_path: Path) -> Path:
    return wav_path.with_suffix(wav_path.suffix + ".json")


def save_clip(samples, fs: float, path, metadata: dict | None = None) -> Path:
    """Write ``samples`` as a mono 32-bit float WAV plus ``<path>.json``.

    Returns the WAV path. Parent directories are created as needed.
    """
    wav_path = Path(path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    sf.write(wav_path, data, int(fs), subtype="FLOAT")

    meta = {
        "sample_rate": int(fs),
        "n_samples": int(data.size),
        "duration_s": round(data.size / fs, 4),
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if metadata:
        meta.update(metadata)
    _sidecar_path(wav_path).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return wav_path


def load_clip(path) -> tuple[np.ndarray, int, dict]:
    """Return ``(samples_float64_mono, sample_rate, metadata)``.

    Stereo files are averaged to mono. The sidecar is optional; an empty dict is
    returned when it is missing.
    """
    wav_path = Path(path)
    data, fs = sf.read(wav_path, dtype="float64", always_2d=False)
    if data.ndim == 2:
        data = data.mean(axis=1)

    sidecar = _sidecar_path(wav_path)
    meta = json.loads(sidecar.read_text(encoding="utf-8")) if sidecar.is_file() else {}
    return np.asarray(data, dtype=np.float64), int(fs), meta
