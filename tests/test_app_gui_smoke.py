"""Smoke test: the whole GUI must construct, run its event loop, analyse a clip,
and switch through every tab without raising. Skipped where there is no display.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from acoustic_analysis.config import load_config
from tests.synth import make_impact_clip

_FS = 48000


def _has_display() -> bool:
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


pytestmark = pytest.mark.skipif(not _has_display(), reason="no display for Tk")


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


def test_gui_constructs_analyses_and_switches_tabs(tmp_path):
    from acoustic_analysis.app.main_window import MainWindow
    from acoustic_analysis.app.state import ClipData

    win = MainWindow(_isolated_cfg(tmp_path))
    try:
        win.update()
        samples, _ = make_impact_clip(_FS, ring_freqs=(1800.0, 5000.0, 9000.0), tau_s=0.1)
        idx = win.ctx.state.add_clip(ClipData(name="syn", samples=samples, fs=_FS))
        win.ctx.service.submit(idx)

        for _ in range(60):
            win.update()
            win.ctx.service.poll()
            if win.ctx.state.clip(idx).features is not None:
                break

        assert win.ctx.state.clip(idx).features is not None
        assert win.ctx.state.clip(idx).features["valid"] is True

        for tab in range(len(win.screens)):
            win.nb.select(tab)
            win.update()
    finally:
        win._on_close()
