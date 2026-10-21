"""label_store: validation, persistence, crash-safety, CSV export."""

from __future__ import annotations

import csv
import json
from types import SimpleNamespace

import pytest

from acoustic_analysis.io.label_store import LabelError, LabelStore

CLASSES = ["good", "cracked", "corner_broken", "other_defect"]
GRADES = ["3A", "3B", "4", "5"]


def _store(tmp_path):
    return LabelStore(tmp_path / "data" / "labels.json", CLASSES, GRADES, ["retest", "discard"])


def test_set_get_and_persist(tmp_path):
    s = _store(tmp_path)
    s.set("s1/S0001", label="good", tier="3A", note="rings clean")
    s.set("s1/S0002", label="cracked")
    again = _store(tmp_path)                                  # a fresh object reads the same file
    assert again.get("s1/S0001")["label"] == "good" and again.get("s1/S0001")["tier"] == "3A"
    assert again.get("s1/S0001")["note"] == "rings clean"
    assert again.counts() == {"good": 1, "cracked": 1} and len(again) == 2


def test_partial_update_keeps_other_fields(tmp_path):
    s = _store(tmp_path)
    s.set("k", label="good", tier="4", note="x")
    s.set("k", tier="5")
    got = s.get("k")
    assert (got["label"], got["tier"], got["note"]) == ("good", "5", "x")
    s.set("k", tier="")                                       # "" clears just that field
    assert s.get("k")["tier"] is None and s.get("k")["label"] == "good"


def test_clearing_everything_removes_the_entry(tmp_path):
    s = _store(tmp_path)
    s.set("k", label="good")
    s.set("k", label="")
    assert s.get("k") is None and len(_store(tmp_path)) == 0


def test_rejects_unknown_class_or_tier(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(LabelError):
        s.set("k", label="shiny")
    with pytest.raises(LabelError):
        s.set("k", tier="9Z")
    assert s.get("k") is None


def test_extra_labels_are_allowed(tmp_path):
    s = _store(tmp_path)
    s.set("k", label="retest")
    assert s.get("k")["label"] == "retest"


def test_failed_write_keeps_the_old_file(tmp_path, monkeypatch):
    s = _store(tmp_path)
    s.set("k", label="good")
    before = s.path.read_text(encoding="utf-8")
    import acoustic_analysis.io.label_store as mod
    monkeypatch.setattr(mod.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        s.set("k2", label="cracked")
    assert s.path.read_text(encoding="utf-8") == before
    assert not list(s.path.parent.glob("*.tmp"))              # no stray temp file


def test_unreadable_file_is_parked_not_overwritten(tmp_path):
    p = tmp_path / "data" / "labels.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ this is not json")
    with pytest.raises(LabelError):
        LabelStore(p, CLASSES, GRADES)
    assert not p.exists()
    assert list(p.parent.glob("labels.unreadable-*.json"))    # the damaged file is still there to recover


def test_export_csv_only_labelled_rows(tmp_path):
    s = _store(tmp_path)
    r1 = SimpleNamespace(key="a/S1", session="a", id="S1", group="tile", tile_id="T1", tof_mm=88,
                         camera={"grade": "Reject", "crack_severity": "none", "corner_broken": True, "corner_fill_ratio": 0.93})
    r2 = SimpleNamespace(key="a/S2", session="a", id="S2", group="tile", tile_id="T2", tof_mm=None, camera=None)
    s.set("a/S1", label="good", tier="3B", note="n")
    n = s.export_csv(tmp_path / "out" / "labels.csv", [r1, r2], {"a/S1": {"centroid_hz": 900.5, "t20_ms": None}})
    assert n == 1
    rows = list(csv.DictReader(open(tmp_path / "out" / "labels.csv", encoding="utf-8")))
    assert rows[0]["key"] == "a/S1" and rows[0]["label"] == "good" and rows[0]["camera_grade"] == "Reject"
    assert rows[0]["centroid_hz"] == "900.5" and rows[0]["t20_ms"] == ""


def test_saved_file_is_plain_json(tmp_path):
    s = _store(tmp_path)
    s.set("k", label="good")
    data = json.loads(s.path.read_text(encoding="utf-8"))
    assert data["schema"] == 1 and data["labels"]["k"]["label"] == "good"
