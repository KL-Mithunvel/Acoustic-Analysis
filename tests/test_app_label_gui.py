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
    w = LabelWindow(load_config(), sessions_dir=root, labels_path=tmp_path_factory.mktemp("lab") / "labels.json")
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
