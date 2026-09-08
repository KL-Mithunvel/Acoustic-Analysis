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
