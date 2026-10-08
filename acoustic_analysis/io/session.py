"""What happens to each clip the sound trigger captures during a collection run.

``SessionStore.handle`` cleans the clip of machine noise, files it, and returns
what it did, so the Collect screen only has to display the result:

    <session>/tap-001.wav          cleaned clip that has a tile ringing in it
    <session>/rejected/tap-002.wav strike with no tile (or no strike) - the
                                   automatic noise-vs-tap sort
    <session>/.raw/tap-001.wav     the untouched capture, always kept, so
                                   nothing is lost if the cleaning is wrong

The sort is a suggestion, not a verdict: a rejected clip can be moved back from
the Library. Files only - no GUI, no microphone.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from ..dsp.machine_noise import clean_clip
from .library import Library
from .machine_profile import MachineProfile
from .wavstore import save_clip

REJECTED = "rejected"
RAW = ".raw"


@dataclass
class SavedClip:
    seq: int
    name: str
    path: Path                 # where the (cleaned) clip was filed
    raw_path: Path
    verdict: str               # tile | no_tile | no_strike
    residual_snr_db: float | None
    scale: float

    @property
    def accepted(self) -> bool:
        return self.verdict == "tile"


def new_session_folder(library: Library, parent="", now: datetime | None = None) -> Path:
    """Create ``YYYY-MM-DD_NN`` (first free NN) under ``parent``; return its path."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    n = 1
    while (library.resolve(parent) / f"{stamp}_{n:02d}").exists():
        n += 1
    return library.make_folder(parent, f"{stamp}_{n:02d}")


class SessionStore:
    def __init__(self, library: Library, folder, cfg: dict, profile: MachineProfile | None = None):
        self.library = library
        self.folder = library.resolve(folder)
        self.cfg = cfg
        self.profile = profile
        self.clips: list[SavedClip] = []
        self._seq = len([p for p in self.folder.rglob("tap-*.wav") if RAW not in p.parts])

    def handle(self, raw: np.ndarray, fs: int) -> SavedClip:
        self._seq += 1
        name = f"tap-{self._seq:03d}"
        prof = self.profile
        res = clean_clip(
            raw, fs, self.cfg,
            template=prof.template if prof else None,
            motor_noise=prof.motor_noise if prof else None,
        )
        raw_path = save_clip(raw, fs, self.folder / RAW / f"{name}.wav", {"kind": "raw"})
        dest = self.folder if res.verdict == "tile" else self.folder / REJECTED
        meta = {
            "kind": "cleaned",
            "verdict": res.verdict,
            "residual_snr_db": None if res.residual_snr_db is None else round(res.residual_snr_db, 2),
            "striker_scale": round(res.scale, 3),
            "onset_sample": res.onset,
            "machine_cleaned": bool(prof and prof.ready),
        }
        path = save_clip(res.samples, fs, dest / f"{name}.wav", meta)
        saved = SavedClip(self._seq, name, path, raw_path, res.verdict, res.residual_snr_db, res.scale)
        self.clips.append(saved)
        return saved

    def counts(self) -> dict:
        return {
            "total": len(self.clips),
            "tile": sum(c.verdict == "tile" for c in self.clips),
            "no_tile": sum(c.verdict == "no_tile" for c in self.clips),
            "no_strike": sum(c.verdict == "no_strike" for c in self.clips),
        }
