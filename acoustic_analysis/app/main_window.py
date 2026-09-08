"""The main window: a menu, a status bar, and a notebook of screens, plus the
periodic poll that pulls finished analysis off the worker and refreshes the
current screen.
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
from .theme import apply_theme
from .widgets import MplPanel
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

_SCREENS = [
    AnalyzeScreen,
    CompareScreen,
    FiltersScreen,
    NoiseScreen,
    MonitorScreen,
    RecordScreen,
    LabelScreen,
    DatasetScreen,
    CalibrateScreen,
    LearnScreen,
    SettingsScreen,
]
from .state import ClipData, SharedState
from .widgets import show_explanation

_POLL_MS = 200


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
        self.geometry("1240x800")
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

        # load an existing reference profile if present
        prof_path = resolve_path(cfg, "reference_profile")
        if prof_path.is_file():
            from ..classify.reference import ReferenceProfile

            try:
                state.profile = ReferenceProfile.load(prof_path)
            except Exception:  # noqa: BLE001
                pass

        self._build_menu()
        self._build_status_bar()

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        content = ttk.Frame(body)
        content.pack(side="left", fill="both", expand=True)
        self.nb = ttk.Notebook(content)
        self.nb.pack(fill="both", expand=True)
        self.screens = []
        for cls in _SCREENS:
            screen = cls(self.nb, self.ctx)
            self.nb.add(screen, text=screen.title)
            self.screens.append(screen)
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._refresh_current())

        self._build_button_rail(body)
        self._build_soft_keys()

        state.add_listener(self._refresh_current)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(_POLL_MS, self._poll)
        self.after(1000, self._tick_clock)
        self._bind_shortcuts()
        self._refresh_current()

    # -- instrument frame ------------------------------------------
    def _build_status_bar(self):
        bar = ttk.Frame(self)
        bar.pack(side="top", fill="x")
        self._screen_title = tk.StringVar(value="")
        self._src_var = tk.StringVar(value="src: -")
        self._cal_var = tk.StringVar(value="uncal")
        self._clock_var = tk.StringVar(value="")
        self._rec_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self._screen_title, style="Status.TLabel").pack(side="left")
        ttk.Label(bar, textvariable=self._rec_var, style="Status.TLabel", foreground="#e2564d").pack(side="right")
        ttk.Label(bar, textvariable=self._clock_var, style="Status.TLabel").pack(side="right")
        ttk.Label(bar, textvariable=self._cal_var, style="Status.TLabel").pack(side="right")
        ttk.Label(bar, textvariable=self._src_var, style="Status.TLabel").pack(side="right")
        self._status = tk.StringVar(value="ready")
        ttk.Label(self, textvariable=self._status, style="Status.TLabel", anchor="w").pack(
            side="bottom", fill="x"
        )

    def _build_button_rail(self, parent):
        rail = ttk.Frame(parent)
        rail.pack(side="right", fill="y")
        buttons = [
            ("Record", lambda: self._rail_record()),
            ("Play", self._rail_play),
            ("Stop", audio_out.stop),
            ("Open", self.open_files),
            ("Save", self._rail_save),
            ("Snapshot", self._rail_snapshot),
            ("Prev", lambda: self._step_clip(-1)),
            ("Next", lambda: self._step_clip(1)),
            ("Home", lambda: self.nb.select(0)),
        ]
        for label, cmd in buttons:
            ttk.Button(rail, text=label, style="Rail.TButton", command=cmd).pack(fill="x", pady=1, padx=2)

    def _build_soft_keys(self):
        self._soft = ttk.Frame(self)
        self._soft.pack(side="bottom", fill="x")
        self._soft_btns = [ttk.Button(self._soft, text="", width=16) for _ in range(4)]
        for b in self._soft_btns:
            b.pack(side="left", padx=2, pady=2)

    def _update_soft_keys(self, screen):
        keys = getattr(screen, "soft_keys", lambda: [])()
        for i, btn in enumerate(self._soft_btns):
            if i < len(keys):
                label, cmd = keys[i]
                btn.configure(text=label, command=cmd, state="normal")
            else:
                btn.configure(text="", command=lambda: None, state="disabled")

    def _tick_clock(self):
        self._clock_var.set(time.strftime("%H:%M"))
        clip = self.ctx.state.primary()
        self._src_var.set(f"src: {clip.source}" if clip else "src: -")
        self._cal_var.set("CAL" if self.ctx.state.cfg["calibration"].get("enabled") else "uncal")
        self.after(1000, self._tick_clock)

    def _step_clip(self, delta):
        clips = self.ctx.state.clips()
        if not clips:
            return
        cur = self.ctx.state.selection()
        i = (cur[0] if cur else 0) + delta
        self.ctx.state.select([i % len(clips)])

    def _rail_play(self):
        clip = self.ctx.state.primary()
        if clip is not None and audio_out.is_available():
            audio_out.play(clip.samples, clip.fs)

    def _rail_record(self):
        for i, s in enumerate(self.screens):
            if s.title == "Record":
                self.nb.select(i)

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
        screen = self.screens[self.nb.index("current")]
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
                self._status.set(
                    f"analysed clip #{item['index']}: {item['features'].get('status')}"
                )
        self.after(_POLL_MS, self._poll)

    def _refresh_current(self):
        try:
            current = self.nb.index("current")
        except tk.TclError:
            return
        if 0 <= current < len(self.screens):
            screen = self.screens[current]
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


def _iter_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _iter_widgets(child)


def run() -> int:
    MainWindow().mainloop()
    return 0
