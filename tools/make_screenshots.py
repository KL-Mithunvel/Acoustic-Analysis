"""Capture the README screenshots from the real app.

Launches the actual GUI against a throw-away data folder, fills it with
synthetic demo data (no microphone needed), visits each screen and saves a PNG
of the window to ``docs/screenshots/``. Windows only (uses ``ImageGrab`` on the
live screen, so keep the window uncovered while it runs).

    venv\\Scripts\\python tools\\make_screenshots.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from acoustic_analysis.config import load_config  # noqa: E402
from acoustic_analysis.dsp.machine_noise import build_striker_template  # noqa: E402
from acoustic_analysis.io.wavstore import save_clip  # noqa: E402

FS = 48000
OUT = ROOT / "docs" / "screenshots"


def _striker(n):
    rng = np.random.default_rng(1234)
    t = np.arange(n) / FS
    return rng.normal(0, 1, n) * np.exp(-t / 0.002) + 0.8 * np.sin(2 * np.pi * 3100 * t) * np.exp(-t / 0.004)


def demo_clip(cfg, tile=0.0, seed=0, ring_hz=2200.0, tau=0.05):
    rng = np.random.default_rng(seed)
    n = int(0.6 * FS)
    x = rng.normal(0, 0.003, n)
    on = int(cfg["capture"]["pre_trigger_ms"] / 1000 * FS)
    s = _striker(int(0.15 * FS))
    x[on:on + s.size] += 0.6 * s
    if tile:
        t = np.arange(n - on) / FS
        x[on:] += tile * np.sin(2 * np.pi * ring_hz * t) * np.exp(-t / tau)
    return x


def grab(win, name):
    win.update_idletasks()
    win.update()
    time.sleep(0.35)
    win.update()
    x, y = win.winfo_rootx(), win.winfo_rooty()
    img = ImageGrab.grab(bbox=(x, y, x + win.winfo_width(), y + win.winfo_height()))
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / f"{name}.png")
    print("saved", OUT / f"{name}.png")


def main() -> None:
    import ctypes

    try:                     # make Tk report physical pixels so the grab box matches
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        pass
    from acoustic_analysis.app.main_window import MainWindow
    from acoustic_analysis.app.state import ClipData

    tmp = Path(tempfile.mkdtemp(prefix="aa_shots_"))
    cfg = load_config()
    cfg["paths"] = {"data_dir": str(tmp), "recordings_dir": str(tmp / "rec"),
                    "database": str(tmp / "d.sqlite"), "exports_dir": str(tmp / "exp"),
                    "reference_profile": str(tmp / "ref.json")}
    win = MainWindow(cfg)
    win.geometry("1320x800+20+20")
    win.update()
    collect = next(s for s in win.screens if s.title == "Collect")
    library = next(s for s in win.screens if s.title == "Library")

    # --- Collect: setup, with both calibrations done ------------------------
    collect.profile.motor_noise = np.random.default_rng(5).normal(0, 0.003, 3 * FS)
    collect.profile.template = build_striker_template([demo_clip(cfg, seed=i) for i in range(12)], FS, cfg)
    collect._dry = [None] * 12
    collect._devs()
    collect._show_page(0)
    grab(win, "01-collect-setup")

    # --- Collect: listening --------------------------------------------------
    collect._new_session()
    collect._show_page(1)
    collect.meter.set(0.2, 0.02)
    collect.big_state.configure(text="Sound heard - recording...", foreground="#e6b053")
    for seed, tile in ((1, 0.30), (2, 0.0), (3, 0.28), (4, 0.33), (5, 0.0), (6, 0.25)):
        collect._handle("clip", (demo_clip(cfg, tile=tile, seed=seed), FS))
    collect.last.configure(text="tap-006  →  kept")
    grab(win, "02-collect-listen")

    # --- Collect: review -----------------------------------------------------
    collect._show_page(2)
    win.update()
    kids = collect.tree.get_children()
    collect.tree.selection_set(kids[0])
    collect._draw_review()
    win.update()
    time.sleep(0.4)
    collect._label("good")                       # tap-001
    collect.tree.selection_set(kids[2])
    collect._label("cracked")                    # tap-003 (advances to tap-004)
    collect.tree.selection_set(kids[0])
    collect._draw_review()
    grab(win, "03-collect-review")

    # --- Library --------------------------------------------------------------
    lib = win.ctx.library
    lib.make_folder("", "cracked tiles")
    lib.make_folder("", "reference good")
    for i, (tile, hz) in enumerate(((0.3, 2200), (0.28, 2300), (0.3, 2150))):
        save_clip(demo_clip(cfg, tile=tile, seed=40 + i, ring_hz=hz), FS, lib.root / "reference good" / f"good-{i + 1:02d}.wav")
    win._goto("Library")
    library._folder = lib.relative(collect.store.folder)      # open the session folder
    library.refresh()
    first = library.files.get_children()
    if first:
        library.files.selection_set(first[0])
    grab(win, "04-library")

    # --- Analyze + Export ------------------------------------------------------
    x = demo_clip(cfg, tile=0.3, seed=60)
    idx = win.ctx.state.add_clip(ClipData(name="tap-001", samples=x, fs=FS, source="recorded"))
    win.ctx.service.submit(idx)
    deadline = time.time() + 10
    while time.time() < deadline and win.ctx.state.clip(idx).features is None:
        win.update()
        win.ctx.service.poll()
        time.sleep(0.05)
    win._goto("Analyze")
    grab(win, "05-analyze")
    win._goto("Export")
    grab(win, "06-export")
    win._goto("Settings")
    grab(win, "07-settings")

    win._on_close()


if __name__ == "__main__":
    main()
