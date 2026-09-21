"""The Slice screen: a tap-test video in, labelled snippets out.

The recordings this project has to work from are phone videos - one continuous
take holding dozens of strikes on tiles of different grades. Nothing else in
the app can use that: every analysis path here starts from a clip containing
exactly one strike. This screen is the bridge. Open a video, see its audio,
cut it into one snippet per tap, label each with a grade tier and a defect
class, and save the lot into the same dataset the Label screen writes to.

Design decisions worth knowing before changing anything here:

* **The detector proposes, the operator disposes.** "Find strikes" marks every
  tap it can see and pre-cuts a snippet round each one. It is not trusted to be
  right - every cut stays draggable and deletable - but confirming a hundred
  proposals is a different job from drawing a hundred selections by hand.
* **Labels are sticky.** A new snippet inherits the last grade/defect used,
  because taps come in runs of the same tile. Cutting ten taps of one grade-4
  tile should not mean picking "4" ten times.
* **The video frame is a labelling aid, not a player.** It shows which tile is
  under the hammer at the playhead. There is no video playback - the audio is
  the measurement, and synchronised video would cost far more than it informs.
* **Nothing reaches the dataset until Save.** In-progress cuts live in a
  sidecar JSON beside the video (io/snippets.py), so an unfinished video can be
  closed and picked up later without putting half-labelled rows in the
  training data.

GUI stays thin (Development Rule 4): the detection, the snippet arithmetic and
the file work all live in dsp/segmentation.py, segments.py and io/, and this
module only wires them to widgets.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np

from .. import segments as segmod
from ..config import resolve_path
from ..dsp import segmentation as seg
from ..features import extract_features
from ..io import audio_out, snippets, videoaudio
from ..io.wavstore import save_clip
from ..segments import Segment, SnippetSet
from . import plots
from .screens import _Base
from .state import ClipData
from .widgets import MplPanel, info_button

_ZOOM_CHOICES = [0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
_PLAYHEAD_MS = 60      # playhead refresh while audio plays
_FRAME_DEBOUNCE_MS = 180  # wait this long after the last scrub before decoding


class SliceScreen(_Base):
    title = "Slice"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        cfg = ctx.state.cfg
        self._vcfg = cfg.get("video", {}) or {}

        # -- source state --------------------------------------------------
        self._path: Path | None = None
        self._samples: np.ndarray | None = None
        self._fs: int = int(self._vcfg.get("audio_sample_rate", 48000))
        self._duration = 0.0
        self._env: tuple[np.ndarray, np.ndarray] | None = None
        self._onsets: list[float] = []
        self._set = SnippetSet(source="")
        self._has_video = False

        # -- view state ----------------------------------------------------
        self._view_start = 0.0
        self._view_span = 2.0
        self._playhead = 0.0
        self._selection: tuple[float, float] | None = None
        self._player = None
        self._play_origin = 0.0
        self._span_selector = None
        self._detail_line = None
        self._overview_line = None
        self._frame_job = None
        self._frame_image = None  # a PhotoImage must outlive the call that set it

        self._work: queue.Queue = queue.Queue()
        self._busy = False

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, minsize=300, weight=0)
        self.rowconfigure(1, weight=1)

        self._build_toolbar()
        self._build_plots()
        self._build_side_panel()
        self._build_table()

        self.after(200, self._poll_work)
        self._set_status("open a video or audio file to start slicing")

    # -- construction ------------------------------------------------------
    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Button(bar, text="Open video...", command=self.open_media).pack(side="left")
        self.file_lbl = tk.StringVar(value="no file")
        ttk.Label(bar, textvariable=self.file_lbl).pack(side="left", padx=8)

        info_button(bar, self.ctx.explainer, "slice_screen").pack(side="right")
        ttk.Button(bar, text="Save to dataset", command=self.save_to_dataset).pack(
            side="right", padx=4)
        ttk.Button(bar, text="Find strikes", command=self.find_strikes).pack(side="right")
        ttk.Label(bar, text="sensitivity").pack(side="right", padx=(12, 4))
        self.sensitivity = tk.DoubleVar(
            value=float(self._vcfg.get("onsets", {}).get("threshold_mult", 6.0)))
        ttk.Scale(bar, from_=12.0, to=2.0, variable=self.sensitivity, length=110).pack(
            side="right")

    def _build_plots(self) -> None:
        left = ttk.Frame(self)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        self.p_overview = MplPanel(left, self.ctx.explainer, "take_overview", figsize=(7.4, 1.5))
        self.p_overview.grid(row=0, column=0, sticky="ew")
        self.p_detail = MplPanel(left, self.ctx.explainer, "take_detail", figsize=(7.4, 3.0))
        self.p_detail.grid(row=1, column=0, sticky="nsew", pady=(4, 0))

        self.p_overview.canvas.mpl_connect("button_press_event", self._on_overview_click)

        self._build_transport(left)

    def _build_transport(self, parent) -> None:
        bar = ttk.Frame(parent)
        bar.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        ttk.Button(bar, text="|< strike", width=9, command=lambda: self.step_strike(-1)).pack(side="left")
        ttk.Button(bar, text="Play", width=7, command=self.play_from_playhead).pack(side="left", padx=3)
        ttk.Button(bar, text="Play sel", width=9, command=self.play_selection).pack(side="left")
        ttk.Button(bar, text="Stop", width=6, command=self.stop_audio).pack(side="left", padx=3)
        ttk.Button(bar, text="strike >|", width=9, command=lambda: self.step_strike(1)).pack(side="left")

        self.position = tk.DoubleVar(value=0.0)
        self._scrub = ttk.Scale(bar, from_=0.0, to=1.0, variable=self.position,
                                command=self._on_scrub)
        self._scrub.pack(side="left", fill="x", expand=True, padx=8)

        self.time_lbl = tk.StringVar(value="0.000 / 0.000 s")
        ttk.Label(bar, textvariable=self.time_lbl, width=18).pack(side="left")

        ttk.Label(bar, text="zoom").pack(side="left", padx=(8, 2))
        self.zoom = ttk.Combobox(bar, width=6, state="readonly",
                                 values=[f"{z:g}s" for z in _ZOOM_CHOICES])
        self.zoom.set("2s")
        self.zoom.bind("<<ComboboxSelected>>", self._on_zoom)
        self.zoom.pack(side="left")

    def _build_side_panel(self) -> None:
        side = ttk.Frame(self)
        side.grid(row=1, column=1, sticky="nsew")

        self.frame_lbl = ttk.Label(side, anchor="center", justify="center",
                                   text="(video frame appears here)")
        self.frame_lbl.pack(fill="x", pady=(0, 8))

        form = ttk.LabelFrame(side, text="label the selection", padding=8)
        form.pack(fill="x")

        cfg = self.ctx.state.cfg["labels"]
        ttk.Label(form, text="grade").grid(row=0, column=0, sticky="w", pady=3)
        self.grade = ttk.Combobox(form, values=list(cfg.get("grades", [])),
                                  state="readonly", width=16)
        self.grade.grid(row=0, column=1, sticky="w")
        ttk.Label(form, text="defect").grid(row=1, column=0, sticky="w", pady=3)
        self.defect = ttk.Combobox(form, values=cfg["classes"] + cfg["extra"],
                                   state="readonly", width=16)
        self.defect.grid(row=1, column=1, sticky="w")

        ttk.Button(form, text="Add selection as snippet", command=self.add_selection).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        ttk.Button(form, text="Apply labels to selected rows", command=self.apply_labels).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=2)

        actions = ttk.LabelFrame(side, text="snippets", padding=8)
        actions.pack(fill="x", pady=8)
        for text, cmd in (
            ("Play snippet", self.play_selected_row),
            ("Snap to strike", self.snap_selected),
            ("Delete snippet", self.delete_selected),
            ("Send to Analyze", self.send_to_analyze),
        ):
            ttk.Button(actions, text=text, command=cmd).pack(fill="x", pady=2)

        self.summary_lbl = tk.StringVar(value="")
        ttk.Label(side, textvariable=self.summary_lbl, justify="left",
                  wraplength=290).pack(anchor="w", pady=(4, 0))
        self.status = tk.StringVar(value="")
        ttk.Label(side, textvariable=self.status, justify="left",
                  wraplength=290).pack(anchor="w", pady=(6, 0))

    def _build_table(self) -> None:
        wrap = ttk.Frame(self)
        wrap.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self.rowconfigure(2, minsize=170, weight=0)

        cols = ("#", "start", "dur", "grade", "defect", "saved")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", height=6,
                                 selectmode="extended")
        widths = {"#": 44, "start": 90, "dur": 70, "grade": 80, "defect": 130, "saved": 60}
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths[c], anchor="center")
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)
        self.tree.bind("<Double-1>", lambda _e: self.play_selected_row())
        # Keys act on the table only when it has focus, so they cannot fight
        # the main window's global shortcuts.
        self.tree.bind("<Delete>", lambda _e: self.delete_selected())
        self.tree.bind("<space>", lambda _e: (self.play_selected_row(), "break")[1])
        for i, grade in enumerate(self.ctx.state.cfg["labels"].get("grades", []), start=1):
            self.tree.bind(str(i), lambda _e, g=grade: self._quick_label(grade=g))

    # -- opening -----------------------------------------------------------
    def open_media(self) -> None:
        if not videoaudio.is_available():
            messagebox.showerror(
                "Slice",
                "ffmpeg was not found.\n\nInstall it into this app's environment with\n"
                "    pip install imageio-ffmpeg\n\nor put ffmpeg on PATH.",
            )
            return
        path = filedialog.askopenfilename(
            title="Open a tap-test video or audio file",
            filetypes=[
                ("Video", " ".join(f"*{s}" for s in sorted(videoaudio.VIDEO_SUFFIXES))),
                ("Audio", " ".join(f"*{s}" for s in sorted(videoaudio.AUDIO_SUFFIXES))),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.load_media(path)

    def load_media(self, path) -> None:
        """Decode on a worker thread - a ten-minute take takes seconds to
        extract, and doing it on the Tk thread freezes the window."""
        path = Path(path)
        self.stop_audio()
        self._busy = True
        self._set_status(f"reading {path.name} ...")
        self.file_lbl.set(path.name)

        fs = int(self._vcfg.get("audio_sample_rate", 48000))
        cache = self._cache_dir()

        def work():
            try:
                samples, real_fs, _ = videoaudio.extract_audio(path, fs, cache)
                meta = videoaudio.probe(path)
                self._work.put(("loaded", path, samples, real_fs, meta, None))
            except Exception as exc:  # noqa: BLE001 - reported in the UI
                self._work.put(("loaded", path, None, 0, None, exc))

        threading.Thread(target=work, daemon=True, name="slice-extract").start()

    def _on_loaded(self, path, samples, fs, meta, error) -> None:
        self._busy = False
        if error is not None:
            self.file_lbl.set("no file")
            messagebox.showerror("Slice", f"{path.name}\n\n{error}")
            self._set_status(f"could not open {path.name}")
            return

        self._path = path
        self._samples = samples
        self._fs = fs
        self._duration = samples.size / fs
        self._has_video = bool(meta and meta.get("has_video"))
        self._onsets = []
        self._selection = None
        self._playhead = 0.0
        self._view_start = 0.0

        buckets = int(self._vcfg.get("overview_buckets", 2000))
        self._env = seg.envelope_minmax(samples, buckets)

        existing = None
        try:
            existing = snippets.load_snippets(path)
        except ValueError as exc:
            messagebox.showwarning("Slice", f"ignoring a damaged sidecar:\n{exc}")
        self._set = existing or SnippetSet(
            source=str(path), duration_s=self._duration, sample_rate=fs)
        self._set.duration_s = self._duration
        self._set.sample_rate = fs

        self._scrub.configure(to=max(self._duration, 0.001))
        resumed = f", resumed {len(self._set.segments)} snippet(s)" if self._set.segments else ""
        self._set_status(f"{path.name}: {self._duration:.1f} s of audio{resumed}")
        self._refresh_all()
        self._request_frame()

    # -- detection ---------------------------------------------------------
    def find_strikes(self) -> None:
        if self._samples is None:
            self._set_status("open a file first")
            return
        ocfg = dict(self._vcfg.get("onsets", {}) or {})
        scfg = dict(self._vcfg.get("snippet", {}) or {})
        try:
            onsets = seg.detect_onsets(
                self._samples, self._fs,
                smooth_ms=float(ocfg.get("smooth_ms", 5.0)),
                threshold_mult=float(self.sensitivity.get()),
                noise_percentile=float(ocfg.get("noise_percentile", 25.0)),
                min_gap_s=float(ocfg.get("min_gap_s", 0.35)),
                min_peak_ratio=float(ocfg.get("min_peak_ratio", 0.05)),
            )
        except ValueError as exc:
            messagebox.showerror("Slice", str(exc))
            return

        self._onsets = [o / self._fs for o in onsets]
        windows = seg.segments_from_onsets(
            onsets, self._samples.size, self._fs,
            pre_ms=float(scfg.get("pre_ms", 30.0)),
            post_ms=float(scfg.get("post_ms", 700.0)),
            guard_ms=float(scfg.get("guard_ms", 20.0)),
        )

        # Existing snippets win: a strike already cut and labelled by hand must
        # not be replaced by a fresh proposal on top of it.
        added = 0
        for (s0, s1), onset in zip(windows, onsets):
            candidate = Segment(
                start_s=s0 / self._fs, end_s=s1 / self._fs,
                grade=self.grade.get(), defect=self.defect.get(),
                onset_s=onset / self._fs,
            )
            try:
                self._set.segments = segmod.add(
                    self._set.segments, candidate, self._duration)
                added += 1
            except ValueError:
                continue

        self._save_sidecar()
        self._set_status(
            f"found {len(self._onsets)} strike(s), added {added} new snippet(s) "
            f"- {len(self._onsets) - added} already covered"
        )
        self._refresh_all()

    # -- selection and snippets --------------------------------------------
    def _on_span(self, t0: float, t1: float) -> None:
        if t1 - t0 < 1e-4:   # a click, not a drag
            return
        self._selection = (max(0.0, t0), min(self._duration, t1))
        self._playhead = self._selection[0]
        self._sync_position()
        self._set_status(
            f"selection {self._selection[0]:.3f} - {self._selection[1]:.3f} s "
            f"({(self._selection[1] - self._selection[0]) * 1000:.0f} ms)"
        )
        self._redraw_detail()

    def add_selection(self) -> None:
        if self._samples is None or self._selection is None:
            self._set_status("drag across the detail plot to select a snippet first")
            return
        start, end = self._selection
        candidate = Segment(
            start_s=start, end_s=end,
            grade=self.grade.get(), defect=self.defect.get(),
        )
        # Snapping only helps when the detector has run; without onsets the
        # hand-drawn edges are all the information there is.
        candidate = segmod.snap_to_onsets(candidate, self._onsets)
        try:
            self._set.segments = segmod.add(self._set.segments, candidate, self._duration)
        except ValueError as exc:
            self._set_status(str(exc))
            return
        self._selection = None
        self._save_sidecar()
        self._set_status(f"added snippet #{candidate.sid}")
        self._refresh_all()

    def delete_selected(self) -> None:
        for sid in self._selected_sids():
            self._set.segments = segmod.remove(self._set.segments, sid)
        self._save_sidecar()
        self._refresh_all()

    def snap_selected(self) -> None:
        if not self._onsets:
            self._set_status("run Find strikes first - there is nothing to snap to")
            return
        sids = set(self._selected_sids())
        snapped = []
        for i, s in enumerate(self._set.segments):
            if s.sid in sids:
                moved = segmod.snap_to_onsets(s, self._onsets)
                if moved is not s:
                    self._set.segments[i] = moved
                    snapped.append(s.sid)
        self._set.segments = segmod.renumber(self._set.segments)
        self._save_sidecar()
        self._set_status(f"snapped {len(snapped)} snippet(s) to the nearest strike")
        self._refresh_all()

    def apply_labels(self) -> None:
        grade = self.grade.get() or None
        defect = self.defect.get() or None
        if grade is None and defect is None:
            self._set_status("pick a grade and/or a defect class first")
            return
        n = segmod.apply_labels(self._set.segments, self._selected_sids(),
                                grade=grade, defect=defect)
        self._save_sidecar()
        self._set_status(f"labelled {n} snippet(s)")
        self._refresh_all()

    def _quick_label(self, grade: str) -> None:
        """Number keys 1..n set the grade on the selected rows - the fast path
        through a run of taps on one tile."""
        self.grade.set(grade)
        if self._selected_sids():
            self.apply_labels()

    # -- playback ----------------------------------------------------------
    def play_from_playhead(self) -> None:
        self._play(self._playhead, self._duration)

    def play_selection(self) -> None:
        if self._selection is None:
            self.play_from_playhead()
            return
        self._play(*self._selection)

    def play_selected_row(self) -> None:
        seg_ = self._first_selected_segment()
        if seg_ is None:
            self.play_from_playhead()
            return
        self._play(seg_.start_s, seg_.end_s)

    def _play(self, start_s: float, end_s: float) -> None:
        if self._samples is None or not audio_out.is_available():
            self._set_status("no audio output available")
            return
        self.stop_audio()
        try:
            self._player = audio_out.play_region(self._samples, self._fs, start_s, end_s)
        except (ValueError, RuntimeError) as exc:
            self._set_status(f"playback failed: {exc}")
            return
        self._play_origin = start_s
        self.after(_PLAYHEAD_MS, self._tick_playhead)

    def stop_audio(self) -> None:
        if self._player is not None:
            self._player.stop()
            self._player = None

    def _tick_playhead(self) -> None:
        if self._player is None:
            return
        self._playhead = self._play_origin + self._player.position_s
        self._follow_playhead()
        self._move_playhead_lines()
        self._sync_position()
        if self._player.is_playing:
            self.after(_PLAYHEAD_MS, self._tick_playhead)
        else:
            self._player = None

    def _follow_playhead(self) -> None:
        """Scroll the detail view when the playhead runs past its edge, so a
        long play does not leave the operator watching a static window."""
        if self._playhead < self._view_start or self._playhead > self._view_start + self._view_span:
            self._view_start = max(0.0, self._playhead - self._view_span * 0.25)
            self._redraw_detail()

    def step_strike(self, direction: int) -> None:
        """Jump to the next/previous detected strike, or snippet if the
        detector has not run."""
        marks = self._onsets or [s.start_s for s in self._set.segments]
        if not marks:
            self._set_status("no strikes found yet - run Find strikes")
            return
        ordered = sorted(marks)
        if direction > 0:
            nxt = next((t for t in ordered if t > self._playhead + 1e-4), ordered[-1])
        else:
            nxt = next((t for t in reversed(ordered) if t < self._playhead - 1e-4), ordered[0])
        self._goto(nxt)

    def _goto(self, t_s: float) -> None:
        self._playhead = max(0.0, min(t_s, self._duration))
        self._view_start = max(0.0, self._playhead - self._view_span * 0.3)
        self._sync_position()
        self._redraw_detail()
        self._redraw_overview()
        self._request_frame()

    # -- saving ------------------------------------------------------------
    def save_to_dataset(self) -> None:
        if self._samples is None:
            self._set_status("nothing to save")
            return
        pending = [s for s in self._set.segments if s.labelled and not s.saved]
        if not pending:
            unlabelled = [s for s in self._set.segments if not s.labelled]
            self._set_status(
                f"nothing new to save ({len(unlabelled)} snippet(s) still need both labels)"
                if unlabelled else "every snippet is already saved"
            )
            return
        if self._busy:
            self._set_status("still busy - wait for the current job to finish")
            return

        self._busy = True
        self._set_status(f"saving {len(pending)} snippet(s) ...")

        cfg = self.ctx.state.cfg
        rec_dir = resolve_path(cfg, "recordings_dir")
        samples, fs, path = self._samples, self._fs, self._path
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in path.stem)[:40]

        # The worker does the slow, thread-safe half - writing WAVs and
        # extracting features. It deliberately does NOT touch the database:
        # ``Dataset``'s sqlite3 connection belongs to the thread that opened
        # it (the Tk thread), and every other screen writes from there too.
        # The rows are inserted in _on_saved, which runs back on the Tk thread
        # and costs microseconds next to the feature extraction.
        def work():
            prepared, failed = [], []
            for s in pending:
                try:
                    a = max(0, int(round(s.start_s * fs)))
                    b = min(samples.size, int(round(s.end_s * fs)))
                    clip = samples[a:b]
                    name = f"{stem}_s{s.sid:03d}_{s.grade}_{s.defect}"
                    wav = save_clip(
                        clip, fs, rec_dir / f"{name}.wav",
                        metadata={
                            "source": "video",
                            "source_file": str(path),
                            "start_s": round(s.start_s, 4),
                            "end_s": round(s.end_s, 4),
                            "grade": s.grade,
                            "defect": s.defect,
                        },
                    )
                    features = extract_features(clip, fs, cfg)
                    # Provenance for the clip row, so a suspicious feature can
                    # be traced back to the exact moment in the exact video.
                    notes = (f"from {path.name} "
                             f"[{s.start_s:.3f}-{s.end_s:.3f}s]"
                             f"{'; ' + s.notes if s.notes else ''}")
                    prepared.append({
                        "sid": s.sid, "wav": str(wav), "features": features,
                        "notes": notes, "duration_s": len(clip) / fs,
                        "grade": s.grade, "defect": s.defect,
                    })
                except Exception as exc:  # noqa: BLE001 - one bad snippet must
                    failed.append((s.sid, str(exc)))   # not abandon the rest
            self._work.put(("saved", prepared, failed, fs, None, None))

        threading.Thread(target=work, daemon=True, name="slice-save").start()

    def _on_saved(self, prepared, failed, fs) -> None:
        self._busy = False
        db = self.ctx.db
        sid = self.ctx.ensure_session()

        done = []
        for item in prepared:
            try:
                cid = db.add_clip(sid, item["wav"], "video", fs,
                                  item["duration_s"], notes=item["notes"])
                db.set_features(cid, item["features"])
                db.set_label(cid, item["defect"], grader="slice",
                             grade_tier=item["grade"])
                done.append((item["sid"], item["features"].get("status", "")))
            except Exception as exc:  # noqa: BLE001
                failed.append((item["sid"], str(exc)))

        saved_sids = {s for s, _ in done}
        for s in self._set.segments:
            if s.sid in saved_sids:
                s.saved = True
        self._save_sidecar()

        retest = sum(1 for _, status in done if status and status != "OK")
        msg = f"saved {len(done)} snippet(s) to the dataset"
        if retest:
            # Worth saying loudly: these rows exist but the analysis flagged
            # them, usually too little pre-roll or too low an SNR.
            msg += f" - {retest} came back flagged (check the Dataset screen)"
        if failed:
            msg += f"; {len(failed)} failed: " + "; ".join(f"#{s}: {e}" for s, e in failed[:3])
        self._set_status(msg)
        self._refresh_all()

    def send_to_analyze(self) -> None:
        """Load the selected snippet as a clip, so the full analysis screens
        can be pointed at one suspicious tap without saving it first."""
        seg_ = self._first_selected_segment()
        if seg_ is None or self._samples is None:
            self._set_status("select a snippet row first")
            return
        a = max(0, int(round(seg_.start_s * self._fs)))
        b = min(self._samples.size, int(round(seg_.end_s * self._fs)))
        idx = self.ctx.state.add_clip(ClipData(
            name=f"{self._path.stem}-s{seg_.sid:03d}",
            samples=self._samples[a:b].copy(), fs=self._fs, source="video",
            path=str(self._path),
            metadata={"start_s": seg_.start_s, "end_s": seg_.end_s},
        ))
        self.ctx.service.submit(idx)
        if self.ctx.navigate:
            self.ctx.navigate("Analyze")

    def _cache_dir(self) -> Path:
        """Where decoded video audio is kept (config ``video.cache_dir``).

        A relative value is anchored under ``paths.data_dir`` rather than the
        repo root, so redirecting the data directory - a preset, or a test -
        takes the cache along instead of scattering decoded WAVs into the
        real ``data/``.
        """
        raw = Path(self._vcfg.get("cache_dir", "cache"))
        if raw.is_absolute():
            return raw
        return resolve_path(self.ctx.state.cfg, "data_dir") / raw

    def _save_sidecar(self) -> None:
        if self._path is None:
            return
        self._set.segments = segmod.renumber(self._set.segments)
        try:
            snippets.save_snippets(self._path, self._set)
        except OSError as exc:
            self._set_status(f"could not write the sidecar: {exc}")

    # -- events ------------------------------------------------------------
    def _on_overview_click(self, event) -> None:
        if event.xdata is not None and self._samples is not None:
            self._goto(float(event.xdata))

    def _on_scrub(self, _value) -> None:
        if self._samples is None or self._player is not None:
            return
        self._playhead = float(self.position.get())
        if not (self._view_start <= self._playhead <= self._view_start + self._view_span):
            self._view_start = max(0.0, self._playhead - self._view_span * 0.5)
            self._redraw_detail()
        self._move_playhead_lines()
        self._update_time_label()
        self._request_frame()

    def _on_zoom(self, _event=None) -> None:
        self._view_span = float(self.zoom.get().rstrip("s"))
        self._view_start = max(0.0, self._playhead - self._view_span * 0.3)
        self._redraw_detail()
        self._redraw_overview()

    def _on_row_select(self, _event=None) -> None:
        seg_ = self._first_selected_segment()
        if seg_ is None:
            return
        self._selection = (seg_.start_s, seg_.end_s)
        if seg_.grade:
            self.grade.set(seg_.grade)
        if seg_.defect:
            self.defect.set(seg_.defect)
        self._goto(seg_.start_s)

    # -- frame preview -----------------------------------------------------
    def _request_frame(self) -> None:
        """Debounced: dragging the scrub bar fires a stream of positions and
        one ffmpeg call per pixel would fall hopelessly behind."""
        if not self._has_video or not self._vcfg.get("frame_preview", True):
            return
        if self._frame_job is not None:
            self.after_cancel(self._frame_job)
        self._frame_job = self.after(_FRAME_DEBOUNCE_MS, self._fetch_frame)

    def _fetch_frame(self) -> None:
        self._frame_job = None
        path, t = self._path, self._playhead
        width = int(self._vcfg.get("frame_width_px", 420))

        def work():
            png = videoaudio.extract_frame_png(path, t, width)
            self._work.put(("frame", png, t, None, None, None))

        threading.Thread(target=work, daemon=True, name="slice-frame").start()

    def _on_frame(self, png: bytes | None, t: float) -> None:
        if not png:
            return
        try:
            self._frame_image = tk.PhotoImage(data=png)
        except tk.TclError:
            return  # Tk without PNG support; the rest of the screen still works
        self.frame_lbl.configure(image=self._frame_image, text="")

    # -- refresh -----------------------------------------------------------
    def _poll_work(self) -> None:
        try:
            while True:
                kind, a, b, c, d, e = self._work.get_nowait()
                if kind == "loaded":
                    self._on_loaded(a, b, c, d, e)
                elif kind == "saved":
                    self._on_saved(a, b, c)
                elif kind == "frame":
                    self._on_frame(a, b)
        except queue.Empty:
            pass
        self.after(200, self._poll_work)

    def refresh(self) -> None:
        """Called by the main window on every state change. Cheap by design -
        the plots are only rebuilt when this screen's own data changed."""
        self._update_summary()

    def _refresh_all(self) -> None:
        self._redraw_overview()
        self._redraw_detail()
        self._refresh_table()
        self._update_summary()

    def _redraw_overview(self) -> None:
        if self._env is None:
            self.p_overview.clear()
            return
        mins, maxs = self._env
        self.p_overview.draw_with(
            plots.draw_take_overview, mins, maxs, self._duration,
            segments=self._set.segments, playhead_s=self._playhead,
            view=(self._view_start, self._view_start + self._view_span),
        )
        self._overview_line = self._playhead_line(self.p_overview)

    def _redraw_detail(self) -> None:
        if self._samples is None:
            self.p_detail.clear()
            return
        start = max(0.0, min(self._view_start, max(0.0, self._duration - self._view_span)))
        self._view_start = start
        a = int(start * self._fs)
        b = min(self._samples.size, int((start + self._view_span) * self._fs))
        view = (start, start + self._view_span)

        self.p_detail.draw_with(
            plots.draw_take_detail, self._samples[a:b], self._fs, start,
            segments=[s for s in self._set.segments
                      if s.end_s > view[0] and s.start_s < view[1]],
            onsets=[o for o in self._onsets if view[0] <= o <= view[1]],
            playhead_s=self._playhead,
            selection=self._selection,
        )
        self._detail_line = self._playhead_line(self.p_detail)
        self._attach_span_selector()

    def _playhead_line(self, panel):
        """Keep a handle on the playhead so it can be moved without redrawing
        the waveform underneath it."""
        axes = panel.figure.axes
        if not axes:
            return None
        return axes[0].axvline(self._playhead, color="#ededf1", lw=1.0)

    def _move_playhead_lines(self) -> None:
        for line in (self._detail_line, self._overview_line):
            if line is not None:
                line.set_xdata([self._playhead, self._playhead])
        self.p_detail.canvas.draw_idle()
        self.p_overview.canvas.draw_idle()

    def _attach_span_selector(self) -> None:
        """Recreated after every redraw: draw_with() clears the figure, which
        takes the old selector's axes with it."""
        from matplotlib.widgets import SpanSelector

        axes = self.p_detail.figure.axes
        if not axes:
            self._span_selector = None
            return
        self._span_selector = SpanSelector(
            axes[0], self._on_span, "horizontal", useblit=True,
            props={"alpha": 0.25, "facecolor": "#4aa8ff"},
            interactive=True, drag_from_anywhere=True,
        )

    def _refresh_table(self) -> None:
        selected = set(self._selected_sids())
        self.tree.delete(*self.tree.get_children())
        for s in self._set.segments:
            self.tree.insert(
                "", "end", iid=str(s.sid),
                values=(s.sid, f"{s.start_s:.3f}", f"{s.duration_s * 1000:.0f} ms",
                        s.grade or "-", s.defect or "-", "yes" if s.saved else ""),
            )
        for sid in selected:
            if self.tree.exists(str(sid)):
                self.tree.selection_add(str(sid))

    def _update_summary(self) -> None:
        info = segmod.summary(self._set.segments)
        if not info["total"]:
            self.summary_lbl.set("no snippets yet")
            return
        grades = ", ".join(f"{k}:{v}" for k, v in sorted(info["by_grade"].items())) or "-"
        defects = ", ".join(f"{k}:{v}" for k, v in sorted(info["by_defect"].items())) or "-"
        self.summary_lbl.set(
            f"{info['total']} snippet(s) - {info['labelled']} labelled, "
            f"{info['saved']} saved\ngrades  {grades}\ndefects {defects}"
        )

    def _sync_position(self) -> None:
        self.position.set(self._playhead)
        self._update_time_label()

    def _update_time_label(self) -> None:
        self.time_lbl.set(f"{self._playhead:.3f} / {self._duration:.3f} s")

    def _set_status(self, text: str) -> None:
        self.status.set(text)

    # -- helpers -----------------------------------------------------------
    def _selected_sids(self) -> list[int]:
        return [int(iid) for iid in self.tree.selection()]

    def _first_selected_segment(self) -> Segment | None:
        sids = self._selected_sids()
        if not sids:
            return None
        return next((s for s in self._set.segments if s.sid == sids[0]), None)

    def soft_keys(self):
        return [
            ("Open video", self.open_media),
            ("Find strikes", self.find_strikes),
            ("Add selection", self.add_selection),
            ("Save to dataset", self.save_to_dataset),
        ]
