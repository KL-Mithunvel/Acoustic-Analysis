"""session_reader: a hand-built mini session, plus the real 2026-10-19 sessions when present."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from acoustic_analysis.io.session_reader import list_sessions, load_all, load_session
from acoustic_analysis.config import repo_root


def _wav(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.zeros(480, dtype="float32"), 48000)


def _session(root: Path, name="2026-10-19_10-00-00") -> Path:
    s = root / name
    labels = {"condition": "tile", "defect": None, "tier": None, "tile_ref": None, "note": None}
    events = [
        {"id": "R0001", "kind": "retract", "source": "tof", "t": 1.0, "cycle": "S0001", "tile_id": "T1", "labels": labels},
        {"id": "S0001", "kind": "strike", "source": "tof", "t": 2.0, "nano_ms": 5, "tile_present": True, "tof_mm": 88,
         "cycle": "R0001", "tile_id": "T1", "retract_to_strike_ms": 1000, "labels": labels},
        {"id": "S0002", "kind": "strike", "source": "rest", "t": 3.0, "tile_present": False, "tile_id": "T2", "labels": labels},
        {"id": "S0003", "kind": "strike", "source": "manual", "t": 4.0, "tile_present": False,
         "labels": {**labels, "condition": "no_tile"}},
        {"id": "A0001", "kind": "ambient", "source": "operator", "t": 5.0, "labels": {**labels, "condition": "ambient"}},
    ]
    (s / "clips").mkdir(parents=True)
    (s / "strikes.json").write_text(json.dumps(events))
    (s / "manifest.json").write_text(json.dumps({"run_type": "tile", "note": "a note"}))
    for n in ("R0001_retract", "S0001_strike", "S0002_strike", "S0003_strike", "A0001_ambient"):
        _wav(s / "clips" / f"{n}.wav")
    (s / "tiles").mkdir()
    (s / "tiles" / "T1.jpg").write_bytes(b"\xff\xd8fake")
    msgs = [
        {"topic": "tile/T1/camera/result", "payload": {"tile_id": "T1", "grade": "Reject", "corner_fill_ratio": 0.9}},
        {"topic": "tile/T1/camera/result", "payload": {"tile_id": "T1", "grade": "Grade A", "corner_fill_ratio": 0.97}},
        {"topic": "tile/T1/acoustic/result", "payload": {"peak_frequency_hz": 200.1}},
        {"topic": "tile/T1/final", "payload": {"final_grade": "Grade A"}},
        {"topic": "station/tap", "payload": {}},
    ]
    (s / "events.jsonl").write_text("\n".join(json.dumps(m) for m in msgs) + "\nnot json at all\n")
    return s


def test_records_groups_and_links(tmp_path):
    recs = {r.id: r for r in load_session(_session(tmp_path))}
    assert set(recs) == {"S0001", "S0002", "S0003", "A0001"}          # retraction is not its own record
    assert [recs[i].group for i in ("S0001", "S0002", "S0003", "A0001")] == ["tile", "rest", "no_tile", "ambient"]
    s1 = recs["S0001"]
    assert s1.key == "2026-10-19_10-00-00/S0001"
    assert s1.clip_path.name == "S0001_strike.wav" and s1.retract_clip_path.name == "R0001_retract.wav"
    assert s1.picture_path.name == "T1.jpg"
    assert s1.camera["grade"] == "Grade A"                             # the last camera message wins
    assert s1.acoustic["peak_frequency_hz"] == 200.1 and s1.final["final_grade"] == "Grade A"
    assert s1.tof_mm == 88 and s1.run_type == "tile" and s1.session_note == "a note"
    assert recs["S0002"].picture_path is None and recs["S0002"].camera is None


def test_damaged_or_missing_files_do_not_raise(tmp_path):
    s = _session(tmp_path)
    (s / "clips" / "S0001_strike.wav").unlink()
    (s / "events.jsonl").unlink()
    rec = next(r for r in load_session(s) if r.id == "S0001")
    assert rec.clip_path is None and rec.camera is None
    (s / "strikes.json").write_text("{broken")
    assert load_session(s) == []
    assert load_session(tmp_path / "nope") == []


def test_list_sessions_ignores_other_folders(tmp_path):
    _session(tmp_path, "2026-10-19_10-00-00")
    _session(tmp_path, "2026-10-19_11-00-00")
    (tmp_path / "other").mkdir()
    assert [p.name for p in list_sessions(tmp_path)] == ["2026-10-19_10-00-00", "2026-10-19_11-00-00"]
    assert len(load_all(tmp_path)) == 8


def test_reading_never_changes_the_session(tmp_path):
    s = _session(tmp_path)

    def digest():
        return {str(p.relative_to(s)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(s.rglob("*")) if p.is_file()}

    before = digest()
    load_all(tmp_path)
    assert digest() == before


REAL = (repo_root().parent / "data" / "master" / "sessions")


@pytest.mark.skipif(not REAL.is_dir(), reason="real station sessions not on this machine")
def test_real_sessions_load():
    recs = load_all(REAL)
    assert len(recs) >= 50
    by = {g: sum(r.group == g for r in recs) for g in ("tile", "no_tile", "rest", "ambient")}
    assert by["no_tile"] >= 25 and by["tile"] >= 20
    tiles = [r for r in recs if r.group == "tile"]
    assert all(r.clip_path for r in tiles) and any(r.camera for r in tiles) and any(r.picture_path for r in tiles)
