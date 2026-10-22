"""Human labels for station strikes, kept in one JSON file next to this app's data.

Two independent axes, as everywhere else in this app (``config.yaml`` ``labels``): the defect
class and the cosmetic grade tier, plus a free note. A label is keyed by
``StrikeRecord.key`` (``<session>/<strike id>``) and lives here, *not* in the session folder,
because the station seals every session with a SHA-256 manifest.

Writes are atomic (temp file + ``os.replace``): a crash mid-save leaves the previous file intact.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import time
from pathlib import Path


class LabelError(ValueError):
    """An unknown class or tier, or an unreadable store file."""


class LabelStore:
    def __init__(self, path: str | Path, classes: list[str], grades: list[str], extra: list[str] | None = None):
        self.path = Path(path)
        self.classes = list(classes)
        self.extra = list(extra or [])
        self.grades = list(grades)
        self._labels: dict[str, dict] = {}
        self._load()

    @classmethod
    def from_config(cls, cfg: dict, path: str | Path) -> "LabelStore":
        lab = cfg["labels"]
        return cls(path, lab["classes"], lab["grades"], lab.get("extra"))

    # -- reading ------------------------------------------------------------
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            labels = data["labels"]
            if not isinstance(labels, dict):
                raise TypeError
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Never overwrite a file we could not read: park it and start clean, loudly.
            bad = self.path.with_suffix(f".unreadable-{int(time.time())}.json")
            try:
                os.replace(self.path, bad)
            except OSError:
                pass
            raise LabelError(f"{self.path} could not be read ({exc}); moved to {bad.name}") from exc
        self._labels = labels

    def get(self, key: str) -> dict | None:
        return self._labels.get(key)

    def all(self) -> dict[str, dict]:
        return dict(self._labels)

    def __len__(self) -> int:
        return len(self._labels)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self._labels.values():
            name = v.get("label") or "(tier only)"
            out[name] = out.get(name, 0) + 1
        return out

    # -- writing ------------------------------------------------------------
    def set(self, key: str, label: str | None = None, tier: str | None = None, note: str | None = None) -> dict:
        """Set any of the three; ``None`` keeps what is there. ``""`` clears that field."""
        if label and label not in self.classes + self.extra:
            raise LabelError(f"unknown label {label!r}; allowed {self.classes + self.extra}")
        if tier and tier not in self.grades:
            raise LabelError(f"unknown tier {tier!r}; allowed {self.grades}")
        cur = dict(self._labels.get(key) or {"label": None, "tier": None, "note": ""})
        if label is not None:
            cur["label"] = label or None
        if tier is not None:
            cur["tier"] = tier or None
        if note is not None:
            cur["note"] = note
        cur["at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not cur["label"] and not cur["tier"] and not cur.get("note"):
            self._labels.pop(key, None)
            self._save()
            return {}
        self._labels[key] = cur
        self._save()
        return cur

    def clear(self, key: str) -> None:
        if self._labels.pop(key, None) is not None:
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": 1, "classes": self.classes, "grades": self.grades, "labels": self._labels}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=1, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # -- export ---------------------------------------------------------------
    def export_csv(self, path: str | Path, records: list, features: dict[str, dict] | None = None) -> int:
        """One row per *labelled* record: its identity, the human label, the camera's reading
        and (if given) the strike features. Returns the number of rows written."""
        features = features or {}
        feat_keys = sorted({k for f in features.values() for k in f if k not in ("onset_found",)})
        head = ["key", "session", "id", "group", "tile_id", "label", "tier", "note", "labelled_at",
                "camera_grade", "crack", "corner_broken", "corner_fill", "tof_mm"] + feat_keys
        rows = 0
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(head)
            for r in records:
                lab = self._labels.get(r.key)
                if not lab:
                    continue
                cam = r.camera or {}
                f = features.get(r.key, {})
                w.writerow([r.key, r.session, r.id, r.group, r.tile_id or "", lab.get("label") or "",
                            lab.get("tier") or "", lab.get("note") or "", lab.get("at") or "",
                            cam.get("grade", ""), cam.get("crack_severity", ""), cam.get("corner_broken", ""),
                            cam.get("corner_fill_ratio", ""), r.tof_mm if r.tof_mm is not None else ""]
                           + [("" if f.get(k) is None else f.get(k)) for k in feat_keys])
                rows += 1
        return rows
