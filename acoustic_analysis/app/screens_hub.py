"""Label tiles: where the labelling tool is explained and opened, and how far along you are.

The labelling tool is its own window (it shows pictures, camera results and plots side by side, and
needs the room). This screen is the doorway to it from the one app: the three steps in plain words, how many
tiles are labelled, whether the sound reference exists yet, and a button that opens the tool.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ..config import resolve_path
from ..io.label_store import LabelError, LabelStore
from ..strike_reference import ReferenceError as RefError, StrikeReference
from .label_tool import launch as label_launch
from .screens import _Base
from .theme import ACCENT, FG_DIM, OK, WARN, ui_font

_STEPS = (
    ("1", "Test tiles", "On the Test Tile screen, strike tiles you know. Every test is saved."),
    ("2", "Label them", "Open the labelling tool. Look at each tile's picture and listen; press G for a good tile, "
                        "C for cracked, B for a broken corner."),
    ("3", "Build the reference", "Once about 8 tiles are labelled good, press Build sound reference. "
                                 "From then on Test Tile grades every strike."),
)


class LabelHubScreen(_Base):
    title = "Label tiles"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self.cfg = ctx.state.cfg
        ttk.Label(self, text="Teach the app which tiles are good", font=ui_font(17, "bold")).pack(anchor="w")
        ttk.Label(self, text="The sound grade is only as good as the labels behind it - and they have to come from a "
                  "person looking at the tile.", style="Dim.TLabel", wraplength=900).pack(anchor="w", pady=(2, 14))

        steps = ttk.Frame(self)
        steps.pack(fill="x")
        steps.columnconfigure((0, 1, 2), weight=1, uniform="step")
        for i, (n, head, body) in enumerate(_STEPS):
            c = ttk.Frame(steps, style="Card.TFrame", padding=12)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            ttk.Label(c, text=f"{n}   {head.upper()}", style="CardH.TLabel").pack(anchor="w")
            ttk.Label(c, text=body, style="Card.TLabel", wraplength=260, justify="left").pack(anchor="w", pady=(6, 0))

        self.stats = ttk.Frame(self, style="Card.TFrame", padding=12)
        self.stats.pack(fill="x", pady=(14, 0))
        ttk.Label(self.stats, text="WHERE YOU ARE", style="CardH.TLabel").pack(anchor="w")
        self.labelled = ttk.Label(self.stats, text="", style="Card.TLabel", font=ui_font(12, "bold"))
        self.labelled.pack(anchor="w", pady=(6, 0))
        self.detail = ttk.Label(self.stats, text="", style="Card.TLabel", foreground=FG_DIM, wraplength=900)
        self.detail.pack(anchor="w")
        self.reference = ttk.Label(self.stats, text="", style="Card.TLabel", font=ui_font(11, "bold"))
        self.reference.pack(anchor="w", pady=(8, 0))

        row = ttk.Frame(self)
        row.pack(fill="x", pady=(14, 0))
        ttk.Button(row, text="Open the labelling tool", style="Accent.TButton", command=self.open_tool).pack(side="left")
        ttk.Button(row, text="Go to Test Tile", command=lambda: ctx.navigate("Test Tile")).pack(side="left", padx=8)
        self.status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status, style="Dim.TLabel").pack(anchor="w", pady=(8, 0))

    def _path(self, key: str, default: str) -> Path:
        try:
            return resolve_path(self.cfg, key)
        except KeyError:
            return Path(self.cfg["paths"]["data_dir"]) / default

    def open_tool(self):
        try:
            label_launch()
            self.status.set("Opening the labelling tool in its own window...")
        except OSError as exc:
            self.status.set(f"Could not start the labelling tool: {exc}")

    def refresh(self):
        try:
            store = LabelStore.from_config(self.cfg, self._path("labels_file", "labels.json"))
            counts = {k: v for k, v in store.counts().items() if k != "(tier only)"}
            total = sum(counts.values())
            self.labelled.configure(text=f"{total} tiles labelled" if total else "No tiles labelled yet",
                                    foreground=OK if total else FG_DIM)
            self.detail.configure(text=", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(counts.items())))
        except LabelError as exc:
            self.labelled.configure(text="The labels file could not be read", foreground=WARN)
            self.detail.configure(text=str(exc))
        p = self._path("strike_reference", "strike_reference.json")
        try:
            ref = StrikeReference.load(p) if p.is_file() else None
        except RefError:
            ref = None
        if ref:
            self.reference.configure(text=f"Sound reference: built from {ref.n_good} good tiles - Test Tile is grading",
                                     foreground=OK)
        else:
            need = int(self.cfg["strike"]["reference"]["min_good"])
            self.reference.configure(text=f"Sound reference: not built yet (needs {need} tiles labelled good)",
                                     foreground=ACCENT)
