"""Reference profile - the acoustic fingerprint of a known-good part type.

Built from the feature dicts of several good clips; ``compare`` scores a new
clip's features against it as per-key z-scores plus one aggregate deviation.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# Scalar features tracked in the profile (mean + std).
SCALAR_KEYS = [
    "dominant_freq_hz", "spectral_centroid_hz", "spectral_bandwidth_hz",
    "spectral_rolloff_hz", "spectral_flatness", "t20_s", "t30_s",
    "decay_rate_db_s", "fastest_band_decay_db_s", "leq_z_db", "crest_factor",
    "high_to_low",  # pulled from band_ratios
]


def _scalar(features: dict, key: str):
    if key == "high_to_low":
        return features.get("band_ratios", {}).get("high_to_low")
    return features.get(key)


class ReferenceProfile:
    def __init__(self, part_type, stats, octave_centres, shape_mean, shape_std, n):
        self.part_type = part_type
        self.stats = stats                      # {key: {"mean": float, "std": float}}
        self.octave_centres = list(octave_centres)
        self.shape_mean = list(shape_mean)
        self.shape_std = list(shape_std)
        self.n = int(n)

    # -- construction ----------------------------------------------------
    @classmethod
    def build(cls, feature_dicts, part_type: str = "") -> "ReferenceProfile":
        valid = [f for f in feature_dicts if f.get("valid")]
        if len(valid) < 3:
            raise ValueError("ReferenceProfile.build: need at least 3 valid feature sets")

        stats: dict[str, dict] = {}
        for key in SCALAR_KEYS:
            vals = [float(_scalar(f, key)) for f in valid if isinstance(_scalar(f, key), (int, float))]
            if len(vals) >= 3:
                stats[key] = {"mean": float(np.mean(vals)), "std": float(np.std(vals, ddof=1))}

        centres = valid[0].get("octave_centres_hz", [])
        rows = [
            [np.nan if v is None else float(v) for v in f["octave_band_shape_db"]]
            for f in valid
            if f.get("octave_band_shape_db") and f.get("octave_centres_hz") == centres
        ]
        if rows:
            arr = np.array(rows, dtype=float)
            with np.errstate(invalid="ignore"):
                shape_mean = np.nan_to_num(np.nanmean(arr, axis=0))
                shape_std = np.nan_to_num(
                    np.nanstd(arr, axis=0, ddof=1) if arr.shape[0] > 1 else np.ones(arr.shape[1]),
                    nan=1.0,
                )
        else:
            shape_mean = np.zeros(len(centres))
            shape_std = np.ones(len(centres))

        return cls(part_type, stats, centres, shape_mean.tolist(), shape_std.tolist(), len(valid))

    # -- scoring -------------------------------------------------------
    def compare(self, features: dict) -> dict:
        """Return ``{"z": {key: z}, "octave_rms_z": float|None, "aggregate": float|None}``."""
        z_scores: dict[str, float] = {}
        magnitudes: list[float] = []

        for key, st in self.stats.items():
            value = _scalar(features, key)
            if not isinstance(value, (int, float)):
                continue
            std = st["std"] if st["std"] > 1e-9 else abs(st["mean"]) * 0.05 + 1e-6
            z = (value - st["mean"]) / std
            z_scores[key] = round(float(z), 3)
            magnitudes.append(abs(z))

        octave_rms_z = None
        shape = features.get("octave_band_shape_db")
        if shape and features.get("octave_centres_hz") == self.octave_centres and self.shape_mean:
            sv = np.array([np.nan if v is None else float(v) for v in shape], dtype=float)
            mean = np.array(self.shape_mean, dtype=float)
            std = np.array(self.shape_std, dtype=float)
            std = np.where(std > 1e-6, std, 1.0)
            band_z = (sv - mean) / std
            band_z = band_z[np.isfinite(band_z)]
            if band_z.size:
                octave_rms_z = round(float(np.sqrt(np.mean(band_z**2))), 3)
                magnitudes.append(octave_rms_z)

        aggregate = round(float(np.sqrt(np.mean(np.square(magnitudes)))), 3) if magnitudes else None
        return {"z": z_scores, "octave_rms_z": octave_rms_z, "aggregate": aggregate}

    # -- persistence -------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "part_type": self.part_type,
            "n": self.n,
            "stats": self.stats,
            "octave_centres_hz": self.octave_centres,
            "octave_shape_mean_db": self.shape_mean,
            "octave_shape_std_db": self.shape_std,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReferenceProfile":
        return cls(
            d.get("part_type", ""),
            d["stats"],
            d.get("octave_centres_hz", []),
            d.get("octave_shape_mean_db", []),
            d.get("octave_shape_std_db", []),
            d.get("n", 0),
        )

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path) -> "ReferenceProfile":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
