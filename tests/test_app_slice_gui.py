"""Drives the Slice screen the way an operator does.

Opens a real video, finds its strikes, labels the proposed snippets and saves
them, then checks the database holds what the video contained. This is the test
that would catch the screen being wired up wrongly - the pure-logic tests
cannot, because they never touch a widget.

Skipped without a display or without ffmpeg.
"""

from __future__ import annotations

import subprocess
import time

import numpy as np
import pytest
import soundfile as sf

from acoustic_analysis.config import load_config
from acoustic_analysis.io import snippets, videoaudio
from tests.conftest import has_display
from tests.synth import make_tap_sequence

_FS = 48000
_TAPS = [0.6, 1.5, 2.4, 3.3]


pytestmark = pytest.mark.skipif(
    not has_display() or not videoaudio.is_available(),
    reason="needs a display and ffmpeg",
)


@pytest.fixture(scope="module")
def _source_video(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("slice_gui")
    wav = tmp / "track.wav"
    sf.write(wav, make_tap_sequence(_FS, _TAPS, duration_s=4.0).astype(np.float32),
             _FS, subtype="FLOAT")
    out = tmp / "taps.mp4"
    subprocess.run(
        [videoaudio.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=4",
         "-i", str(wav), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "pcm_s16le", str(out)],
        check=True, capture_output=True,
    )
    return out


@pytest.fixture
def tap_video(_source_video, tmp_path):
    """A private copy per test.

    The screen writes its cuts to a sidecar beside the video and reloads them
    on reopen - correct behaviour, and exactly why tests cannot share one file:
    the second test would inherit the first one's snippets.
    """
    import shutil

    dest = tmp_path / _source_video.name
    shutil.copy2(_source_video, dest)
    return dest


def _isolated_cfg(tmp_path):
    cfg = load_config()
    cfg["paths"] = {
        "data_dir": str(tmp_path),
        "recordings_dir": str(tmp_path / "rec"),
        "database": str(tmp_path / "d.sqlite"),
        "exports_dir": str(tmp_path / "exp"),
        "reference_profile": str(tmp_path / "ref.json"),
    }
    return cfg


def _pump(win, predicate, timeout_s=30):
    """Run the Tk loop until ``predicate`` holds - the screen does its work on
    background threads and hands results back through an after() poll."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        win.update()
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def win(tmp_path):
    from acoustic_analysis.app.main_window import MainWindow

    w = MainWindow(_isolated_cfg(tmp_path))
    w.update()
    try:
        yield w
    finally:
        w._on_close()


def _slice_screen(win):
    return next(s for s in win.screens if s.title == "Slice")


def test_slice_screen_is_in_the_sidebar(win):
    win._goto("Slice")
    win.update()
    assert win._screen_title.get() == "Slice"
    assert len(win._nav_items) == len(win.screens)


def test_open_video_find_strikes_label_and_save(win, tap_video, tmp_path):
    screen = _slice_screen(win)
    win._goto("Slice")

    screen.load_media(tap_video)
    assert _pump(win, lambda: screen._samples is not None), "video never loaded"
    assert screen._duration == pytest.approx(4.0, abs=0.2)
    assert screen._has_video is True

    screen.find_strikes()
    win.update()
    assert len(screen._set.segments) == len(_TAPS)
    assert len(screen.tree.get_children()) == len(_TAPS)

    # The sidecar is written as soon as cuts exist, so closing now would not
    # lose them.
    assert snippets.has_snippets(tap_video)

    # Label the first two 3A/good and the rest 4/cracked, through the widgets.
    screen.tree.selection_set(("1", "2"))
    screen.grade.set("3A")
    screen.defect.set("good")
    screen.apply_labels()
    screen.tree.selection_set(("3", "4"))
    screen.grade.set("4")
    screen.defect.set("cracked")
    screen.apply_labels()
    win.update()
    assert [s.grade for s in screen._set.segments] == ["3A", "3A", "4", "4"]

    screen.save_to_dataset()
    assert _pump(win, lambda: all(s.saved for s in screen._set.segments)), "save never finished"

    rows = win.ctx.db.list_clips()
    assert len(rows) == len(_TAPS)
    assert [r["label"]["grade_tier"] for r in rows] == ["3A", "3A", "4", "4"]
    assert [r["label"]["label"] for r in rows] == ["good", "good", "cracked", "cracked"]
    assert all(r["features"] for r in rows), "every saved snippet should be analysed"
    assert all("taps.mp4" in (r["notes"] or "") for r in rows)

    # Saved WAVs are on disk under the isolated recordings dir.
    assert len(list((tmp_path / "rec").glob("*.wav"))) == len(_TAPS)


def test_saving_twice_does_not_duplicate_rows(win, tap_video):
    screen = _slice_screen(win)
    win._goto("Slice")
    screen.load_media(tap_video)
    assert _pump(win, lambda: screen._samples is not None)

    screen.find_strikes()
    screen.tree.selection_set(tuple(screen.tree.get_children()))
    screen.grade.set("5")
    screen.defect.set("good")
    screen.apply_labels()

    screen.save_to_dataset()
    assert _pump(win, lambda: all(s.saved for s in screen._set.segments))
    first = len(win.ctx.db.list_clips())

    screen.save_to_dataset()   # nothing is pending now
    win.update()
    assert len(win.ctx.db.list_clips()) == first


def test_resuming_a_video_restores_its_snippets(win, tap_video):
    screen = _slice_screen(win)
    win._goto("Slice")
    screen.load_media(tap_video)
    assert _pump(win, lambda: screen._samples is not None)
    screen.find_strikes()
    cut_count = len(screen._set.segments)
    assert cut_count

    # Reopening the same file must come back to the same cuts, not a blank
    # slate - that is the whole point of the sidecar.
    screen.load_media(tap_video)
    assert _pump(win, lambda: screen._samples is not None and screen._set.segments)
    assert len(screen._set.segments) == cut_count


def test_selection_and_snippet_editing(win, tap_video):
    screen = _slice_screen(win)
    win._goto("Slice")
    screen.load_media(tap_video)
    assert _pump(win, lambda: screen._samples is not None)

    # A drag on the detail plot arrives as this callback.
    screen._on_span(1.40, 1.95)
    assert screen._selection == pytest.approx((1.40, 1.95))
    screen.grade.set("3B")
    screen.defect.set("corner_broken")
    screen.add_selection()
    win.update()
    assert len(screen._set.segments) == 1
    assert screen._set.segments[0].grade == "3B"

    # Overlapping the snippet just added is refused, and says so rather than
    # raising into the Tk loop.
    screen._on_span(1.50, 1.80)
    screen.add_selection()
    win.update()
    assert len(screen._set.segments) == 1
    assert "overlap" in screen.status.get()

    screen.tree.selection_set(("1",))
    screen.delete_selected()
    win.update()
    assert screen._set.segments == []


def test_navigation_and_playhead_do_not_need_audio_hardware(win, tap_video):
    screen = _slice_screen(win)
    win._goto("Slice")
    screen.load_media(tap_video)
    assert _pump(win, lambda: screen._samples is not None)
    screen.find_strikes()

    screen._goto(0.0)
    screen.step_strike(1)
    assert screen._playhead == pytest.approx(_TAPS[0], abs=0.05)
    screen.step_strike(1)
    assert screen._playhead == pytest.approx(_TAPS[1], abs=0.05)
    screen.step_strike(-1)
    assert screen._playhead == pytest.approx(_TAPS[0], abs=0.05)

    screen.zoom.set("0.5s")
    screen._on_zoom()
    win.update()
    assert screen._view_span == pytest.approx(0.5)

    # Clicking the overview jumps the playhead there.
    class _Event:
        xdata = 2.0

    screen._on_overview_click(_Event())
    win.update()
    assert screen._playhead == pytest.approx(2.0, abs=0.01)


def test_unlabelled_snippets_are_not_saved(win, tap_video):
    screen = _slice_screen(win)
    win._goto("Slice")
    screen.load_media(tap_video)
    assert _pump(win, lambda: screen._samples is not None)
    screen.find_strikes()          # proposals carry no labels yet

    screen.save_to_dataset()
    win.update()
    assert win.ctx.db.list_clips() == []
    assert "still need both labels" in screen.status.get()
