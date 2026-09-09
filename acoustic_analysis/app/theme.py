"""Dark "instrument" theme - a ttk style, named styles for the app shell, plus
matching matplotlib defaults, so the app reads like the screen of a handheld
analyser (docs/UI_DESIGN.md). Palette extends the original blue-grey / blue-accent
set; every numeric readout is set in a monospace face.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import matplotlib as mpl

# -- palette -----------------------------------------------------------------
BG = "#141419"          # window background / content ground
SIDEBAR = "#0f0f13"     # left nav + right action rail
RAIL = SIDEBAR
PANEL = "#1c1c23"       # raised panels / cards
PANEL_2 = "#23232c"     # secondary panels, list rows, default buttons
INPUT = "#2b2b35"       # entries, combobox fields, sliders
LINE = "#33333e"        # borders / separators
FG = "#ededf1"          # primary text
FG_DIM = "#9c9caa"      # secondary text
FG_MUTE = "#63636f"     # tertiary / disabled / group headers
ACCENT = "#4aa8ff"      # selection / focus / primary action
ACCENT_2 = "#2f8ae0"    # accent gradient foot / pressed
ACCENT_INK = "#06121f"  # text on an accent fill
OK = "#4fc98a"          # calibrated / GOOD
WARN = "#e6b053"        # borderline / caution
BAD = "#e85d52"         # reject / error / REC
PLOT_BG = "#131318"     # embedded-plot axes face

# -- fonts -----------------------------------------------------------------
UI_FAMILY = "Segoe UI"          # present on every Win10/11 target
MONO_FAMILY = "Consolas"        # universal Windows monospace


def ui_font(size: int = 10, weight: str = "normal") -> tuple:
    return (UI_FAMILY, size, weight) if weight != "normal" else (UI_FAMILY, size)


def mono_font(size: int = 10, weight: str = "normal") -> tuple:
    return (MONO_FAMILY, size, weight) if weight != "normal" else (MONO_FAMILY, size)


def apply_theme(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")

    # named default fonts - propagate to plain tk widgets too
    for name, spec in (
        ("TkDefaultFont", (UI_FAMILY, 10)),
        ("TkTextFont", (UI_FAMILY, 10)),
        ("TkMenuFont", (UI_FAMILY, 10)),
        ("TkHeadingFont", (UI_FAMILY, 10, "bold")),
        ("TkFixedFont", (MONO_FAMILY, 10)),
    ):
        try:
            f = tkfont.nametofont(name)
            f.configure(family=spec[0], size=spec[1])
            if len(spec) > 2:
                f.configure(weight=spec[2])
        except tk.TclError:  # pragma: no cover - font name absent on some platforms
            pass

    root.configure(bg=BG)
    style.configure(".", background=BG, foreground=FG, fieldbackground=INPUT,
                    bordercolor=LINE, lightcolor=PANEL, darkcolor=SIDEBAR,
                    focuscolor=ACCENT, font=(UI_FAMILY, 10))
    style.map(".", foreground=[("disabled", FG_MUTE)])

    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=PANEL, bordercolor=LINE, relief="solid", borderwidth=1)
    style.configure("Sidebar.TFrame", background=SIDEBAR)
    style.configure("Rail.TFrame", background=RAIL)
    style.configure("Status.TFrame", background=SIDEBAR)

    style.configure("TLabelframe", background=BG, foreground=FG_DIM, bordercolor=LINE)
    style.configure("TLabelframe.Label", background=BG, foreground=FG_DIM, font=(UI_FAMILY, 9, "bold"))

    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Dim.TLabel", background=BG, foreground=FG_DIM)
    style.configure("Mute.TLabel", background=BG, foreground=FG_MUTE)
    style.configure("H.TLabel", background=BG, foreground=FG_MUTE, font=(UI_FAMILY, 9, "bold"))
    style.configure("Card.TLabel", background=PANEL, foreground=FG)
    style.configure("CardH.TLabel", background=PANEL, foreground=FG_DIM, font=(UI_FAMILY, 9, "bold"))
    style.configure("Value.TLabel", background=PANEL, foreground=FG, font=(MONO_FAMILY, 11))
    style.configure("Big.TLabel", background=PANEL, foreground=FG, font=(MONO_FAMILY, 20, "bold"))
    style.configure("Status.TLabel", background=SIDEBAR, foreground=FG, font=(UI_FAMILY, 10))
    style.configure("StatusMeta.TLabel", background=SIDEBAR, foreground=FG_DIM, font=(MONO_FAMILY, 9))
    style.configure("StatusTitle.TLabel", background=SIDEBAR, foreground=FG, font=(UI_FAMILY, 11, "bold"))
    style.configure("Ok.TLabel", background=SIDEBAR, foreground=OK, font=(MONO_FAMILY, 9, "bold"))
    style.configure("Rec.TLabel", background=SIDEBAR, foreground=BAD, font=(MONO_FAMILY, 9, "bold"))

    style.configure("TButton", background=PANEL_2, foreground=FG, bordercolor=LINE,
                    borderwidth=1, focusthickness=1, focuscolor=ACCENT, padding=(10, 6))
    style.map("TButton",
              background=[("pressed", INPUT), ("active", INPUT), ("disabled", PANEL)],
              foreground=[("disabled", FG_MUTE)])
    style.configure("Accent.TButton", background=ACCENT, foreground=ACCENT_INK,
                    bordercolor=ACCENT_2, font=(UI_FAMILY, 10, "bold"))
    style.map("Accent.TButton", background=[("pressed", ACCENT_2), ("active", "#5bb2ff")])
    style.configure("Ghost.TButton", background=BG, foreground=FG_DIM, bordercolor=LINE)
    style.map("Ghost.TButton", background=[("active", PANEL_2)])
    style.configure("Danger.TButton", background="#3a2220", foreground="#f0a49d", bordercolor="#5b2f2b")
    style.map("Danger.TButton", background=[("active", "#4a2a27")])
    style.configure("Soft.TButton", background=PANEL_2, foreground=FG, bordercolor=LINE, padding=(8, 5))
    style.map("Soft.TButton", background=[("active", INPUT), ("disabled", "#1a1a20")],
              foreground=[("disabled", FG_MUTE)])
    style.configure("Info.TButton", background=PANEL, foreground=FG_MUTE, bordercolor=LINE, padding=1)
    style.map("Info.TButton", background=[("active", PANEL_2)], foreground=[("active", FG)])

    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL_2, foreground=FG_DIM, padding=(12, 6))
    style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", FG)])

    style.configure("Treeview", background=PANEL_2, fieldbackground=PANEL_2, foreground=FG,
                    bordercolor=LINE, rowheight=24, font=(MONO_FAMILY, 9))
    style.configure("Treeview.Heading", background=SIDEBAR, foreground=FG_MUTE,
                    font=(UI_FAMILY, 9, "bold"), relief="flat")
    style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", ACCENT_INK)])
    style.map("Treeview.Heading", background=[("active", PANEL_2)])

    style.configure("TCombobox", fieldbackground=INPUT, background=INPUT, foreground=FG,
                    bordercolor=LINE, arrowcolor=FG_DIM, selectbackground=INPUT, selectforeground=FG)
    style.map("TCombobox", fieldbackground=[("readonly", INPUT)], foreground=[("disabled", FG_MUTE)])
    style.configure("TEntry", fieldbackground=INPUT, foreground=FG, bordercolor=LINE, insertcolor=FG)
    style.configure("TProgressbar", background=ACCENT, troughcolor=INPUT, bordercolor=LINE, thickness=14)
    style.configure("TScale", background=BG, troughcolor=INPUT)
    style.configure("TCheckbutton", background=BG, foreground=FG, focuscolor=ACCENT)
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=BG, bordercolor=BG,
                    arrowcolor=FG_DIM)
    style.configure("Horizontal.TScrollbar", background=PANEL_2, troughcolor=BG, bordercolor=BG,
                    arrowcolor=FG_DIM)

    root.option_add("*Listbox.background", PANEL_2)
    root.option_add("*Listbox.foreground", FG)
    root.option_add("*Listbox.selectBackground", ACCENT)
    root.option_add("*Listbox.selectForeground", ACCENT_INK)
    root.option_add("*Listbox.font", f"{{{MONO_FAMILY}}} 9")
    root.option_add("*Listbox.borderWidth", 0)
    root.option_add("*Listbox.highlightThickness", 0)
    root.option_add("*Text.background", PANEL_2)
    root.option_add("*Text.foreground", FG)
    root.option_add("*Text.insertBackground", FG)
    root.option_add("*Text.borderWidth", 0)
    root.option_add("*Text.highlightThickness", 0)
    root.option_add("*Text.font", f"{{{MONO_FAMILY}}} 9")
    root.option_add("*Menu.background", PANEL_2)
    root.option_add("*Menu.foreground", FG)
    root.option_add("*Menu.activeBackground", ACCENT)
    root.option_add("*Menu.activeForeground", ACCENT_INK)

    mpl.rcParams.update(
        {
            "figure.facecolor": PANEL,
            "axes.facecolor": PLOT_BG,
            "savefig.facecolor": PANEL,
            "text.color": FG,
            "axes.edgecolor": "#3a3a45",
            "axes.labelcolor": FG_DIM,
            "axes.titlecolor": FG,
            "axes.titlesize": 9,
            "axes.titleweight": "bold",
            "xtick.color": FG_DIM,
            "ytick.color": FG_DIM,
            "grid.color": "#2a2a33",
            "axes.grid": True,
            "legend.facecolor": PANEL_2,
            "legend.edgecolor": "#3a3a45",
            "font.family": "sans-serif",
            "font.sans-serif": [UI_FAMILY, "DejaVu Sans"],
            "font.size": 8,
        }
    )
