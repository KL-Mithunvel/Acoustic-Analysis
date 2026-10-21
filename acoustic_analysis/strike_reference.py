"""Grade a tile's strike by how far it sits from tiles a person labelled GOOD.

No training, nothing hidden: for each chosen feature the reference keeps the median of the good tiles and
a robust spread (1.4826 x MAD). A new strike's distance on each feature is a robust z-score; the
verdict follows the worst one, and the reasons name the features that are off and in which direction.

    GOOD        every feature within ``z_ok`` spreads of the good tiles
    BORDERLINE  worst feature between ``z_ok`` and ``z_bad``
    DEFECTIVE   worst feature beyond ``z_bad``
    RETEST      no strike heard, or too weak to trust
    UNGRADED    no reference yet (fewer than ``min_good`` labelled-good tiles)

It can only recognise "different from the good tiles" - it cannot tell a crack from a chip. Every threshold
is provisional (``config.yaml`` ``strike.reference``); ``evaluate`` measures them against the labels you have.
Pure: dicts in, dicts out (plus JSON save / load).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .strike_features import FEATURE_LABELS

GRADES = ("GOOD", "BORDERLINE", "DEFECTIVE", "RETEST", "UNGRADED", "NO TILE")
_DEFECT_LABELS = ("cracked", "corner_broken", "other_defect")


class ReferenceError(ValueError):
    pass


@dataclass
class StrikeReference:
    features: dict[str, dict]       # key -> {"median", "sigma", "n"}
    n_good: int
    built_at: str

    def to_json(self) -> dict:
        return {"schema": 1, "built_at": self.built_at, "n_good": self.n_good, "features": self.features}

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_json(), fh, indent=1)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @classmethod
    def load(cls, path: str | Path) -> "StrikeReference":
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(features=dict(d["features"]), n_good=int(d["n_good"]), built_at=str(d.get("built_at", "")))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ReferenceError(f"could not read the sound reference {path}: {exc}") from exc


def build_reference(good: list[dict], cfg: dict) -> StrikeReference:
    """From the strike features of tiles labelled GOOD. Raises ``ReferenceError`` if there are too few."""
    c = cfg["strike"]["reference"]
    usable = [f for f in good if f.get("onset_found")]
    if len(usable) < int(c["min_good"]):
        raise ReferenceError(f"{len(usable)} good tiles with a clear strike; at least {c['min_good']} are needed.")
    feats: dict[str, dict] = {}
    for key in c["features"]:
        vals = np.array([f[key] for f in usable if f.get(key) is not None], float)
        if vals.size < int(c["min_good"]):
            continue
        med = float(np.median(vals))
        sigma = max(1.4826 * float(np.median(np.abs(vals - med))), float(c["min_sigma_frac"]) * abs(med), 1e-9)
        feats[key] = {"median": med, "sigma": sigma, "n": int(vals.size)}
    if not feats:
        raise ReferenceError("none of the reference features could be measured on the good tiles.")
    return StrikeReference(feats, len(usable), time.strftime("%Y-%m-%dT%H:%M:%S"))


def _word(key: str, z: float) -> str:
    name = FEATURE_LABELS.get(key, (key, ""))[0].lower()
    return f"{name} is {'higher' if z > 0 else 'lower'} than the good tiles'"


def grade_strike(feat: dict | None, ref: StrikeReference | None, cfg: dict, tile_present: bool | None = None) -> dict:
    """``{"grade", "reasons", "z", "worst"}``. ``tile_present`` False (from the distance sensor) = NO TILE."""
    c = cfg["strike"]["reference"]
    out = {"grade": "UNGRADED", "reasons": [], "z": {}, "worst": None}
    if tile_present is False:
        out.update(grade="NO TILE", reasons=["The distance sensor saw no tile under the striker."])
        return out
    if not feat or not feat.get("onset_found"):
        out.update(grade="RETEST", reasons=["No strike was heard in the recording."])
        return out
    if feat.get("snr_db") is not None and feat["snr_db"] < float(c["min_snr_db"]):
        out.update(grade="RETEST", reasons=[f"The strike is only {feat['snr_db']:.0f} dB over the background "
                                            f"(needs {c['min_snr_db']} dB)."])
        return out
    if ref is None:
        out["reasons"] = ["No sound reference yet: label some tiles good, then build it in the labelling tool."]
        return out
    zs = {}
    for key, r in ref.features.items():
        v = feat.get(key)
        if v is not None:
            zs[key] = (v - r["median"]) / r["sigma"]
    if not zs:
        out.update(grade="RETEST", reasons=["None of the reference features could be measured on this strike."])
        return out
    worst = max(zs, key=lambda k: abs(zs[k]))
    zmax = abs(zs[worst])
    out["z"], out["worst"] = zs, worst
    out["grade"] = "GOOD" if zmax <= float(c["z_ok"]) else ("BORDERLINE" if zmax <= float(c["z_bad"]) else "DEFECTIVE")
    off = sorted((k for k in zs if abs(zs[k]) > float(c["z_ok"])), key=lambda k: -abs(zs[k]))
    out["reasons"] = ([f"{_word(k, zs[k])} ({abs(zs[k]):.1f} spreads away)" for k in off[:3]]
                      or [f"All {len(zs)} measurements are within {c['z_ok']} spreads of the good tiles."])
    return out


def evaluate(items: list[tuple[str, dict, str]], cfg: dict) -> dict:
    """How the reference does on labelled data. ``items`` = (key, features, label).

    Good tiles are graded leave-one-out (never against a reference that contains themselves);
    defect-labelled tiles against the reference of all the good ones. Honest, not flattering: with few
    labels the numbers are rough, so the counts are returned alongside the rates.
    """
    good = [(k, f) for k, f, lab in items if lab == "good" and f.get("onset_found")]
    bad = [(k, f, lab) for k, f, lab in items if lab in _DEFECT_LABELS and f.get("onset_found")]
    res = {"n_good": len(good), "n_defect": len(bad), "good_accepted": 0, "good_borderline": 0, "good_rejected": 0,
           "defect_caught": 0, "defect_flagged": 0, "missed": [], "false_alarms": [], "possible": True}
    try:
        full = build_reference([f for _, f in good], cfg)
    except ReferenceError as exc:
        return {**res, "possible": False, "why": str(exc)}
    for i, (key, f) in enumerate(good):
        try:
            loo = build_reference([g for j, (_, g) in enumerate(good) if j != i], cfg)
        except ReferenceError:
            loo = full                               # too few to leave one out: fall back (flagged by n_good)
        grade = grade_strike(f, loo, cfg)["grade"]
        if grade == "GOOD":
            res["good_accepted"] += 1
        elif grade == "BORDERLINE":
            res["good_borderline"] += 1
            res["false_alarms"].append(key)
        elif grade == "DEFECTIVE":
            res["good_rejected"] += 1
            res["false_alarms"].append(key)
    for key, f, _lab in bad:
        grade = grade_strike(f, full, cfg)["grade"]
        if grade == "DEFECTIVE":
            res["defect_caught"] += 1
            res["defect_flagged"] += 1
        elif grade == "BORDERLINE":
            res["defect_flagged"] += 1
        else:
            res["missed"].append(key)
    return res


def describe_evaluation(ref: StrikeReference, ev: dict) -> str:
    """Plain-language summary of ``evaluate`` for a message box."""
    lines = [f"Sound reference built from {ref.n_good} tiles you labelled good."]
    if not ev.get("possible", True):
        return "\n".join(lines + ["Could not check it against your labels: " + ev.get("why", "")])
    lines.append("")
    lines.append("How it does on your own labels (rough - these are small numbers):")
    lines.append(f"  Good tiles accepted:  {ev['good_accepted']} of {ev['n_good']}"
                 f"  ({ev['good_borderline']} borderline, {ev['good_rejected']} rejected)   [each checked without itself]")
    if ev["n_defect"]:
        lines.append(f"  Defective tiles caught: {ev['defect_caught']} of {ev['n_defect']}"
                     f"  ({ev['defect_flagged']} flagged as borderline or worse)")
        if ev["missed"]:
            lines.append(f"  Sounded like a good tile: {', '.join(ev['missed'][:6])}")
    else:
        lines.append("  No defective tiles labelled yet, so how well it catches them is not known.")
    lines += ["", "It can only tell a tile that sounds DIFFERENT from your good ones - not a crack from a chip."]
    return "\n".join(lines)
