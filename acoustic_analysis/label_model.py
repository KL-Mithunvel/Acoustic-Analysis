"""The labelling tool's brain, with no GUI in it.

Holds the strike records of one or more station sessions, computes each clip's strike features,
keeps the per-group medians the analysis is compared against, filters the list, and turns one
record into the plain-language "everything we know about this tile" sections the window shows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from .io.label_store import LabelStore
from .io.session_reader import GROUP_TEXT, StrikeRecord
from .strike_features import (FEATURE_KEYS, FEATURE_LABELS, find_onset, flags as _flags, percentile_of, ring_envelope_db,
                              ring_spectrum, strike_features)

NO_CAMERA = "no camera result"


@dataclass
class Section:
    title: str
    rows: list[tuple[str, str]]


def load_wav(path: str | Path) -> tuple[np.ndarray, int]:
    """Mono float clip and its sample rate."""
    x, fs = sf.read(str(path), dtype="float64", always_2d=False)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x, int(fs)


def fmt_feature(key: str, value) -> str:
    if value is None:
        return "-"
    unit = FEATURE_LABELS.get(key, ("", ""))[1]
    if key in ("f_low", "f_mid", "f_high", "f_top"):
        return f"{100 * value:.0f} %"
    if key == "peak":
        return f"{value:.2f}"
    text = f"{value:.2f}" if abs(value) < 10 else f"{value:.0f}"
    return f"{text} {unit}".strip()


def _yes(v) -> str:
    return "-" if v is None else ("yes" if v else "no")


class ReviewData:
    def __init__(self, records: list[StrikeRecord], cfg: dict, labels: LabelStore | None = None):
        self.records = list(records)
        self.cfg = cfg
        self.labels = labels
        self.features: dict[str, dict] = {}
        self.medians: dict[str, dict[str, float]] = {}
        self.curves: dict[str, dict] = {}            # per clip: "spec" (freq, share) and "env" (ms, dB)
        self.reference: dict[str, dict] = {}         # per group: median / quartile curves to compare against

    # -- analysis -------------------------------------------------------------
    def compute_features(self, progress: Callable[[int, int], None] | None = None) -> None:
        todo = [r for r in self.records if r.clip_path is not None]
        for i, r in enumerate(todo):
            try:
                x, fs = load_wav(r.clip_path)
                self.features[r.key] = strike_features(x, fs, self.cfg)
                self.curves[r.key] = {"spec": ring_spectrum(x, fs, self.cfg), "env": ring_envelope_db(x, fs, self.cfg)}
            except Exception:  # noqa: BLE001 - an unreadable clip must not stop the rest
                self.features[r.key] = {"onset_found": False, **{k: None for k in FEATURE_KEYS}, "error": True}
            if progress:
                progress(i + 1, len(todo))
        self._build_medians()

    def _stack(self, recs: list[StrikeRecord], kind: str):
        """Curves of one kind for these records, as one array - only those that share their x axis."""
        pairs = [self.curves[r.key][kind] for r in recs if self.curves.get(r.key, {}).get(kind) is not None]
        if not pairs:
            return None
        n = min(len(p[0]) for p in pairs)
        x = pairs[0][0][:n]
        ys = np.array([p[1][:n] for p in pairs if len(p[0]) >= n and np.allclose(p[0][:n], x)])
        return (x, ys) if len(ys) else None

    def _build_reference(self) -> None:
        self.reference = {}
        for g in {r.group for r in self.records}:
            recs = [r for r in self.records if r.group == g]
            ref = {}
            spec, env = self._stack(recs, "spec"), self._stack(recs, "env")
            if spec:
                f, p = spec
                ref["spec"] = (f, np.median(p, 0), np.percentile(p, 25, 0), np.percentile(p, 75, 0))
            if env:
                t, d = env
                ref["env"] = (t, np.median(d, 0), np.percentile(d, 25, 0), np.percentile(d, 75, 0))
            if ref:
                self.reference[g] = ref

    def waveform(self, rec: StrikeRecord, pre_ms: float = 60.0, post_ms: float = 320.0):
        """``(t_ms, samples, onset_ms)`` around the strike, t=0 at the onset; ``None`` without a clip/strike."""
        if rec.clip_path is None:
            return None
        x, fs = load_wav(rec.clip_path)
        x = x - np.median(x)
        onset, _ = find_onset(x, fs, self.cfg)
        if onset is None:
            onset = int(float(self.cfg["strike"]["expect_s"]) * fs)       # show where it was expected
        a, b = max(onset - int(pre_ms * fs / 1000), 0), min(onset + int(post_ms * fs / 1000), x.size)
        return (np.arange(a, b) - onset) / fs * 1000.0, x[a:b], 0.0

    def _build_medians(self) -> None:
        self._build_reference()
        self.medians = {}
        for g in {r.group for r in self.records}:
            feats = [self.features[r.key] for r in self.records
                     if r.group == g and r.key in self.features and self.features[r.key].get("onset_found")]
            if feats:
                self.medians[g] = {k: float(np.median([f[k] for f in feats if f[k] is not None]))
                                   for k in FEATURE_KEYS if any(f[k] is not None for f in feats)}

    def feature_of(self, rec: StrikeRecord) -> dict | None:
        return self.features.get(rec.key)

    def percentile(self, rec: StrikeRecord, feat: str) -> float | None:
        """Where this strike sits among the strikes of its own group (0 = lowest, 100 = highest)."""
        mine = (self.features.get(rec.key) or {}).get(feat)
        pop = [self.features[r.key].get(feat) for r in self.records
               if r.group == rec.group and r.key in self.features and self.features[r.key].get("onset_found")]
        return percentile_of(mine, pop)

    def flags(self, rec: StrikeRecord) -> list[str]:
        f = self.features.get(rec.key)
        if f is None:
            return ["No audio clip was found for this strike."]
        notes = _flags(f, self.medians.get("tile"), self.medians.get("no_tile"))
        # Strikes near the start of a session group sit apart from the rest on the 2026-10-19 data.
        return notes

    # -- filtering --------------------------------------------------------------
    def camera_grades(self) -> list[str]:
        grades = sorted({(r.camera or {}).get("grade") for r in self.records if r.camera} - {None})
        return grades + [NO_CAMERA]

    def filter(self, group: str = "all", camera: str = "all", status: str = "all",
               session: str = "all") -> list[StrikeRecord]:
        out = []
        for r in self.records:
            if group != "all" and r.group != group:
                continue
            if session != "all" and r.session != session:
                continue
            if camera != "all":
                grade = (r.camera or {}).get("grade")
                if camera == NO_CAMERA and r.camera:
                    continue
                if camera != NO_CAMERA and grade != camera:
                    continue
            if status != "all" and self.labels is not None:
                labelled = self.labels.get(r.key) is not None
                if (status == "labelled") != labelled:
                    continue
            out.append(r)
        return out

    def progress(self) -> tuple[int, int]:
        """(labelled, total) over the records that have a clip."""
        recs = [r for r in self.records if r.clip_path is not None]
        done = sum(1 for r in recs if self.labels is not None and self.labels.get(r.key) is not None)
        return done, len(recs)

    # -- everything we know about one strike ------------------------------------
    def sections(self, rec: StrikeRecord) -> list[Section]:
        out: list[Section] = []
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec.t)) if rec.t else "-"
        out.append(Section("This recording", [
            ("Strike", f"{rec.id}  ({GROUP_TEXT.get(rec.group, rec.group)})"),
            ("Session", rec.session),
            ("Session type", rec.run_type or "-"),
            ("Session note", rec.session_note or "-"),
            ("Time", when),
            ("Tile id", rec.tile_id or "-"),
        ]))
        out.append(Section("Striker and distance sensor", [
            ("Triggered by", rec.source or "-"),
            ("Tile detected under striker", _yes(rec.tile_present)),
            ("Distance (ToF)", f"{rec.tof_mm} mm" if rec.tof_mm is not None else "-"),
            ("Raise to strike", f"{rec.retract_to_strike_ms / 1000:.1f} s" if rec.retract_to_strike_ms else "-"),
            ("Raising noise clip", "recorded" if rec.retract_clip_path else "-"),
        ]))
        cam = rec.camera
        if cam:
            model = ("not used (model off)" if not cam.get("model_used") and not cam.get("model_grade")
                     else f"{cam.get('model_grade')}  (counted: {_yes(cam.get('model_used'))})")
            out.append(Section("Camera (vision) result", [
                ("Camera grade", str(cam.get("grade", "-"))),
                ("Rule grade", str(cam.get("rule_grade", "-"))),
                ("Vision-model grade", model),
                ("Crack", f"{cam.get('crack_severity', '-')}  ({cam.get('crack_length_px', 0):.0f} px)"
                          if cam.get("crack_detected") else "none found"),
                ("Corner broken", _yes(cam.get("corner_broken"))),
                ("Corner fill ratio", f"{cam['corner_fill_ratio']:.3f}  (1.0 = perfect square)"
                                      if cam.get("corner_fill_ratio") is not None else "-"),
            ]))
        else:
            out.append(Section("Camera (vision) result", [("Camera", NO_CAMERA)]))
        fin = rec.final
        if fin:
            out.append(Section("Station decision", [
                ("Final grade", str(fin.get("final_grade", "-"))),
                ("Goes to", str(fin.get("destination", "-"))),
                ("Sound counted", _yes(fin.get("acoustic_counted"))),
                ("Why", "; ".join(fin.get("reasons") or []) or "-"),
            ]))
        ac = rec.acoustic
        if ac:
            out.append(Section("Station's own sound reading", [
                ("Strongest frequency", f"{ac['peak_frequency_hz']:.0f} Hz" if ac.get("peak_frequency_hz") else "-"),
                ("Decay T20", f"{ac['decay_t20_s'] * 1000:.0f} ms" if ac.get("decay_t20_s") else "-"),
                ("Sound grade", str(ac.get("acoustic_grade") or "none (no reference profile yet)")),
            ]))
        feat = self.features.get(rec.key)
        if feat and feat.get("onset_found"):
            med = self.medians.get(rec.group, {})
            rows = []
            for k in FEATURE_KEYS:
                p = self.percentile(rec, k)
                rows.append((FEATURE_LABELS[k][0],
                             f"{fmt_feature(k, feat[k])}   (typical {fmt_feature(k, med.get(k))}"
                             + (f", {p:.0f}th pct)" if p is not None else ")")))
            out.insert(1, Section("Sound analysis (this app)", rows))       # the analysis comes first
        elif feat is not None:
            out.insert(1, Section("Sound analysis (this app)", [("Result", "no strike found in the clip")]))
        return out
