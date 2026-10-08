"""Collect screen: set up, listen, review - one guided flow for gathering tap data.

    1 Setup   record the rig's own sound (motor, striker with no tile)
    2 Listen  sound-triggered capture; each strike is cleaned and filed
    3 Review  look at before/after, press one key to label, move on

Thin on purpose: triggering is ``dsp/trigger``, cleaning is ``dsp/machine_noise``,
filing is ``io/session``, the microphone is ``io/recorder.SessionRecorder``.
Audio callbacks only drop things on a queue; the Tk thread does the rest.
"""

from __future__ import annotations

import math
import queue
import threading
import tkinter as tk
from tkinter import ttk

import numpy as np

from ..config import resolve_path
from ..dsp.machine_noise import build_striker_template
from ..features import extract_features
from ..io import audio_out
from ..io.library import LibraryError
from ..io.machine_profile import MachineProfile, load_profile, save_profile
from ..io.session import REJECTED, SessionStore, new_session_folder
from ..io.wavstore import load_clip
from .screens import _Base
from .screens_live import _devices
from .theme import ACCENT, BAD, FG, FG_DIM, FG_MUTE, INPUT, LINE, OK, PANEL, WARN, mono_font, ui_font
from .widgets import MplPanel

_STEPS = ("1  Setup", "2  Listen", "3  Review")
_LABEL_KEYS = {"g": "good", "c": "cracked", "b": "corner_broken", "o": "other_defect"}
_DB_FLOOR, _DB_CEIL = -70.0, 0.0
_STATE_TEXT = {
    "warming up": ("Getting ready... stay quiet for a moment", FG_DIM),
    "listening": ("Listening - strike a tile", OK),
    "capturing": ("Sound heard - recording...", WARN),
    "cooldown": ("Captured - settling...", ACCENT),
}


def _db(x: float) -> float:
    return 20.0 * math.log10(max(x, 1e-9))


class LevelMeter(tk.Canvas):
    """Horizontal level bar on a dB scale with the trigger threshold as a marker."""

    def __init__(self, master, height=34):
        super().__init__(master, height=height, bg=INPUT, highlightthickness=1,
                         highlightbackground=LINE)
        self._level = _DB_FLOOR
        self._thr = _DB_FLOOR
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, level: float, threshold: float | None = None) -> None:
        self._level = _db(level)
        if threshold is not None:
            self._thr = _db(threshold)
        self._draw()

    def _x(self, db: float) -> float:
        frac = (min(max(db, _DB_FLOOR), _DB_CEIL) - _DB_FLOOR) / (_DB_CEIL - _DB_FLOOR)
        return frac * max(self.winfo_width(), 1)

    def _draw(self) -> None:
        self.delete("all")
        h = int(self["height"])
        over = self._level >= self._thr
        self.create_rectangle(0, 0, self._x(self._level), h, fill=WARN if over else OK, width=0)
        tx = self._x(self._thr)
        self.create_line(tx, 0, tx, h, fill=BAD, width=3)
        self.create_text(tx + 6, 9, text="trigger", fill=FG, anchor="w", font=ui_font(8))
        self.create_text(self.winfo_width() - 6, h - 9, text=f"{self._level:.0f} dB",
                         fill=FG, anchor="e", font=mono_font(9))


class CollectScreen(_Base):
    title = "Collect"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self.cfg = ctx.state.cfg
        self.lib = ctx.library
        self.q: queue.Queue = queue.Queue()
        self.rec = None
        self.mode = "idle"              # idle | dry | listen
        self._dry: list[np.ndarray] = []
        self._live = (0.0, 1e-4, "warming up")
        self.store: SessionStore | None = None
        self._db_ids: dict[str, int] = {}
        self._review_rows: dict[str, object] = {}
        self._page = 0

        self._profile_path = resolve_path(self.cfg, "data_dir") / "machine_profile.npz"
        self.profile = load_profile(self._profile_path) or MachineProfile(int(self.cfg["audio"]["sample_rate"]))
        if self.profile.fs != int(self.cfg["audio"]["sample_rate"]):
            self.profile = MachineProfile(int(self.cfg["audio"]["sample_rate"]))

        # step bar
        steps = ttk.Frame(self)
        steps.pack(fill="x", pady=(0, 10))
        self._chips = []
        for i, text in enumerate(_STEPS):
            b = ttk.Button(steps, text=text, command=lambda i=i: self._show_page(i))
            b.pack(side="left", padx=(0, 6))
            self._chips.append(b)

        self._pages = [ttk.Frame(self) for _ in _STEPS]
        self._build_setup(self._pages[0])
        self._build_listen(self._pages[1])
        self._build_review(self._pages[2])

        self.status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status, style="Dim.TLabel").pack(side="bottom", anchor="w", pady=(6, 0))
        self._show_page(0)
        self.after(50, self._pump)

    # ------------------------------------------------------------------
    # page 1 - setup
    # ------------------------------------------------------------------
    def _build_setup(self, page):
        ttk.Label(page, text="Teach the app what your machine sounds like", font=ui_font(14, "bold")).pack(anchor="w")
        ttk.Label(page, text="Two short recordings, once per setup. The app subtracts these from every tap "
                  "so only the tile's ring is left. You can skip this and still collect.",
                  style="Dim.TLabel", wraplength=900).pack(anchor="w", pady=(2, 12))

        row = ttk.Frame(page)
        row.pack(fill="x", pady=(0, 10))
        ttk.Label(row, text="Microphone").pack(side="left")
        self.device = ttk.Combobox(row, width=46, state="readonly")
        self.device.pack(side="left", padx=8)

        cards = ttk.Frame(page)
        cards.pack(fill="x")
        cards.columnconfigure((0, 1), weight=1, uniform="c")

        m = ttk.Frame(cards, style="Card.TFrame", padding=14)
        m.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        ttk.Label(m, text="A   MOTOR ONLY", style="CardH.TLabel").pack(anchor="w")
        ttk.Label(m, text=f"Run the motor. Do NOT fire the striker.\nRecords {self.cfg['machine']['motor_seconds']} s.",
                  style="Card.TLabel").pack(anchor="w", pady=8)
        self.motor_btn = ttk.Button(m, text="Record motor noise", style="Accent.TButton", command=self._record_motor)
        self.motor_btn.pack(anchor="w")
        self.motor_state = ttk.Label(m, text="", style="Card.TLabel", font=ui_font(10, "bold"))
        self.motor_state.pack(anchor="w", pady=(10, 0))

        s = ttk.Frame(cards, style="Card.TFrame", padding=14)
        s.grid(row=0, column=1, sticky="nsew")
        ttk.Label(s, text="B   STRIKER, NO TILE", style="CardH.TLabel").pack(anchor="w")
        ttk.Label(s, text=f"Motor on, striker firing, nothing under it.\nStrikes are counted automatically "
                  f"(want {self.cfg['machine']['dry_strikes_target']}).", style="Card.TLabel").pack(anchor="w", pady=8)
        brow = ttk.Frame(s, style="Card.TFrame")
        brow.pack(anchor="w")
        self.dry_btn = ttk.Button(brow, text="Start dry strikes", style="Accent.TButton", command=self._toggle_dry)
        self.dry_btn.pack(side="left")
        self.dry_done = ttk.Button(brow, text="Use these now", command=self._finish_dry)
        self.dry_done.pack(side="left", padx=6)
        self.dry_meter = LevelMeter(s)
        self.dry_meter.pack(fill="x", pady=(10, 4))
        self.dry_state = ttk.Label(s, text="", style="Card.TLabel", font=ui_font(10, "bold"))
        self.dry_state.pack(anchor="w")

        nav = ttk.Frame(page)
        nav.pack(fill="x", pady=(16, 0))
        ttk.Button(nav, text="Next: Listen  →", style="Accent.TButton", command=lambda: self._show_page(1)).pack(side="right")
        ttk.Button(nav, text="Forget machine profile", command=self._forget_profile).pack(side="left")

    def _devs(self):
        devs = _devices()
        if devs is None:
            self.device["values"] = ["(PortAudio unavailable)"]
            self.device.current(0)
            for b in (self.motor_btn, self.dry_btn):
                b.state(["disabled"])
            return
        self.device["values"] = [f"{d['index']}: {d['name']}" for d in devs]
        if devs and not self.device.get():
            want = self.cfg["audio"].get("device")
            idx = next((i for i, d in enumerate(devs) if d["index"] == want), 0)
            self.device.current(idx)

    def _device_index(self):
        t = self.device.get()
        return int(t.split(":")[0]) if t[:1].isdigit() else None

    def _new_recorder(self, on_clip):
        from ..io.recorder import SessionRecorder

        return SessionRecorder(self.cfg, on_clip=on_clip, on_level=self._on_level,
                               device=self._device_index())

    def _on_level(self, level, threshold, state):           # audio thread
        self._live = (level, threshold, state)

    def _record_motor(self):
        self.motor_btn.state(["disabled"])
        self.motor_state.configure(text="recording... keep the striker still", foreground=WARN)
        secs = float(self.cfg["machine"]["motor_seconds"])

        def work():
            try:
                rec = self._new_recorder(lambda *_: None)
                x = rec.record_seconds(secs)
                self.q.put(("motor_done", x))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _toggle_dry(self):
        if self.mode == "dry":
            self._stop_recorder()
            self.dry_btn.configure(text="Start dry strikes")
            self.mode = "idle"
            return
        self._dry = []
        self._start_recorder("dry", lambda clip, fs: self.q.put(("dry_clip", clip)))
        self.dry_btn.configure(text="Stop")
        self._update_dry_text()

    def _finish_dry(self):
        self._stop_recorder()
        self.mode = "idle"
        self.dry_btn.configure(text="Start dry strikes")
        fs = self.profile.fs
        try:
            tpl = build_striker_template(self._dry, fs, self.cfg)
        except ValueError as exc:
            self.dry_state.configure(text=str(exc), foreground=BAD)
            return
        self.profile.template = tpl
        save_profile(self.profile, self._profile_path)
        self._refresh_setup_state()

    def _forget_profile(self):
        self.profile = MachineProfile(self.profile.fs)
        try:
            self._profile_path.unlink()
        except OSError:
            pass
        self._refresh_setup_state()

    def _update_dry_text(self):
        target = int(self.cfg["machine"]["dry_strikes_target"])
        self.dry_state.configure(text=f"{len(self._dry)} / {target} strikes heard", foreground=FG)

    def _refresh_setup_state(self):
        if self.profile.motor_noise is not None:
            self.motor_state.configure(text="● recorded", foreground=OK)
        else:
            self.motor_state.configure(text="○ not recorded (optional)", foreground=FG_MUTE)
        t = self.profile.template
        if t is None:
            if self.mode != "dry":
                self.dry_state.configure(text="○ not recorded (optional)", foreground=FG_MUTE)
        else:
            good = t.repeatability >= float(self.cfg["machine"]["min_repeatability"])
            msg = (f"● template from {t.n_used} strikes - repeatability {t.repeatability:.0%}"
                   + ("" if good else "\n  Low: strikes differ too much. Check the striker is fixed "
                      "firmly and the ball lands the same way, then redo."))
            self.dry_state.configure(text=msg, foreground=OK if good else WARN)
        self.motor_btn.configure(text="Record again" if self.profile.motor_noise is not None else "Record motor noise")

    # ------------------------------------------------------------------
    # page 2 - listen
    # ------------------------------------------------------------------
    def _build_listen(self, page):
        self.big_state = ttk.Label(page, text="Press Start, then strike a tile", font=ui_font(20, "bold"))
        self.big_state.pack(anchor="w", pady=(4, 8))
        self.meter = LevelMeter(page, height=44)
        self.meter.pack(fill="x")

        ctl = ttk.Frame(page)
        ctl.pack(fill="x", pady=12)
        self.listen_btn = ttk.Button(ctl, text="▶  Start listening   (Space)", style="Accent.TButton",
                                     command=self._toggle_listen)
        self.listen_btn.pack(side="left")
        ttk.Label(ctl, text="Sensitivity").pack(side="left", padx=(24, 6))
        self.sens = tk.DoubleVar(value=8)
        ttk.Scale(ctl, from_=1, to=10, variable=self.sens, length=200,
                  command=lambda _v: self._apply_sens()).pack(side="left")
        ttk.Label(ctl, text="higher = reacts to quieter sounds", style="Dim.TLabel").pack(side="left", padx=8)

        sess = ttk.Frame(page)
        sess.pack(fill="x", pady=(2, 10))
        ttk.Label(sess, text="Saving into:").pack(side="left")
        self.folder_lbl = ttk.Label(sess, text="(starts with the first capture)", font=mono_font(10))
        self.folder_lbl.pack(side="left", padx=8)
        ttk.Button(sess, text="New session folder", command=self._new_session).pack(side="left")

        cards = ttk.Frame(page)
        cards.pack(fill="x")
        cards.columnconfigure((0, 1, 2), weight=1, uniform="k")
        self.cnt = {}
        for i, (key, title, colour) in enumerate((("tile", "TILE TAPS KEPT", OK),
                                                   ("rej", "REJECTED (NO TILE / NOISE)", WARN),
                                                   ("all", "CAPTURED", FG))):
            c = ttk.Frame(cards, style="Card.TFrame", padding=12)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            ttk.Label(c, text=title, style="CardH.TLabel").pack(anchor="w")
            lab = ttk.Label(c, text="0", style="Big.TLabel")
            lab.configure(foreground=colour)
            lab.pack(anchor="w")
            self.cnt[key] = lab
        self.last = ttk.Label(page, text="", style="Dim.TLabel", wraplength=900)
        self.last.pack(anchor="w", pady=(10, 0))
        nav = ttk.Frame(page)
        nav.pack(fill="x", pady=(14, 0))
        ttk.Button(nav, text="Review clips  →", style="Accent.TButton", command=lambda: self._show_page(2)).pack(side="right")

    def _apply_sens(self):
        mult = 2.0 + (10.0 - self.sens.get()) * 2.0
        self.cfg["capture"]["floor_mult"] = mult
        if self.rec is not None:
            self.rec.set_sensitivity(mult)

    def _new_session(self):
        folder = new_session_folder(self.lib)
        self.store = SessionStore(self.lib, folder, self.cfg, self.profile)
        self._review_rows.clear()
        self.folder_lbl.configure(text=str(self.lib.relative(folder)))
        self._update_counts()

    def _toggle_listen(self):
        if self.mode == "listen":
            self._stop_recorder()
            self.mode = "idle"
            self.listen_btn.configure(text="▶  Start listening   (Space)")
            self.big_state.configure(text="Stopped", foreground=FG_DIM)
            return
        if self.store is None:
            self._new_session()
        self.store.profile = self.profile
        self._apply_sens()
        self._start_recorder("listen", lambda clip, fs: self.q.put(("clip", (clip, fs))))
        self.listen_btn.configure(text="■  Stop   (Space)")

    def _update_counts(self):
        c = self.store.counts() if self.store else {"total": 0, "tile": 0, "no_tile": 0, "no_strike": 0}
        self.cnt["tile"].configure(text=str(c["tile"]))
        self.cnt["rej"].configure(text=str(c["no_tile"] + c["no_strike"]))
        self.cnt["all"].configure(text=str(c["total"]))

    # ------------------------------------------------------------------
    # page 3 - review
    # ------------------------------------------------------------------
    def _build_review(self, page):
        page.columnconfigure(1, weight=1)
        page.rowconfigure(0, weight=1)
        left = ttk.Frame(page)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        self.tree = ttk.Treeview(left, columns=("v", "snr", "lab"), show="tree headings", height=16, selectmode="browse")
        self.tree.heading("#0", text="clip")
        self.tree.column("#0", width=110)
        for col, w, t in (("v", 80, "result"), ("snr", 60, "SNR dB"), ("lab", 100, "label")):
            self.tree.heading(col, text=t)
            self.tree.column(col, width=w, anchor="center")
        self.tree.tag_configure("tile", foreground=OK)
        self.tree.tag_configure("no_tile", foreground=WARN)
        self.tree.tag_configure("no_strike", foreground=FG_MUTE)
        self.tree.pack(fill="y", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._draw_review())
        for k, lab in _LABEL_KEYS.items():
            self.tree.bind(f"<KeyPress-{k}>", lambda _e, lab=lab: self._label(lab))
        self.tree.bind("<KeyPress-n>", lambda _e: self._discard())
        self.tree.bind("<space>", lambda _e: self._play())

        right = ttk.Frame(page)
        right.grid(row=0, column=1, sticky="nsew")
        self.plot = MplPanel(right, figsize=(6.0, 3.2))
        self.plot.pack(fill="both", expand=True)
        self.review_msg = ttk.Label(right, text="", style="Dim.TLabel", wraplength=640)
        self.review_msg.pack(anchor="w", pady=4)
        btns = ttk.Frame(right)
        btns.pack(fill="x")
        for text, key, lab in (("Good", "G", "good"), ("Cracked", "C", "cracked"),
                               ("Corner broken", "B", "corner_broken"), ("Other defect", "O", "other_defect")):
            ttk.Button(btns, text=f"{text}  {key}", command=lambda lab=lab: self._label(lab)).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Not a tap  N", style="Danger.TButton", command=self._discard).pack(side="left", padx=(12, 6))
        ttk.Button(btns, text="▶ Play  Space", command=self._play).pack(side="right")

    def _populate_review(self):
        self.tree.delete(*self.tree.get_children())
        self._review_rows = {}
        if not self.store:
            return
        for c in self.store.clips:
            self._review_rows[c.name] = c
            snr = "-" if c.residual_snr_db is None else f"{c.residual_snr_db:.0f}"
            self.tree.insert("", "end", iid=c.name, text=c.name, tags=(c.verdict,),
                             values=({"tile": "tile", "no_tile": "no tile", "no_strike": "no strike"}[c.verdict], snr, ""))
        kids = self.tree.get_children()
        if kids:
            self.tree.selection_set(kids[0])
            self.tree.focus(kids[0])
            self.tree.focus_set()

    def _current(self):
        sel = self.tree.selection()
        return self._review_rows.get(sel[0]) if sel else None

    def _draw_review(self):
        c = self._current()
        if c is None:
            self.plot.clear()
            return
        raw, fs, _ = load_clip(c.raw_path)
        clean, _, _ = load_clip(c.path)
        t = np.arange(raw.size) / fs

        def draw(ax):
            ax.plot(t, raw, lw=0.6, color=FG_MUTE, label="as recorded")
            ax.plot(t, clean, lw=0.7, color=OK if c.accepted else WARN, label="machine removed")
            ax.set_xlabel("time (s)")
            ax.set_title(f"{c.name}  -  {c.verdict.replace('_', ' ')}")
            ax.legend(loc="upper right")
        self.plot.draw_with(draw)
        why = {"tile": "A tile is ringing after the strike. Label it below.",
               "no_tile": "Nothing but the machine is left after cleaning - probably no tile under the striker.",
               "no_strike": "No strike found in this recording - probably noise."}[c.verdict]
        self.review_msg.configure(text=why)

    def _label(self, label: str):
        c = self._current()
        if c is None:
            return
        cid = self._db_ids.get(str(c.path))
        samples, fs, _ = load_clip(c.path)
        db = self.ctx.db
        if cid is None:
            cid = db.add_clip(self.ctx.ensure_session(), str(c.path), "recorded", fs, len(samples) / fs)
            self._db_ids[str(c.path)] = cid
            db.set_features(cid, extract_features(samples, fs, self.cfg))
        db.set_label(cid, label, grader="collect")
        self.tree.set(c.name, "lab", label)
        self.status.set(f"{c.name} labelled {label.replace('_', ' ')}")
        self._advance()

    def _discard(self):
        c = self._current()
        if c is None:
            return
        try:
            if c.path.parent.name != REJECTED:
                dest = self.lib.resolve(c.path.parent) / REJECTED
                dest.mkdir(exist_ok=True)
                c.path = self.lib.move(c.path, dest)
        except LibraryError as exc:
            self.status.set(f"Not moved: {exc}")
            return
        self.tree.set(c.name, "lab", "not a tap")
        self.status.set(f"{c.name} moved to rejected")
        self._advance()

    def _advance(self):
        kids = self.tree.get_children()
        cur = self.tree.selection()[0]
        i = kids.index(cur)
        if i + 1 < len(kids):
            self.tree.selection_set(kids[i + 1])
            self.tree.focus(kids[i + 1])
            self.tree.see(kids[i + 1])

    def _play(self):
        c = self._current()
        if c is not None and audio_out.is_available():
            x, fs, _ = load_clip(c.path)
            audio_out.play(x, fs)

    # ------------------------------------------------------------------
    # shared plumbing
    # ------------------------------------------------------------------
    def _show_page(self, i: int):
        self._page = i
        for p in self._pages:
            p.pack_forget()
        self._pages[i].pack(fill="both", expand=True)
        for j, b in enumerate(self._chips):
            b.configure(style="Accent.TButton" if j == i else "TButton")
        if i == 2:
            self._populate_review()
        elif i == 1:
            self.listen_btn.focus_set()          # Space presses it
        self.refresh()

    def refresh(self):
        if not self.device["values"]:
            self._devs()
        self._refresh_setup_state()
        self._update_counts()

    def soft_keys(self):
        return [("Setup", lambda: self._show_page(0)), ("Listen", lambda: self._show_page(1)),
                ("Review", lambda: self._show_page(2))]

    def _start_recorder(self, mode, on_clip):
        try:
            self.rec = self._new_recorder(on_clip)
            self.rec.start()
        except Exception as exc:  # noqa: BLE001
            self.rec = None
            self.status.set(f"Could not open the microphone: {exc}")
            return
        self.mode = mode
        self.status.set("")

    def _stop_recorder(self):
        if self.rec is not None:
            try:
                self.rec.stop()
            finally:
                self.rec = None

    def shutdown(self):
        self._stop_recorder()

    def _pump(self):
        level, thr, state = self._live
        if self.mode in ("dry", "listen"):
            meter = self.meter if self.mode == "listen" else self.dry_meter
            meter.set(level, thr)
            if self.mode == "listen":
                text, colour = _STATE_TEXT.get(state, (state, FG))
                self.big_state.configure(text=text, foreground=colour)
        try:
            while True:
                kind, payload = self.q.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.after(50, self._pump)

    def _handle(self, kind, payload):
        if kind == "error":
            self.status.set(f"Recording failed: {payload}")
            self.motor_btn.state(["!disabled"])
        elif kind == "motor_done":
            self.profile.motor_noise = payload
            save_profile(self.profile, self._profile_path)
            self.motor_btn.state(["!disabled"])
            self._refresh_setup_state()
        elif kind == "dry_clip":
            self._dry.append(payload)
            self._update_dry_text()
            if len(self._dry) >= int(self.cfg["machine"]["dry_strikes_target"]):
                self._finish_dry()
        elif kind == "clip":
            clip, fs = payload
            if self.store is None:
                return
            saved = self.store.handle(clip, fs)
            self._update_counts()
            mark = "kept" if saved.accepted else "rejected: " + saved.verdict.replace("_", " ")
            self.last.configure(text=f"{saved.name}  →  {mark}")
