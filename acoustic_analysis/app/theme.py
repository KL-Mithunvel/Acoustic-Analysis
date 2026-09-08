"""Dark "instrument" theme - a ttk style plus matching matplotlib defaults, so
the app reads like the screen of a handheld analyser (docs/UI_DESIGN.md).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import matplotlib as mpl

BG = "#1e1e24"          # window background
PANEL = "#26262e"       # raised panels
PANEL_2 = "#2e2e38"     # inputs, list rows
FG = "#e6e6e6"          # primary text
FG_DIM = "#9a9aa6"      # secondary text
ACCENT = "#3ea6ff"      # selection / focus
OK = "#4caf7d"
WARN = "#e0a34a"
BAD = "#e2564d"
RAIL = "#17171c"


def apply_theme(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(bg=BG)
    style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL_2,
                    bordercolor=RAIL, lightcolor=PANEL, darkcolor=RAIL)
    style.configure("TFrame", background=BG)
    style.configure("TLabelframe", background=BG, foreground=FG_DIM)
    style.configure("TLabelframe.Label", background=BG, foreground=FG_DIM)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Dim.TLabel", foreground=FG_DIM)
    style.configure("Status.TLabel", background=RAIL, foreground=FG, padding=6)

    style.configure("TButton", background=PANEL_2, foreground=FG, borderwidth=1, padding=6)
    style.map("TButton", background=[("active", PANEL), ("pressed", ACCENT)])
    style.configure("Rail.TButton", background=RAIL, foreground=FG, padding=(6, 10), width=8)
    style.map("Rail.TButton", background=[("active", PANEL_2), ("pressed", ACCENT)])
    style.configure("Accent.TButton", background=ACCENT, foreground="#0b1a2b")

    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL_2, foreground=FG_DIM, padding=(12, 6))
    style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", FG)])

    style.configure("Treeview", background=PANEL_2, fieldbackground=PANEL_2, foreground=FG,
                    bordercolor=RAIL)
    style.configure("Treeview.Heading", background=RAIL, foreground=FG_DIM)
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#0b1a2b")])

    style.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=FG)
    style.configure("TProgressbar", background=ACCENT, troughcolor=PANEL_2)

    root.option_add("*Listbox.background", PANEL_2)
    root.option_add("*Listbox.foreground", FG)
    root.option_add("*Listbox.selectBackground", ACCENT)
    root.option_add("*Text.background", PANEL_2)
    root.option_add("*Text.foreground", FG)
    root.option_add("*Text.insertBackground", FG)

    mpl.rcParams.update(
        {
            "figure.facecolor": PANEL,
            "axes.facecolor": "#1b1b21",
            "savefig.facecolor": PANEL,
            "text.color": FG,
            "axes.edgecolor": "#4a4a55",
            "axes.labelcolor": FG_DIM,
            "axes.titlecolor": FG,
            "xtick.color": FG_DIM,
            "ytick.color": FG_DIM,
            "grid.color": "#33333d",
            "axes.grid": True,
            "font.size": 8,
        }
    )
