"""Smoke test: the whole GUI must construct, run its event loop, analyse a clip,
and switch through every sidebar screen without raising. Skipped where there is
no display.
"""

from __future__ import annotations

import time

import pytest

from acoustic_analysis.config import load_config
from tests.conftest import has_display
from tests.synth import make_impact_clip

_FS = 48000


pytestmark = pytest.mark.skipif(not has_display(), reason="no display for Tk")


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

        deadline = time.time() + 10
        while time.time() < deadline:
            win.update()
            win.ctx.service.poll()
            if win.ctx.state.clip(idx).features is not None:
                break
            time.sleep(0.03)

        assert win.ctx.state.clip(idx).features is not None
        assert win.ctx.state.clip(idx).features["valid"] is True

        assert len(win._nav_items) == len(win.screens)
        for i in range(len(win.screens)):
            win._show(i)  # calls _refresh_current: title + soft-key wiring
            win.update()

        # instrument frame is present and wired
        assert win._screen_title.get()
        win._tick_clock()
        win._step_clip(1)
        win._step_clip(-1)
        win._go_back()
        win.update()
    finally:
        win._on_close()
