"""Save / load the rig's machine-noise profile (motor recording + striker template).

One ``.npz`` file, so the Collect screen can reload last session's calibration
instead of asking for it again. A profile is only valid for the sample rate it
was recorded at - ``load`` returns it as-is and the caller compares ``fs``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..dsp.machine_noise import StrikerTemplate


@dataclass
class MachineProfile:
    fs: int
    motor_noise: np.ndarray | None = None
    template: StrikerTemplate | None = None

    @property
    def ready(self) -> bool:
        return self.motor_noise is not None or self.template is not None


def save_profile(profile: MachineProfile, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict = {"fs": np.array(profile.fs)}
    if profile.motor_noise is not None:
        arrays["motor_noise"] = np.asarray(profile.motor_noise, dtype=np.float32)
    t = profile.template
    if t is not None:
        arrays["template"] = np.asarray(t.samples, dtype=np.float32)
        arrays["template_meta"] = np.array([t.pre_n, t.n_used, t.n_rejected, t.repeatability])
    np.savez_compressed(path, **arrays)
    return path


def load_profile(path) -> MachineProfile | None:
    """Return the saved profile, or ``None`` if the file is absent or unreadable."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        with np.load(path) as z:
            fs = int(z["fs"])
            motor = z["motor_noise"].astype(np.float64) if "motor_noise" in z else None
            tpl = None
            if "template" in z:
                pre_n, used, rej, rep = z["template_meta"]
                tpl = StrikerTemplate(z["template"].astype(np.float64), int(pre_n), fs, float(rep),
                                      int(used), int(rej))
    except (OSError, ValueError, KeyError):
        return None
    return MachineProfile(fs, motor, tpl)
