"""The labelling window, driven programmatically on a hand-built session (no real data, no dialogs)."""

from __future__ import annotations

import time

import pytest

from tests.conftest import has_display
from tests.test_session_reader import _session

pytestmark = pytest.mark.skipif(not has_display(), reason="no display for Tk")


def _wait_ready(win, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        win.update()
        if win.status.get().startswith("Ready"):
            return
        time.sleep(0.03)
    raise AssertionError(f"analysis never finished: {win.status.get()!r}")


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    # One window for the file (several Tk roots in one process is flaky - see conftest).
    from PIL import Image

    from acoustic_analysis.app.label_tool import LabelWindow
    from acoustic_analysis.config import load_config

    root = tmp_path_factory.mktemp("sessions")
    s = _session(root)
    Image.new("RGB", (640, 480), (190, 120, 80)).save(s / "tiles" / "T1.jpg")   # a real, if plain, picture
    cfg = load_config()
    lab = tmp_path_factory.mktemp("lab")
    cfg["paths"] = {**cfg["paths"], "strike_reference": str(lab / "strike_reference.json")}      # never touch the real data/
    w = LabelWindow(cfg, sessions_dir=root, labels_path=lab / "labels.json")
    w.dialog = lambda title, text: w.shown.append((title, text))
    w.shown = []
    _wait_ready(w)
    try:
        yield w
    finally:
        w.destroy()


def _select(win, key):
    win.tree.selection_set(key)
    win.update()


def test_lists_every_strike_and_counts_labels(win):
    assert len(win.tree.get_children()) == 4
    assert win.progress_var.get() == "0 of 4 labelled"


def test_filters_narrow_the_list(win):
    win.f_group.var.set("no_tile")
    win.refresh_list()
    assert len(win.tree.get_children()) == 1
    win.f_group.var.set("all")
    win.f_camera.var.set("Grade A")
    win.refresh_list()
    assert [win.tree.item(i, "values")[1] for i in win.tree.get_children()] == ["Grade A"]
    win.f_camera.var.set("all")
    win.refresh_list()
    assert len(win.tree.get_children()) == 4


def test_selecting_a_tile_shows_picture_and_everything_known(win):
    key = next(r.key for r in win.data.records if r.id == "S0001")
    _select(win, key)
    assert win._photo is not None                                    # the tile picture loaded
    text = win.info.get("1.0", "end")
    for needle in ("Camera (vision) result", "Camera grade: Grade A", "Vision-model grade: not used",
                   "Distance (ToF): 88 mm", "Station decision", "Station's own sound reading", "a note"):
        assert needle in text, needle


def test_striker_alone_has_no_picture_and_says_why(win):
    key = next(r.key for r in win.data.records if r.id == "S0003")
    _select(win, key)
    assert win._photo is None
    assert "no tile to photograph" in win.pic.cget("text")
    assert "no camera result" in win.info.get("1.0", "end")


def _rec(win, rid):
    return next(r for r in win.data.records if r.id == rid)


def test_plot_draws_three_panels_for_the_selection(win):
    _select(win, _rec(win, "S0001").key)
    assert len(win.plot.figure.axes) == 3
    assert [a.get_title() for a in win.plot.figure.axes] == ["What it sounds like", "Which pitches ring", "How fast it fades"]


def test_labelling_saves_and_moves_to_the_next_unlabelled(win):
    first = _rec(win, "S0001")
    _select(win, first.key)
    win.set_label("good")
    win.update()
    assert win.labels.get(first.key)["label"] == "good"
    assert win._rec.id == "S0002"                                    # on to the next strike still to do
    assert win.progress_var.get() == "1 of 4 labelled"
    assert win.tree.item(first.key, "values")[2] == "good"
    _select(win, first.key)
    assert win.cur_label_var.get().startswith("Your label:  good")


def test_tier_note_and_keyboard(win):
    rec = _rec(win, "S0002")
    _select(win, rec.key)
    win.set_tier("3B")
    win.note_var.set("hairline near the edge")
    win.save_note()
    got = win.labels.get(rec.key)
    assert got["tier"] == "3B" and got["note"] == "hairline near the edge" and got["label"] is None

    class Ev:                                                        # a key press for "c" = cracked
        char = "c"
    win.focus_set()
    win._on_key(Ev())
    win.update()
    assert win.labels.get(rec.key)["label"] == "cracked"
    assert win.labels.get(rec.key)["tier"] == "3B"                   # setting the class kept the tier and note


def test_clear_and_unlabelled_filter(win):
    rec = _rec(win, "S0002")
    _select(win, rec.key)
    win.clear_label()
    win.update()
    assert win.labels.get(rec.key) is None
    win.f_status.var.set("unlabelled")
    win.refresh_list()
    assert rec.key in win.tree.get_children() and _rec(win, "S0001").key not in win.tree.get_children()
    win.f_status.var.set("all")
    win.refresh_list()


def test_export_writes_only_labelled(win, tmp_path):
    n = win.labels.export_csv(tmp_path / "out.csv", win.data.records, win.data.features)
    import csv

    rows = list(csv.DictReader(open(tmp_path / "out.csv", encoding="utf-8")))
    assert n == len(rows) == 1 and rows[0]["id"] == "S0001" and rows[0]["label"] == "good"


def test_shortcut_keys_are_the_obvious_letters(win):
    assert win._label_keys == {"g": "good", "c": "cracked", "b": "corner_broken", "o": "other_defect",
                               "r": "retest", "d": "discard"}
    assert win._tier_keys == {"1": "3A", "2": "3B", "3": "4", "4": "5"}


def _synthetic_session(root, n_good=10, n_bad=2):
    """A session whose good tiles ring at 2 kHz (fast fade) and whose defects ring at 5 kHz (slow fade)."""
    import json

    import numpy as np
    import soundfile as sf

    fs = 48000
    s = root / "2026-10-20_09-00-00"
    (s / "clips").mkdir(parents=True)
    events = []
    rng = np.random.default_rng(11)
    for i in range(n_good + n_bad):
        good = i < n_good
        t = np.arange(int(1.5 * fs)) / fs
        x = rng.normal(0, 1e-3, t.size)
        m = t >= 0.5
        f0 = (2000 + rng.normal(0, 30)) if good else 5000
        x[m] += 0.6 * np.sin(2 * np.pi * f0 * (t[m] - 0.5)) * np.exp(-(t[m] - 0.5) / (0.02 if good else 0.08))
        sid = f"S{i + 1:04d}"
        sf.write(s / "clips" / f"{sid}_strike.wav", x.astype("float32"), fs)
        events.append({"id": sid, "kind": "strike", "source": "tof", "t": 1.0 + i, "tile_present": True, "tof_mm": 88,
                       "tile_id": f"T{i}", "labels": {"condition": "tile"}})
    (s / "strikes.json").write_text(json.dumps(events))
    (s / "manifest.json").write_text(json.dumps({"run_type": "tile", "note": "synthetic"}))
    return root


def test_building_the_sound_reference_needs_enough_good_tiles(win):
    win.shown.clear()
    win.build_reference()
    title, text = win.shown[-1]
    assert title == "Sound reference" and "Not enough labelled tiles" in text


def test_building_the_reference_grades_tiles_by_sound(win, tmp_path):
    import os

    root = _synthetic_session(tmp_path)
    win.load(root)
    _wait_ready(win)
    recs = win.data.records
    for r in recs[:10]:
        win.labels.set(r.key, label="good")
    for r in recs[10:]:
        win.labels.set(r.key, label="cracked")
    win.shown.clear()
    win.build_reference()
    text = win.shown[-1][1]
    assert "built from 10 tiles" in text and "Defective tiles caught: 2 of 2" in text
    assert os.path.isfile(win.cfg["paths"]["strike_reference"])
    _select(win, recs[10].key)                                       # a 5 kHz tile
    info = win.info.get("1.0", "end")
    assert "Sound grade (vs your good tiles)" in info and "Sound grade: DEFECTIVE" in info
    _select(win, recs[3].key)                                        # a 2 kHz tile
    assert "Sound grade: GOOD" in win.info.get("1.0", "end")
