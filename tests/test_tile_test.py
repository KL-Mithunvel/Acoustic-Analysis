"""tile_test.analyse_strike and the strike logger: the pipeline, and that its output opens in the labelling tool."""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from acoustic_analysis.config import load_config
from acoustic_analysis.io.session_reader import load_session
from acoustic_analysis.io.strike_log import StrikeLogger
from acoustic_analysis.strike_reference import build_reference
from acoustic_analysis.tile_test import analyse_strike, is_graded_source

FS = 48000


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _clip(freq, tau, seed=0, noise=1e-3):
    rng = np.random.default_rng(seed)
    t = np.arange(int(1.5 * FS)) / FS
    x = rng.normal(0, noise, t.size)
    m = t >= 0.5
    x[m] += 0.6 * np.sin(2 * np.pi * freq * (t[m] - 0.5)) * np.exp(-(t[m] - 0.5) / tau)
    return x


@pytest.fixture(scope="module")
def reference(cfg):
    feats = [analyse_strike(_clip(2000 + 20 * i, 0.02, seed=i), FS, cfg, None)["features"] for i in range(12)]
    return build_reference(feats, cfg)


def test_result_carries_everything_the_screen_draws(cfg, reference):
    r = analyse_strike(_clip(2000, 0.02, seed=50), FS, cfg, reference, tile_present=True)
    assert set(r) == {"features", "verdict", "spec", "env", "wave"}
    assert r["features"]["onset_found"] and r["verdict"]["grade"] == "GOOD"
    f, p = r["spec"]
    assert p.sum() == pytest.approx(1.0) and r["env"][1][:int(0.01 * FS)].max() == pytest.approx(0.0, abs=1e-6)
    t, x, on = r["wave"]
    assert t[0] < 0 < t[-1] and on == 0.0


def test_a_tile_that_rings_differently_is_not_good(cfg, reference):
    r = analyse_strike(_clip(5200, 0.08, seed=51), FS, cfg, reference, tile_present=True)
    assert r["verdict"]["grade"] in ("BORDERLINE", "DEFECTIVE") and r["verdict"]["reasons"]


def test_no_reference_means_ungraded_but_still_analysed(cfg):
    r = analyse_strike(_clip(2000, 0.02), FS, cfg, None, tile_present=True)
    assert r["verdict"]["grade"] == "UNGRADED" and r["features"]["centroid_hz"] is not None


def test_no_tile_and_no_strike(cfg, reference):
    assert analyse_strike(_clip(2000, 0.02), FS, cfg, reference, tile_present=False)["verdict"]["grade"] == "NO TILE"
    quiet = np.random.default_rng(0).normal(0, 1e-3, int(1.5 * FS))
    r = analyse_strike(quiet, FS, cfg, reference, tile_present=True)
    assert r["verdict"]["grade"] == "RETEST" and r["spec"] is None and r["env"] is None
    assert r["wave"] is not None                                    # still shows where it looked


def test_which_strikes_are_a_tiles_tap():
    assert is_graded_source("tof") and is_graded_source("manual") and is_graded_source(None)
    assert not is_graded_source("rest") and not is_graded_source("safety") and not is_graded_source("tof_blind")


def test_logger_writes_a_session_the_labelling_tool_can_open(tmp_path, cfg):
    log = StrikeLogger(tmp_path / "sessions", FS, clock=lambda: 1_792_415_000.0)
    s1 = log.add(_clip(2000, 0.02), source="manual", tile_present=True, tof_mm=91, t=1.0, nano_seq=3, verdict="GOOD")
    s2 = log.add(_clip(2000, 0.02) * 5, source="manual", tile_present=False, tof_mm=140, t=2.0)      # clips at +/-1
    log.close()
    assert (s1, s2, log.count) == ("S0001", "S0002", 2)
    recs = {r.id: r for r in load_session(log.folder)}
    assert recs["S0001"].group == "tile" and recs["S0001"].tof_mm == 91 and recs["S0001"].clip_path.is_file()
    assert recs["S0002"].group == "no_tile" and recs["S0002"].tile_present is False
    x, fs = sf.read(recs["S0002"].clip_path)
    assert fs == FS and np.abs(x).max() <= 1.0
    man = json.loads((log.folder / "manifest.json").read_text())
    assert man["status"] == "complete" and man["run_type"] == "tile"
    assert json.loads((log.folder / "strikes.json").read_text())[0]["app_verdict"] == "GOOD"


def test_two_sessions_in_the_same_second_do_not_collide(tmp_path):
    a = StrikeLogger(tmp_path, FS, clock=lambda: 1_792_415_000.0)
    b = StrikeLogger(tmp_path, FS, clock=lambda: 1_792_415_000.0)
    assert a.folder != b.folder and a.folder.is_dir() and b.folder.is_dir()
