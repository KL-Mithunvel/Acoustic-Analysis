"""The main window: the instrument shell (status bar, left sidebar nav, right
action rail, bottom soft-key bar) wrapped around one visible screen at a time,
plus the periodic poll that pulls finished analysis off the worker and refreshes
the current screen.
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..config import load_config, resolve_path
from ..io import audio_out
from ..io.dataset import Dataset
from ..io.wavstore import load_clip
from .explain import Explainer
from .screens import (
    AnalyzeScreen,
    CompareScreen,
    DatasetScreen,
    FiltersScreen,
    LabelScreen,
    LearnScreen,
    NoiseScreen,
)
from .screens_live import CalibrateScreen, MonitorScreen, RecordScreen, SettingsScreen
from .service import AnalysisService
from .state import ClipData, SharedState
from .theme import ACCENT, FG_MUTE, LINE, OK, SIDEBAR, apply_theme, ui_font
from .widgets import MplPanel, NavItem, RailButton, show_explanation

_POLL_MS = 200

# Sidebar groups, top to bottom. HomeScreen is prepended once it exists.
_NAV_GROUPS: list[tuple[str, list]] = [
    ("LIVE", [MonitorScreen, RecordScreen, CalibrateScreen]),
    ("ANALYZE", [AnalyzeScreen, CompareScreen, FiltersScreen, NoiseScreen]),
    ("DATA", [LabelScreen, DatasetScreen]),
    ("HELP", [LearnScreen, SettingsScreen]),
]


@dataclass
class AppContext:
    root: tk.Misc
    state: SharedState
    service: AnalysisService
    explainer: Explainer
    db: Dataset
    _session_id: int | None = None

    def ensure_session(self) -> int:
        if self._session_id is None:
            self._session_id = self.db.create_session("default")
        return self._session_id


class MainWindow(tk.Tk):
    def __init__(self, cfg: dict | None = None):
        super().__init__()
        self.title("Acoustic-Analysis")
        self.minsize(1180, 720)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1400, sw - 24), min(860, sh - 80)
        self.geometry(f"{w}x{h}+8+8")
        apply_theme(self)

        cfg = cfg or load_config()
        state = SharedState(cfg)
        db_path = resolve_path(cfg, "database")
        self.ctx = AppContext(
            root=self,
            state=state,
            service=AnalysisService(state),
            explainer=Explainer(),
            db=Dataset(db_path),
        )

        prof_path = resolve_path(cfg, "reference_profile")
        if prof_path.is_file():
            from ..classify.reference import ReferenceProfile

            try:
                state.profile = ReferenceProfile.load(prof_path)
            except Exception:  # noqa: BLE001
                pass

        self._current = 0
        self._history: list[int] = []

        self._build_menu()
        self._build_status_bar()   # status bar (top) + status message (bottom)
        self._build_soft_keys()    # soft-key bar (bottom) - pack fixed edges before the body

        body = ttk.Frame(self)
        self._build_sidebar(body)
        self._build_rail(body)
        self._content = ttk.Frame(body)
        self._content.pack(side="left", fill="both", expand=True)
        self._content.pack_propagate(False)
        self._content.bind("<Configure>", self._fit_content)
        body.pack(fill="both", expand=True)   # expanding centre packs last

        self.screens: list = []
        for cls in [c for _, group in _NAV_GROUPS for c in group]:
            self.screens.append(cls(self._content, self.ctx))

        state.add_listener(self._refresh_current)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(_POLL_MS, self._poll)
        self.after(1000, self._tick_clock)
        self._bind_shortcuts()
        self._show(0, record_history=False)

    # -- instrument frame ------------------------------------------
    def _build_status_bar(self):
        bar = ttk.Frame(self, style="Status.TFrame", padding=(14, 8))
        bar.pack(side="top", fill="x")
        self._screen_title = tk.StringVar(value="")
        dot = tk.Canvas(bar, width=10, height=10, bg=SIDEBAR, highlightthickness=0, bd=0)
        dot.create_oval(2, 2, 9, 9, fill=ACCENT, outline=ACCENT)
        dot.pack(side="left", padx=(0, 8))
        ttk.Label(bar, textvariable=self._screen_title, style="StatusTitle.TLabel").pack(side="left")

        self._src_var = tk.StringVar(value="src -")
        self._cal_var = tk.StringVar(value="uncal")
        self._clock_var = tk.StringVar(value="")
        self._rec_var = tk.StringVar(value="")
        self._cal_lbl = ttk.Label(bar, textvariable=self._cal_var, style="StatusMeta.TLabel")
        ttk.Label(bar, textvariable=self._rec_var, style="Rec.TLabel").pack(side="right", padx=(12, 0))
        ttk.Label(bar, textvariable=self._clock_var, style="StatusMeta.TLabel").pack(side="right", padx=(12, 0))
        self._cal_lbl.pack(side="right", padx=(12, 0))
        ttk.Label(bar, textvariable=self._src_var, style="StatusMeta.TLabel").pack(side="right", padx=(12, 0))

        self._status = tk.StringVar(value="ready")
        ttk.Label(self, textvariable=self._status, style="StatusMeta.TLabel", anchor="w",
                  padding=(14, 4)).pack(side="bottom", fill="x")

    def _build_sidebar(self, parent):
        rail = tk.Frame(parent, bg=SIDEBAR, width=178)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        tk.Frame(parent, bg=LINE, width=1).pack(side="left", fill="y")
        self._nav_items: list[NavItem] = []
        flat = 0
        for gi, (group, classes) in enumerate(_NAV_GROUPS):
            tk.Label(rail, text=group, bg=SIDEBAR, fg=FG_MUTE, anchor="w",
                     font=ui_font(8, "bold"), padx=16).pack(
                         fill="x", pady=(4 if gi == 0 else 14, 5))
            for _cls in classes:
                idx = flat
                item = NavItem(rail, _title_for(_cls), lambda i=idx: self._show(i))
                item.pack(fill="x")
                self._nav_items.append(item)
                flat += 1

    def _build_rail(self, parent):
        rail = tk.Frame(parent, bg=SIDEBAR, width=64)
        rail.pack(side="right", fill="y")
        rail.pack_propagate(False)
        tk.Frame(parent, bg=LINE, width=1).pack(side="right", fill="y")
        groups = [
            [("rec", "Rec", lambda: self._goto("Record"), True),
             ("play", "Play", self._rail_play, False),
             ("stop", "Stop", audio_out.stop, False)],
            [("open", "Open", self.open_files, False),
             ("save", "Save", self._rail_save, False),
             ("snap", "Snap", self._rail_snapshot, False)],
            [("prev", "Prev", lambda: self._step_clip(-1), False),
             ("next", "Next", lambda: self._step_clip(1), False)],
            [("back", "Back", self._go_back, False),
             ("home", "Home", lambda: self._goto("Home"), False)],
        ]
        for gi, group in enumerate(groups):
            if gi:
                tk.Frame(rail, bg=LINE, height=1, width=40).pack(pady=6)
            for glyph, label, cmd, danger in group:
                RailButton(rail, glyph, label, cmd, danger=danger).pack()

    def _build_soft_keys(self):
        self._soft = tk.Frame(self, bg="#0d0d11")
        self._soft.pack(side="bottom", fill="x")
        inner = ttk.Frame(self._soft, padding=(12, 7))
        inner.pack(fill="x")
        self._soft_btns = [ttk.Button(inner, text="", width=15, style="Soft.TButton") for _ in range(4)]
        for b in self._soft_btns:
            b.pack(side="left", padx=(0, 6))
        self._apply_btn = ttk.Button(inner, text="Apply", width=9, style="Accent.TButton")
        self._cancel_btn = ttk.Button(inner, text="Cancel", width=9, style="Ghost.TButton")
        self._apply_btn.pack(side="right")
        self._cancel_btn.pack(side="right", padx=(0, 6))

    def _update_soft_keys(self, screen):
        keys = getattr(screen, "soft_keys", lambda: [])()
        for i, btn in enumerate(self._soft_btns):
            if i < len(keys):
                label, cmd = keys[i]
                btn.configure(text=label, command=cmd, state="normal")
            else:
                btn.configure(text="", command=lambda: None, state="disabled")
        edit = getattr(screen, "edit_actions", lambda: None)()
        if edit:
            cancel, apply_ = edit
            self._cancel_btn.configure(command=cancel)
            self._apply_btn.configure(command=apply_)
            self._cancel_btn.pack(side="right", padx=(0, 6))
            self._apply_btn.pack(side="right")
        else:
            self._cancel_btn.pack_forget()
            self._apply_btn.pack_forget()

    def _tick_clock(self):
        self._clock_var.set(time.strftime("%H:%M"))
        clip = self.ctx.state.primary()
        self._src_var.set(f"src {clip.name}" if clip else "src -")
        calibrated = self.ctx.state.cfg.get("calibration", {}).get("enabled")
        self._cal_var.set("● CAL" if calibrated else "uncal")
        self._cal_lbl.configure(foreground=OK if calibrated else FG_MUTE)
        self.after(1000, self._tick_clock)

    def _fit_content(self, event):
        # Pin every screen to exactly the content area; with pack_propagate off
        # their inner grid/pack lays out within this and can never overflow.
        for s in getattr(self, "screens", []):
            s.configure(width=event.width, height=event.height)

    # -- navigation ----------------------------------------------
    def _show(self, index: int, record_history: bool = True):
        if not (0 <= index < len(self.screens)):
            return
        if record_history and index != self._current:
            self._history.append(self._current)
            del self._history[:-20]
        for s in self.screens:
            s.pack_forget()
        self.screens[index].pack(fill="both", expand=True)
        self._current = index
        for i, item in enumerate(self._nav_items):
            item.set_active(i == index)
        self._refresh_current()

    def _goto(self, title: str):
        for i, s in enumerate(self.screens):
            if s.title == title:
                self._show(i)
                return
        self._show(0)

    def _go_back(self):
        if self._history:
            self._show(self._history.pop(), record_history=False)

    def _step_clip(self, delta):
        clips = self.ctx.state.clips()
        if not clips:
            return
        cur = self.ctx.state.selection()
        i = (cur[0] if cur else 0) + delta
        self.ctx.state.select([i % len(clips)])

    # -- rail actions ------------------------------------------------
    def _rail_play(self):
        clip = self.ctx.state.primary()
        if clip is not None and audio_out.is_available():
            audio_out.play(clip.samples, clip.fs)

    def _rail_save(self):
        clip = self.ctx.state.primary()
        if clip is None:
            return
        path = filedialog.asksaveasfilename(defaultextension=".wav", initialfile=f"{clip.name}.wav")
        if path:
            from ..io.wavstore import save_clip

            save_clip(clip.samples, clip.fs, path, metadata={"source": clip.source})
            self._status.set(f"saved {path}")

    def _rail_snapshot(self):
        screen = self.screens[self._current]
        panel = next((w for w in _iter_widgets(screen) if isinstance(w, MplPanel)), None)
        if panel is None:
            self._status.set("no chart on this screen to snapshot")
            return
        path = filedialog.asksaveasfilename(defaultextension=".png")
        if path:
            panel.figure.savefig(path, dpi=140)
            self._status.set(f"saved {path}")

    # -- menu / shortcuts -------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open WAV...", accelerator="Ctrl+O", command=self.open_files)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Glossary", command=self._glossary)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

    def _bind_shortcuts(self):
        self.bind("<Control-o>", lambda _e: self.open_files())
        self.bind("<F5>", lambda _e: self.ctx.service.submit_selection())
        self.bind("<Escape>", lambda _e: self._go_back())
        self.bind("<Control-Prior>", lambda _e: self._show((self._current - 1) % len(self.screens)))
        self.bind("<Control-Next>", lambda _e: self._show((self._current + 1) % len(self.screens)))

    # -- actions ---------------------------------------------------
    def open_files(self):
        paths = filedialog.askopenfilenames(
            title="Open WAV file(s)", filetypes=[("WAV audio", "*.wav"), ("All files", "*.*")]
        )
        for p in paths:
            try:
                samples, fs, meta = load_clip(p)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Open", f"{p}\n{exc}")
                continue
            idx = self.ctx.state.add_clip(
                ClipData(name=Path(p).stem, samples=samples, fs=fs, source="file", path=p, metadata=meta)
            )
            self.ctx.service.submit(idx)
        if paths:
            self._status.set(f"loaded {len(paths)} file(s)")

    def _glossary(self):
        show_explanation(self, self.ctx.explainer, self.ctx.explainer.keys()[0])

    # -- loop ----------------------------------------------------
    def _poll(self):
        for item in self.ctx.service.poll():
            if item["error"]:
                self._status.set("analysis error - see console")
                print(item["error"])
            else:
                self._status.set(f"analysed clip #{item['index']}: {item['features'].get('status')}")
        self.after(_POLL_MS, self._poll)

    def _refresh_current(self):
        if not (0 <= self._current < len(self.screens)):
            return
        screen = self.screens[self._current]
        screen.refresh()
        self._screen_title.set(screen.title)
        self._update_soft_keys(screen)

    def _on_close(self):
        try:
            audio_out.stop()
            self.ctx.service.stop()
            self.ctx.db.close()
        finally:
            self.destroy()


def _title_for(cls) -> str:
    return getattr(cls, "title", cls.__name__)


def _iter_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _iter_widgets(child)


def run() -> int:
    MainWindow().mainloop()
    return 0
