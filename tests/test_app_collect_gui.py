"""Collect + Library screens, driven programmatically (no microphone, no dialogs)."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.dsp.machine_noise import build_striker_template
from tests.conftest import has_display
from tests.test_app_gui_smoke import _isolated_cfg
from tests.test_machine_noise import FS, _clip

pytestmark = pytest.mark.skipif(not has_display(), reason="no display for Tk")


@pytest.fixture(scope="module")
def win(tmp_path_factory):
    # One window for the whole file: repeatedly creating Tk roots in a single
    # process is flaky (intermittent TclError inside tk.Tk()), so tests share it
    # and each uses its own session folder / file names.
    from acoustic_analysis.app.main_window import MainWindow

    cfg = _isolated_cfg(tmp_path_factory.mktemp("collect"))
    w = MainWindow(cfg)
    w.update()
    try:
        yield w
    finally:
        w._on_close()


def _screen(win, title):
    return next(s for s in win.screens if s.title == title)


def test_app_opens_on_collect_and_advanced_is_collapsed(win):
    assert win._screen_title.get() == "Collect"
    assert win._group_open["ADVANCED"] is False
    win._goto("Slice")                                   # navigating into it opens the group
    assert win._group_open["ADVANCED"] is True
    win._goto("Collect")


def test_captured_clips_are_cleaned_filed_and_counted(win):
    s = _screen(win, "Collect")
    cfg = win.ctx.state.cfg
    s.profile.template = build_striker_template(           # as if Setup step B was done
        [_clip(cfg, seed=i)[0] for i in range(10)], FS, cfg)
    s._new_session()                                       # no mic: feed the queue directly
    for seed, tile in ((1, 0.3), (2, 0.0), (3, 0.3)):
        s.q.put(("clip", (_clip(cfg, tile=tile, seed=seed)[0], FS)))
    s._show_page(1)
    while not s.q.empty():
        s._handle(*s.q.get())
    win.update()
    assert s.cnt["all"].cget("text") == "3"
    assert s.cnt["tile"].cget("text") == "2" and s.cnt["rej"].cget("text") == "1"


def test_review_label_writes_dataset_row(win):
    s = _screen(win, "Collect")
    cfg = win.ctx.state.cfg
    s._new_session()
    s._handle("clip", (_clip(cfg, tile=0.3, seed=4)[0], FS))
    s._show_page(2)
    win.update()
    assert s.tree.selection()
    s._label("cracked")
    clip = s._current()
    rows = [r for r in win.ctx.db.list_clips() if r["path"] == str(clip.path)]
    assert len(rows) == 1 and rows[0]["label"]["label"] == "cracked"


def test_discard_moves_clip_to_rejected(win):
    s = _screen(win, "Collect")
    cfg = win.ctx.state.cfg
    s._new_session()
    s._handle("clip", (_clip(cfg, tile=0.3, seed=4)[0], FS))
    s._show_page(2)
    clip = s._current()
    s._discard()
    assert clip.path.parent.name == "rejected" and clip.path.is_file()


def test_machine_profile_persists_between_runs(win, tmp_path):
    from acoustic_analysis.io.machine_profile import load_profile

    s = _screen(win, "Collect")
    s._handle("motor_done", np.random.default_rng(0).normal(0, 0.003, FS))
    assert load_profile(s._profile_path).motor_noise is not None
    s._forget_profile()
    assert load_profile(s._profile_path) is None


def test_library_screen_move_rename_delete_undo(win):
    lib = win.ctx.library
    from acoustic_analysis.io.wavstore import save_clip

    save_clip(np.zeros(480), FS, lib.root / "lib_a.wav")
    scr = _screen(win, "Library")
    win._goto("Library")
    win.update()
    lib.make_folder("", "good_lib")
    scr.refresh()
    assert "lib_a.wav" in "".join(scr.files.item(i, "text") for i in scr.files.get_children())
    scr._move(["lib_a.wav"], "good_lib")
    assert (lib.root / "good_lib" / "lib_a.wav").is_file()
    scr.undo()
    assert (lib.root / "lib_a.wav").is_file()
    scr.files.selection_set("lib_a.wav")
    scr.delete()
    assert not (lib.root / "lib_a.wav").exists()
    scr.undo()
    assert (lib.root / "lib_a.wav").is_file()


def test_library_move_updates_dataset_path(win):
    from acoustic_analysis.io.wavstore import save_clip

    lib = win.ctx.library
    wav = save_clip(np.zeros(480), FS, lib.root / "db_a.wav")
    cid = win.ctx.db.add_clip(win.ctx.ensure_session(), str(wav.resolve()), "recorded", FS)
    lib.make_folder("", "good_db")
    new = lib.move("db_a.wav", "good_db")
    assert win.ctx.db.get_clip(cid)["path"] == str(new)


def test_basic_settings_apply_save_and_reset(win):
    from acoustic_analysis.config import user_settings_path

    s = _screen(win, "Settings")
    win._goto("Settings")
    win.update()
    cfg = win.ctx.state.cfg
    default = cfg["capture"]["cooldown_s"]
    s._vars[("capture", "cooldown_s")].set(2.5)
    s._vars[("machine", "dry_strikes_target")].set(99)          # out of range -> clamped to 40
    s._apply_basic()
    assert cfg["capture"]["cooldown_s"] == 2.5 and cfg["machine"]["dry_strikes_target"] == 40
    assert user_settings_path(cfg).is_file()
    s._reset_basic()
    assert cfg["capture"]["cooldown_s"] == default and not user_settings_path(cfg).exists()
