"""The Test Tile screen, driven with a fake Nano (scripted serial port) and a fake microphone ring."""

from __future__ import annotations

import json
import time

import numpy as np
import pytest

from acoustic_analysis.io.nano_link import NanoLink
from acoustic_analysis.strike_reference import build_reference
from acoustic_analysis.tile_test import analyse_strike
from tests.conftest import has_display
from tests.test_app_gui_smoke import _isolated_cfg
from tests.test_nano_link import FakeSerial

pytestmark = pytest.mark.skipif(not has_display(), reason="no display for Tk")

FS = 48000


def _ring_clip(freq=2000.0, tau=0.02, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(1.5 * FS)) / FS
    x = rng.normal(0, 1e-3, t.size)
    m = t >= 0.5
    x[m] += 0.6 * np.sin(2 * np.pi * freq * (t[m] - 0.5)) * np.exp(-(t[m] - 0.5) / tau)
    return x


class FakeRing:
    fs = FS

    def __init__(self):
        self.level = 0.05
        self.started = self.stopped = False
        self.next_clip = _ring_clip()
        self.cuts = []

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def cut_after(self, t_event, pre_s, post_s, wait_s=3.0):
        self.cuts.append((t_event, pre_s, post_s))
        return self.next_clip


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    from acoustic_analysis.app.main_window import MainWindow
    from acoustic_analysis.app.screens_tester import TesterScreen

    tmp = tmp_path_factory.mktemp("tester")
    cfg = _isolated_cfg(tmp)
    cfg["paths"].update(strike_reference=str(tmp / "strike_reference.json"), test_sessions_dir=str(tmp / "sessions"))
    ser, ring = FakeSerial(), FakeRing()
    mp = pytest.MonkeyPatch()
    mp.setattr(TesterScreen, "link_factory", staticmethod(lambda c: NanoLink(c, serial_factory=lambda port, baud: ser)))
    mp.setattr(TesterScreen, "ring_factory", staticmethod(lambda c, dev: ring))
    mp.setattr(TesterScreen, "ports_fn", staticmethod(lambda c: [{"device": "COM9", "description": "USB-SERIAL CH340",
                                                                  "vid": "1A86", "candidate": True}]))
    w = MainWindow(cfg)
    w.update()
    screen = next(s for s in w.screens if s.title == "Test Tile")
    try:
        yield {"win": w, "screen": screen, "ser": ser, "ring": ring, "tmp": tmp, "cfg": cfg}
    finally:
        w._on_close()
        mp.undo()


def _wait(win, cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        win.update()
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for the screen")


def test_connect_starts_the_link_and_the_microphone(env):
    s, w = env["screen"], env["win"]
    s._refresh_ports()
    assert s.port.get().startswith("COM9")
    s._toggle_connect()
    assert s.link.connected and env["ring"].started and s.connect_btn.cget("text") == "Disconnect"
    env["ser"].push("HELLO nano-fw-0.2", "HB 5000 0 1 0 1 0 91 1 7 1500 0 30 0")
    _wait(w, lambda: s.link.link_ok and "TILE" in s.tof_var.get())
    assert "91 mm" in s.tof_var.get() and s.link_var.get().startswith("Striker: ready (manual)")
    assert any(x.startswith(b"PING") for x in env["ser"].written)            # the keep-alive is running


def test_strike_now_arms_taps_and_a_ungraded_result_is_shown_and_saved(env):
    s, w, ser = env["screen"], env["win"], env["ser"]
    ser.written.clear()
    s._strike_now()
    assert ser.sent() == ["MODE 1", "STRIKE 1", "TAP"]
    ser.push("TAP 1 1 91 1000 1")                                              # the Nano: struck (manual), tile present
    _wait(w, lambda: len(s.results) == 1)
    r = s.results[0]
    assert r["verdict"]["grade"] == "UNGRADED" and r["features"]["onset_found"]       # analysed, no reference to grade against
    assert s.verdict.cget("text") == "UNGRADED" and "no reference" in s.meaning.cget("text").lower()
    t_event, pre, post = env["ring"].cuts[0]
    assert pre == pytest.approx(0.5) and post == pytest.approx(1.0)                  # a 1.5 s clip, strike 0.5 s in
    assert r["saved_as"] == "S0001" and len(s.tree.get_children()) == 1
    sess = list((env["tmp"] / "sessions").iterdir())
    assert len(sess) == 1 and (sess[0] / "clips" / "S0001_strike.wav").is_file()
    assert len(s.plot.figure.axes) == 3


def test_with_a_reference_a_good_tile_is_good_and_a_different_one_is_not(env):
    s, w, ser = env["screen"], env["win"], env["ser"]
    cfg = env["cfg"]
    feats = [analyse_strike(_ring_clip(2000 + 15 * i, 0.02, seed=i), FS, cfg, None)["features"] for i in range(12)]
    # the isolated test config has no strike block override, so the shipped defaults apply
    build_reference(feats, cfg).save(env["tmp"] / "strike_reference.json")
    s._load_reference()
    assert "built from 12 good tiles" in s.ref_var.get()

    env["ring"].next_clip = _ring_clip(2010, 0.02, seed=40)
    ser.push("TAP 2 1 90 2000 1")
    _wait(w, lambda: len(s.results) == 2)
    assert s.results[1]["verdict"]["grade"] == "GOOD" and s.verdict.cget("text") == "GOOD"

    env["ring"].next_clip = _ring_clip(5200, 0.08, seed=41)
    ser.push("TAP 3 1 90 3000 1")
    _wait(w, lambda: len(s.results) == 3)
    assert s.results[2]["verdict"]["grade"] in ("BORDERLINE", "DEFECTIVE") and s.reasons.cget("text")


def test_no_tile_and_non_tile_strikes(env):
    s, w, ser = env["screen"], env["win"], env["ser"]
    n = len(s.results)
    ser.push("TAP 4 0 140 4000 1")                                           # the sensor saw no tile
    _wait(w, lambda: len(s.results) == n + 1)
    assert s.results[-1]["verdict"]["grade"] == "NO TILE" and s.verdict.cget("text") == "NO TILE"
    ser.push("TAP 5 0 140 5000 4")                                           # the striker lowering itself
    for _ in range(15):
        w.update()
        time.sleep(0.02)
    assert len(s.results) == n + 1 and "lowered itself" in s.status.get()


def test_tile_coming_and_stop_and_hold_commands(env):
    s, ser = env["screen"], env["ser"]
    ser.written.clear()
    s._tile_coming()
    s._stop_striker()
    s.hold.set(40)
    s._apply_hold()
    assert ser.sent() == ["MODE 0", "STRIKE 1", "UP", "STRIKE 0", "HOLD 40"]


def test_selecting_a_history_row_shows_that_strike_again(env):
    s, w = env["screen"], env["win"]
    first = s.tree.get_children()[-1]                                        # oldest row
    s.tree.selection_set(first)
    w.update()
    assert s.verdict.cget("text") == s.results[0]["verdict"]["grade"]


def test_analysing_a_wav_file_does_not_save_it(env, tmp_path):
    s = env["screen"]
    before = len(list((env["tmp"] / "sessions").glob("*/clips/*.wav")))
    res = s.process_clip(_ring_clip(2000, 0.02, seed=77), FS, {"src": "file", "tile_present": None, "t": time.time()})
    assert res["saved_as"] is None and res["verdict"]["grade"] in ("GOOD", "BORDERLINE", "DEFECTIVE")
    assert len(list((env["tmp"] / "sessions").glob("*/clips/*.wav"))) == before


def test_a_clip_that_could_not_be_cut_says_so(env):
    s, w = env["screen"], env["win"]
    n = len(s.results)
    env["ring"].next_clip = None
    env["ser"].push("TAP 6 1 90 6000 1")
    _wait(w, lambda: "Could not cut" in s.status.get())
    assert len(s.results) == n
    env["ring"].next_clip = _ring_clip()


def test_disconnect_inhibits_the_striker_and_seals_the_session(env):
    s, w, ser = env["screen"], env["win"], env["ser"]
    folder = next((env["tmp"] / "sessions").iterdir())
    s._toggle_connect()
    assert not s.link.connected and env["ring"].stopped and s.connect_btn.cget("text") == "Connect"
    assert ser.sent()[-1] == "STRIKE 0"
    assert json.loads((folder / "manifest.json").read_text())["status"] == "complete"
    s._strike_now()                                                          # not connected: a message, not a crash
    assert "Not connected" in s.status.get()


def test_the_saved_tests_open_in_the_labelling_tool(env):
    from acoustic_analysis.io.session_reader import load_all

    recs = load_all(env["tmp"] / "sessions")
    assert len(recs) >= 3 and {r.group for r in recs} >= {"tile", "no_tile"}
    assert all(r.clip_path and r.clip_path.is_file() for r in recs)
