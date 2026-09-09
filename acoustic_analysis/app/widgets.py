"""Reusable Tk widgets: an embedded matplotlib panel with a "?" explainer, a
key/value feature table, the sidebar nav item and action-rail button that make
up the instrument shell, and a helper to attach an explainer popup to anything.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import matplotlib

from .theme import ACCENT, BAD, FG, FG_DIM, RAIL, SIDEBAR, ui_font

matplotlib.use("Agg", force=False)  # a real backend is selected by FigureCanvasTkAgg
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

_NAV_HOVER = "#17171d"
_NAV_ACTIVE_BG = "#1b2740"
_NAV_ACTIVE_FG = "#cfe6ff"


def show_explanation(parent, explainer, key: str) -> None:
    """Pop a small window with the explanation text for ``key``."""
    top = tk.Toplevel(parent)
    top.title(explainer.title(key) or key)
    top.geometry("460x320")
    frame = ttk.Frame(top, padding=12)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=explainer.title(key) or key, font=("", 11, "bold")).pack(anchor="w")
    text = tk.Text(frame, wrap="word", height=12, relief="flat", borderwidth=0)
    text.insert("1.0", explainer.body(key))
    text.configure(state="disabled")
    text.pack(fill="both", expand=True, pady=(8, 8))
    ttk.Button(frame, text="Close", command=top.destroy).pack(anchor="e")


def info_button(parent, explainer, key: str) -> ttk.Button:
    btn = ttk.Button(parent, text="?", width=2, style="Info.TButton",
                     command=lambda: show_explanation(parent, explainer, key))
    return btn


# -- instrument shell ------------------------------------------------------
class NavItem(tk.Frame):
    """One row in the left sidebar: an accent bar + label, click to select."""

    def __init__(self, master, text: str, command, bg: str = SIDEBAR):
        super().__init__(master, bg=bg, cursor="hand2")
        self._bg = bg
        self._command = command
        self._active = False
        self._bar = tk.Frame(self, bg=bg, width=3)
        self._bar.pack(side="left", fill="y")
        self._lbl = tk.Label(self, text=text, bg=bg, fg=FG_DIM, anchor="w",
                             font=ui_font(10), padx=13, pady=8)
        self._lbl.pack(side="left", fill="x", expand=True)
        for w in (self, self._lbl):
            w.bind("<Button-1>", lambda _e: self._command())
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _enter(self, _e=None):
        if not self._active:
            self._paint(_NAV_HOVER, FG, self._bg)

    def _leave(self, _e=None):
        if not self._active:
            self._paint(self._bg, FG_DIM, self._bg)

    def set_active(self, on: bool) -> None:
        self._active = on
        if on:
            self._paint(_NAV_ACTIVE_BG, _NAV_ACTIVE_FG, ACCENT)
        else:
            self._paint(self._bg, FG_DIM, self._bg)

    def _paint(self, bg: str, fg: str, bar: str) -> None:
        self.configure(bg=bg)
        self._lbl.configure(bg=bg, fg=fg)
        self._bar.configure(bg=bar)


class RailButton(tk.Frame):
    """One button in the right action rail: a drawn glyph over a small label."""

    def __init__(self, master, glyph: str, text: str, command, bg: str = RAIL, danger: bool = False):
        super().__init__(master, bg=bg, cursor="hand2")
        self._bg = bg
        self._glyph = glyph
        self._danger = danger
        self._cv = tk.Canvas(self, width=22, height=20, bg=bg, highlightthickness=0, bd=0)
        self._cv.pack(pady=(8, 2))
        self._lbl = tk.Label(self, text=text, bg=bg, fg=FG_DIM, font=ui_font(8))
        self._lbl.pack(pady=(0, 8))
        _draw_glyph(self._cv, glyph, FG_DIM)
        for w in (self, self._cv, self._lbl):
            w.bind("<Button-1>", lambda _e: command())
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _enter(self, _e=None):
        fg = BAD if self._danger else FG
        for w in (self, self._cv):
            w.configure(bg=_NAV_HOVER)
        self._lbl.configure(bg=_NAV_HOVER, fg=fg)
        _draw_glyph(self._cv, self._glyph, fg)

    def _leave(self, _e=None):
        for w in (self, self._cv):
            w.configure(bg=self._bg)
        self._lbl.configure(bg=self._bg, fg=FG_DIM)
        _draw_glyph(self._cv, self._glyph, FG_DIM)


def _draw_glyph(cv: tk.Canvas, name: str, color: str) -> None:
    """Draw a simple 22x20 monoline icon. Unknown names draw nothing."""
    cv.delete("all")
    w = 1.8
    rc = {"width": w, "fill": color, "joinstyle": "round", "capstyle": "round"}
    if name == "rec":
        cv.create_oval(6, 4, 16, 14, fill=color, outline=color)
    elif name == "play":
        cv.create_polygon(7, 3, 7, 17, 18, 10, fill=color, outline=color)
    elif name == "stop":
        cv.create_rectangle(6, 4, 16, 14, fill=color, outline=color)
    elif name == "open":
        cv.create_rectangle(3, 6, 19, 16, outline=color, width=w)
        cv.create_line(3, 7, 8, 7, 10, 9, 18, 9, **rc)
    elif name == "save":
        cv.create_rectangle(4, 3, 18, 17, outline=color, width=w)
        cv.create_rectangle(8, 3, 14, 7, outline=color, width=w)
        cv.create_rectangle(7, 11, 15, 17, outline=color, width=w)
    elif name == "snap":
        cv.create_rectangle(3, 6, 19, 17, outline=color, width=w)
        cv.create_oval(8, 9, 14, 15, outline=color, width=w)
    elif name == "prev":
        cv.create_line(13, 3, 8, 10, 13, 17, **rc)
    elif name == "next":
        cv.create_line(9, 3, 14, 10, 9, 17, **rc)
    elif name == "back":
        cv.create_arc(4, 4, 18, 18, start=110, extent=250, style="arc", outline=color, width=w)
        cv.create_line(4, 6, 4, 11, 9, 9, **rc)
    elif name == "home":
        cv.create_line(3, 11, 11, 3, 19, 11, **rc)
        cv.create_rectangle(5, 10, 17, 18, outline=color, width=w)


class MplPanel(ttk.Frame):
    """A titled matplotlib figure with a "?" button wired to an explainer key."""

    def __init__(self, master, explainer=None, explain_key: str | None = None, figsize=(5.0, 3.0)):
        super().__init__(master, width=int(figsize[0] * 96), height=int(figsize[1] * 96))
        # The Tk matplotlib backend resizes its widget to the figure's pixel
        # size on every draw; without this the panel would force that size onto
        # its container and screens would overflow. propagate=False keeps the
        # panel at whatever size its parent's grid/pack cell gives it, and the
        # canvas (fill=both) plus the backend's <Configure> handler then fit the
        # figure to the panel.
        self.pack_propagate(False)
        self.grid_propagate(False)
        header = ttk.Frame(self)
        header.pack(fill="x")
        if explainer is not None and explain_key and explainer.has(explain_key):
            info_button(header, explainer, explain_key).pack(side="right")

        self.figure = Figure(figsize=figsize, layout="constrained")
        self._canvas = FigureCanvasTkAgg(self.figure, master=self)
        self._canvas.get_tk_widget().pack(fill="both", expand=True)

    def draw_with(self, fn, *args, **kwargs) -> None:
        """Clear the figure, call ``fn(ax, *args, **kwargs)``, redraw."""
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        try:
            fn(ax, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - show the problem, don't crash the UI
            ax.clear()
            ax.text(0.5, 0.5, f"plot error:\n{exc}", ha="center", va="center", fontsize=8, wrap=True)
        self._canvas.draw_idle()

    def clear(self) -> None:
        self.figure.clear()
        self._canvas.draw_idle()


class FeatureTree(ttk.Frame):
    """A two-column (name / value) tree for showing a flat feature dict."""

    def __init__(self, master, height: int = 16):
        super().__init__(master)
        self.tree = ttk.Treeview(self, columns=("value",), show="tree headings", height=height)
        self.tree.heading("#0", text="feature")
        self.tree.heading("value", text="value")
        self.tree.column("#0", width=150, minwidth=90, stretch=True)
        self.tree.column("value", width=92, minwidth=64, anchor="e", stretch=False)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def show(self, features: dict | None) -> None:
        self.tree.delete(*self.tree.get_children())
        if not features:
            return
        for key, value in features.items():
            if key in ("reasons", "peaks", "octave_band_shape_db", "octave_centres_hz",
                       "per_band_decay_db_s", "time_to_drop_s"):
                continue
            if isinstance(value, dict):
                parent = self.tree.insert("", "end", text=key, values=("",))
                for k2, v2 in value.items():
                    self.tree.insert(parent, "end", text=f"  {k2}", values=(_fmt(v2),))
            else:
                self.tree.insert("", "end", text=key, values=(_fmt(value),))


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, bool):
        return "yes" if v else "no"
    return str(v)
