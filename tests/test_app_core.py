"""Tests for the non-Tk GUI core: explain, state, service."""

from __future__ import annotations

import time

import numpy as np
import pytest

from acoustic_analysis.app.explain import Explainer, load_explanations
from acoustic_analysis.app.service import AnalysisService
from acoustic_analysis.app.state import ClipData, SharedState
from acoustic_analysis.config import load_config
from tests.synth import make_impact_clip

_FS = 48000


# -- explain ---------------------------------------------------------------
def test_load_explanations_parses_blocks():
    entries = load_explanations()
    assert "spectrum" in entries
    title, body = entries["spectrum"]
    assert "spectrum" in title.lower()
    assert len(body) > 40


def test_load_explanations_missing_file(tmp_path):
    assert load_explanations(tmp_path / "none.md") == {}


def test_explainer_facade():
    ex = Explainer()
    assert ex.has("edc")
    assert ex.title("edc")
    assert "\n\n" in ex.text("edc")
    assert ex.text("nonexistent-key")  # graceful fallback
    assert len(ex.glossary()) >= 5


# -- state ---------------------------------------------------------------
@pytest.fixture
def state():
    return SharedState(load_config())


def _clip(name="c", seed=0):
    samples, _ = make_impact_clip(_FS, ring_freqs=(1800.0, 5000.0), tau_s=0.1, seed=seed)
    return ClipData(name=name, samples=samples, fs=_FS)


def test_add_select_remove(state):
    fired = []
    state.add_listener(lambda: fired.append(1))
    i0 = state.add_clip(_clip("a"))
    i1 = state.add_clip(_clip("b"))
    assert state.selection() == [i1]
    state.select([i0, i1])
    assert len(state.selected_clips()) == 2
    state.remove_clip(i0)
    assert [c.name for c in state.clips()] == ["b"]
    assert fired  # listeners fired


def test_set_analysis(state):
    i = state.add_clip(_clip())
    state.set_analysis(i, {"status": "OK"}, {"grade": "GOOD"})
    assert state.clip(i).features["status"] == "OK"
    assert state.primary().grade["grade"] == "GOOD"


# -- service ---------------------------------------------------------------
def test_service_runs_extraction_off_thread(state):
    svc = AnalysisService(state)
    try:
        idx = state.add_clip(_clip(seed=3))
        svc.submit(idx)
        deadline = time.time() + 10
        results = []
        while time.time() < deadline and not results:
            results = svc.poll()
            time.sleep(0.05)
        assert results and results[0]["error"] is None
        assert results[0]["features"]["valid"] is True
        assert state.clip(idx).features is not None
    finally:
        svc.stop()


def test_service_reports_errors_without_crashing(state):
    svc = AnalysisService(state)
    try:
        bad = state.add_clip(ClipData(name="bad", samples=np.zeros(10), fs=_FS))
        svc.submit(bad)
        deadline = time.time() + 10
        results = []
        while time.time() < deadline and not results:
            results = svc.poll()
            time.sleep(0.05)
        assert results and results[0]["error"] is not None
    finally:
        svc.stop()
