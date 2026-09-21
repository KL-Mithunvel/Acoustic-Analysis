"""Tests for acoustic_analysis.io.dataset."""

from __future__ import annotations

import csv
import json

import pytest

from acoustic_analysis.io.dataset import Dataset


@pytest.fixture
def db(tmp_path):
    with Dataset(tmp_path / "d.sqlite") as d:
        yield d


def _feat(dom):
    return {
        "status": "OK",
        "valid": True,
        "dominant_freq_hz": dom,
        "t30_s": 0.4,
        "band_ratios": {"high_to_low": 1.5, "high_to_total": 0.4},
    }


def test_session_clip_feature_label_flow(db):
    sid = db.create_session("bench-1", part_type="9x9 tile", material="terracotta")
    c1 = db.add_clip(sid, "clips/1.wav", "recorded", 48000, 0.6)
    c2 = db.add_clip(sid, "clips/2.wav", "imported", 48000, 0.6)
    assert (c1, c2) == (1, 2)

    db.set_features(c1, _feat(1800.0))
    db.set_label(c1, "good", grader="klm", confidence=0.9, in_reference=True)

    got = db.get_clip(c1)
    assert got["seq"] == 1
    assert got["features"]["dominant_freq_hz"] == 1800.0
    assert got["label"]["label"] == "good"
    assert got["label"]["in_reference"] is True

    # auto seq increments per session
    assert db.get_clip(c2)["seq"] == 2


def test_list_and_filter(db):
    sid = db.create_session("s")
    a = db.add_clip(sid, "a.wav", "recorded", 48000)
    b = db.add_clip(sid, "b.wav", "recorded", 48000)
    db.set_label(a, "good")
    db.set_label(b, "cracked")
    assert len(db.list_clips(session_id=sid)) == 2
    assert [c["id"] for c in db.list_clips(label="cracked")] == [b]


def test_reference_clips_needs_flag_and_features(db):
    sid = db.create_session("s")
    a = db.add_clip(sid, "a.wav", "recorded", 48000)
    b = db.add_clip(sid, "b.wav", "recorded", 48000)
    db.set_features(a, _feat(2000.0))
    db.set_label(a, "good", in_reference=True)
    db.set_label(b, "good", in_reference=True)  # no features
    refs = db.reference_clips(session_id=sid)
    assert [c["id"] for c in refs] == [a]


def test_set_label_upsert(db):
    sid = db.create_session("s")
    a = db.add_clip(sid, "a.wav", "recorded", 48000)
    db.set_label(a, "good")
    db.set_label(a, "cracked", grader="klm")
    assert db.get_clip(a)["label"]["label"] == "cracked"
    assert db.get_clip(a)["label"]["grader"] == "klm"


def test_delete_clip_cascades(db):
    sid = db.create_session("s")
    a = db.add_clip(sid, "a.wav", "recorded", 48000)
    db.set_features(a, _feat(1000.0))
    db.set_label(a, "good")
    db.delete_clip(a)
    assert db.get_clip(a) is None


def test_export_csv_and_json(db, tmp_path):
    sid = db.create_session("s")
    a = db.add_clip(sid, "a.wav", "recorded", 48000, 0.6)
    db.set_features(a, _feat(1750.0))
    db.set_label(a, "good", grader="klm", in_reference=True)

    csv_path = db.export_csv(tmp_path / "out.csv")
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows[0]["label"] == "good"
    assert rows[0]["dominant_freq_hz"] == "1750.0"
    assert rows[0]["band_ratios.high_to_low"] == "1.5"

    json_path = db.export_json(tmp_path / "out.json")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload[0]["features"]["dominant_freq_hz"] == 1750.0
    assert payload[0]["label"]["grader"] == "klm"


def test_grade_tier_is_stored_and_exported_alongside_the_defect_label(db, tmp_path):
    sid = db.create_session("s")
    a = db.add_clip(sid, "a.wav", "video", 48000, 0.73, notes="from taps.mp4 [1.000-1.730s]")
    db.set_features(a, _feat(2100.0))
    db.set_label(a, "cracked", grader="slice", grade_tier="3B")

    row = db.get_clip(a)
    assert row["label"]["label"] == "cracked"
    assert row["label"]["grade_tier"] == "3B"

    rows = list(csv.DictReader(db.export_csv(tmp_path / "g.csv").open(encoding="utf-8")))
    assert rows[0]["grade_tier"] == "3B"
    assert rows[0]["label"] == "cracked"

    payload = json.loads(db.export_json(tmp_path / "g.json").read_text(encoding="utf-8"))
    assert payload[0]["notes"].startswith("from taps.mp4")


def test_label_without_a_grade_tier_still_works(db):
    """The Label screen sets only the defect class; that must stay valid."""
    sid = db.create_session("s")
    a = db.add_clip(sid, "a.wav", "recorded", 48000)
    db.set_label(a, "good")
    assert db.get_clip(a)["label"]["grade_tier"] in (None, "")


def test_database_written_by_an_older_build_gains_the_new_column(tmp_path):
    """A pre-grade_tier file must migrate on open, not fail on first insert."""
    import sqlite3

    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE sessions (id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
        " part_type TEXT, material TEXT, notes TEXT, created_at TEXT NOT NULL);"
        "CREATE TABLE clips (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL,"
        " seq INTEGER NOT NULL, path TEXT NOT NULL, source TEXT NOT NULL,"
        " sample_rate INTEGER NOT NULL, duration_s REAL, recorded_at TEXT NOT NULL,"
        " notes TEXT);"
        "CREATE TABLE labels (clip_id INTEGER PRIMARY KEY, label TEXT NOT NULL,"
        " grader TEXT, confidence REAL, in_reference INTEGER NOT NULL DEFAULT 0,"
        " labelled_at TEXT NOT NULL);"
    )
    old.commit()
    old.close()

    with Dataset(path) as db:
        sid = db.create_session("s")
        cid = db.add_clip(sid, "a.wav", "video", 48000)
        db.set_label(cid, "good", grade_tier="4")
        assert db.get_clip(cid)["label"]["grade_tier"] == "4"
