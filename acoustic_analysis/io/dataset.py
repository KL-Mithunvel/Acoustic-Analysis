"""SQLite store for sessions, clips, features and labels.

One database file (path from ``config.yaml`` ``paths.database``). Feature dicts
are kept whole as a JSON blob; ``export_csv`` flattens a curated set of scalars
for model training, ``export_json`` writes everything.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    part_type  TEXT,
    material   TEXT,
    notes      TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    path        TEXT NOT NULL,
    source      TEXT NOT NULL,
    sample_rate INTEGER NOT NULL,
    duration_s  REAL,
    recorded_at TEXT NOT NULL,
    notes       TEXT
);
CREATE TABLE IF NOT EXISTS features (
    clip_id      INTEGER PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
    json         TEXT NOT NULL,
    extracted_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (
    clip_id      INTEGER PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
    label        TEXT NOT NULL,
    grade_tier   TEXT,
    grader       TEXT,
    confidence   REAL,
    in_reference INTEGER NOT NULL DEFAULT 0,
    labelled_at  TEXT NOT NULL
);
"""

# Columns added after the first release, as (table, column, definition). Applied
# by _migrate() on open: CREATE TABLE IF NOT EXISTS leaves an existing table
# alone, so a database written by an older build would otherwise never gain
# them and every insert naming one would fail.
_MIGRATIONS = [
    # grade_tier: the tile's cosmetic grade (3A/3B/4/5), kept separate from
    # `label` (the defect class) by the owner's decision - see segments.py.
    ("labels", "grade_tier", "TEXT"),
]

# Curated scalar features for CSV export (nested keys use dotted paths).
_CSV_FEATURE_KEYS = [
    "dominant_freq_hz", "spectral_centroid_hz", "spectral_bandwidth_hz",
    "spectral_rolloff_hz", "spectral_flatness", "t20_s", "t30_s",
    "decay_rate_db_s", "fastest_band_decay_db_s", "snr_db", "leq_z_db",
    "crest_factor", "band_ratios.high_to_low", "band_ratios.high_to_total",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dig(d: dict, dotted: str):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class Dataset:
    """Handle to the clip database. Use as a context manager or call ``close()``."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._migrate()
        self._db.commit()

    def _migrate(self) -> None:
        """Add any columns introduced after this database file was created."""
        for table, column, decl in _MIGRATIONS:
            existing = {
                r["name"] for r in self._db.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in existing:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    # -- lifecycle -----------------------------------------------------------
    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "Dataset":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- sessions ----------------------------------------------------------
    def create_session(self, name: str, part_type: str = "", material: str = "", notes: str = "") -> int:
        cur = self._db.execute(
            "INSERT INTO sessions (name, part_type, material, notes, created_at) VALUES (?,?,?,?,?)",
            (name, part_type, material, notes, _now()),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def list_sessions(self) -> list[dict]:
        rows = self._db.execute("SELECT * FROM sessions ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # -- clips -----------------------------------------------------------
    def add_clip(
        self,
        session_id: int,
        path: str,
        source: str,
        sample_rate: int,
        duration_s: float | None = None,
        seq: int | None = None,
        notes: str = "",
    ) -> int:
        if seq is None:
            row = self._db.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM clips WHERE session_id = ?", (session_id,)
            ).fetchone()
            seq = int(row["n"])
        cur = self._db.execute(
            "INSERT INTO clips (session_id, seq, path, source, sample_rate, duration_s, recorded_at, notes)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (session_id, seq, str(path), source, int(sample_rate), duration_s, _now(), notes),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def set_features(self, clip_id: int, features: dict) -> None:
        self._db.execute(
            "INSERT INTO features (clip_id, json, extracted_at) VALUES (?,?,?)"
            " ON CONFLICT(clip_id) DO UPDATE SET json = excluded.json, extracted_at = excluded.extracted_at",
            (clip_id, json.dumps(features), _now()),
        )
        self._db.commit()

    def set_label(
        self,
        clip_id: int,
        label: str,
        grader: str = "",
        confidence: float | None = None,
        in_reference: bool = False,
        grade_tier: str = "",
    ) -> None:
        """Label a clip. ``label`` is the defect class, ``grade_tier`` the
        cosmetic grade - two independent axes, see segments.py."""
        self._db.execute(
            "INSERT INTO labels (clip_id, label, grade_tier, grader, confidence,"
            " in_reference, labelled_at) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(clip_id) DO UPDATE SET label=excluded.label,"
            " grade_tier=excluded.grade_tier, grader=excluded.grader,"
            " confidence=excluded.confidence, in_reference=excluded.in_reference,"
            " labelled_at=excluded.labelled_at",
            (clip_id, label, grade_tier, grader, confidence, int(bool(in_reference)), _now()),
        )
        self._db.commit()

    def delete_clip(self, clip_id: int) -> None:
        self._db.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        self._db.commit()

    def get_clip(self, clip_id: int) -> dict | None:
        row = self._db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if row is None:
            return None
        return self._assemble(row)

    def list_clips(self, session_id: int | None = None, label: str | None = None) -> list[dict]:
        sql = "SELECT c.* FROM clips c LEFT JOIN labels l ON l.clip_id = c.id"
        conds, args = [], []
        if session_id is not None:
            conds.append("c.session_id = ?")
            args.append(session_id)
        if label is not None:
            conds.append("l.label = ?")
            args.append(label)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY c.session_id, c.seq"
        return [self._assemble(r) for r in self._db.execute(sql, args).fetchall()]

    def reference_clips(self, session_id: int | None = None) -> list[dict]:
        return [
            c
            for c in self.list_clips(session_id=session_id)
            if c.get("label", {}).get("in_reference") and c.get("features")
        ]

    def _assemble(self, clip_row: sqlite3.Row) -> dict:
        out = dict(clip_row)
        frow = self._db.execute(
            "SELECT json FROM features WHERE clip_id = ?", (out["id"],)
        ).fetchone()
        out["features"] = json.loads(frow["json"]) if frow else None
        lrow = self._db.execute(
            "SELECT label, grade_tier, grader, confidence, in_reference, labelled_at"
            " FROM labels WHERE clip_id = ?",
            (out["id"],),
        ).fetchone()
        if lrow:
            ld = dict(lrow)
            ld["in_reference"] = bool(ld["in_reference"])
            out["label"] = ld
        else:
            out["label"] = {}
        return out

    # -- export ----------------------------------------------------------
    def export_csv(self, path, session_id: int | None = None) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "clip_id", "session_id", "seq", "source", "sample_rate", "duration_s",
            "label", "grade_tier", "grader", "in_reference", "status", *(_CSV_FEATURE_KEYS),
        ]
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(header)
            for clip in self.list_clips(session_id=session_id):
                feats = clip.get("features") or {}
                lab = clip.get("label") or {}
                writer.writerow(
                    [
                        clip["id"], clip["session_id"], clip["seq"], clip["source"],
                        clip["sample_rate"], clip["duration_s"],
                        lab.get("label", ""), lab.get("grade_tier") or "",
                        lab.get("grader", ""),
                        int(bool(lab.get("in_reference"))), feats.get("status", ""),
                        *[_dig(feats, k) for k in _CSV_FEATURE_KEYS],
                    ]
                )
        return path

    def export_json(self, path, session_id: int | None = None) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "clip_id": c["id"],
                "session_id": c["session_id"],
                "seq": c["seq"],
                "source": c["source"],
                "sample_rate": c["sample_rate"],
                # Provenance: for a snippet cut out of a video this records the
                # file and the time range it came from, so a suspect row can be
                # traced back to the footage and re-listened to.
                "notes": c.get("notes") or "",
                "label": c.get("label", {}),
                "features": c.get("features"),
            }
            for c in self.list_clips(session_id=session_id)
        ]
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path
