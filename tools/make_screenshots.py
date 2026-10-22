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

    extra_screens(win, cfg, tmp)
    win._on_close()
    label_tool_shots(cfg, tmp)


def _pump(win, predicate, timeout_s=30):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        win.update()
        win.ctx.service.poll()
        if predicate():
            return True
        time.sleep(0.03)
    return False


def extra_screens(win, cfg, tmp):
    """Home, Learn, Label tiles, Compare, Filters, Noise, Label, Calibrate, Monitor, Record, Slice.

    Demo data only. Monitor and Record are shown idle (no microphone is opened) and
    Calibrate never presses Apply, so config.yaml is not touched.
    """
    import subprocess

    import soundfile as sf
    from acoustic_analysis.app.state import ClipData
    from acoustic_analysis.io import videoaudio
    from tests.synth import make_tap_sequence

    # three analysed clips: a good ring, a shorter lower "cracked" ring, and room noise alone
    kinds = (("good-01", dict(tile=0.30, seed=70, ring_hz=2200, tau=0.05)),
             ("cracked-01", dict(tile=0.30, seed=71, ring_hz=1700, tau=0.015)),
             ("room-noise", dict(tile=0.0, seed=72)))
    ids = []
    for name, kw in kinds:
        ids.append(win.ctx.state.add_clip(ClipData(name=name, samples=demo_clip(cfg, **kw), fs=FS, source="recorded")))
        win.ctx.service.submit(ids[-1])
    _pump(win, lambda: all(win.ctx.state.clip(i).features is not None for i in ids))

    win._goto("Home")
    grab(win, "10-home")
    win._goto("Learn")
    grab(win, "11-learn")
    win._goto("Label tiles")
    grab(win, "12-label-tiles-hub")

    compare = next(s for s in win.screens if s.title == "Compare")
    win.ctx.state.select(ids[:2])
    win._goto("Compare")
    compare.refresh()
    for i in ids[:2]:
        compare.clip_list.selection_set(i)
    grab(win, "13-compare")

    win.ctx.state.select([ids[0]])
    win._goto("Filters")
    grab(win, "14-filters")

    noise = next(s for s in win.screens if s.title == "Noise")
    win._goto("Noise")
    noise.refresh()
    noise.noise_pick.current(2)
    noise.target_pick.current(0)
    noise.refresh()
    grab(win, "15-noise")

    win._goto("Label")
    grab(win, "16-label")

    calib = next(s for s in win.screens if s.title == "Calibrate")
    t = np.arange(2 * FS) / FS
    calib._tone, calib._fs = 0.05 * np.sin(2 * np.pi * 1000 * t), FS
    calib.src.set("demo 1 kHz tone (synthetic)")
    calib._compute()                       # never _apply(): that would rewrite config.yaml
    win._goto("Calibrate")
    grab(win, "17-calibrate")

    win._goto("Monitor")
    grab(win, "18-monitor-idle")
    win._goto("Record")
    grab(win, "19-record-idle")

    if videoaudio.is_available():
        wav, video = tmp / "track.wav", tmp / "taps.mp4"
        sf.write(wav, make_tap_sequence(FS, [0.6, 1.5, 2.4, 3.3], duration_s=4.0).astype(np.float32), FS, subtype="FLOAT")
        subprocess.run([videoaudio.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "testsrc=size=640x360:rate=15:duration=4", "-i", str(wav), "-shortest", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(video)], check=True, capture_output=True)
        sl = next(s for s in win.screens if s.title == "Slice")
        win._goto("Slice")
        sl.load_media(video)
        _pump(win, lambda: sl._samples is not None)
        sl.find_strikes()
        sl.tree.selection_set(("1", "2"))
        sl.grade.set("3A")
        sl.defect.set("good")
        sl.apply_labels()
        sl.tree.selection_set(("3", "4"))
        sl.grade.set("4")
        sl.defect.set("cracked")
        sl.apply_labels()
        sl.tree.selection_set(("1",))
        grab(win, "20-slice")


def label_tool_shots(cfg, tmp):
    """The labelling tool on the real 2026-10-19 station sessions with the real labels (a copy: nothing is written back)."""
    import shutil

    from acoustic_analysis.app.label_tool import LabelWindow

    sessions = ROOT.parent / "data" / "master" / "sessions"
    labels = ROOT / "data" / "labels.json"
    if not sessions.is_dir() or not labels.is_file():
        print("skipped the labelling tool: no sessions or labels.json")
        return
    shutil.copy2(labels, tmp / "labels.json")
    cfg = dict(cfg, paths={**cfg["paths"], "strike_reference": str(tmp / "strike_reference.json")})
    w = LabelWindow(cfg, sessions_dir=sessions, labels_path=tmp / "labels.json")
    w.dialog = lambda title, text: None
    _pump_label(w)
    key = "2026-10-19_18-44-39/S0024"            # a tile labelled cracked
    if w.tree.exists(key):
        w.tree.selection_set(key)
        w.tree.focus(key)
        w.tree.see(key)
    _pump_label(w)
    grab(w, "21-label-tool-labelled")
    w.destroy()


def _pump_label(w, timeout_s=60):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        w.update()
        if w.status.get().startswith("Ready"):
            break
        time.sleep(0.05)
    for _ in range(20):
        w.update()
        time.sleep(0.05)


if __name__ == "__main__":
    main()
