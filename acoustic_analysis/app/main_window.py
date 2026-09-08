"""The main window: a menu, a status bar, and a notebook of screens, plus the
periodic poll that pulls finished analysis off the worker and refreshes the
current screen.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..config import load_config, resolve_path
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
        self.geometry("1180x760")

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
        self._status = tk.StringVar(value="ready")
        ttk.Label(self, textvariable=self._status, anchor="w", relief="sunken").pack(
            side="bottom", fill="x"
        )

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.screens = []
        for cls in _SCREENS:
            screen = cls(self.nb, self.ctx)
            self.nb.add(screen, text=screen.title)
            self.screens.append(screen)
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._refresh_current())

        state.add_listener(self._refresh_current)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(_POLL_MS, self._poll)
        self._bind_shortcuts()

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
            self.screens[current].refresh()

    def _on_close(self):
        try:
            self.ctx.service.stop()
            self.ctx.db.close()
        finally:
            self.destroy()


def run() -> int:
    MainWindow().mainloop()
    return 0
