"""Reusable Tk widgets: an embedded matplotlib panel with a "?" explainer, a
key/value feature table, and a helper to attach an explainer popup to anything.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import matplotlib

matplotlib.use("Agg", force=False)  # a real backend is selected by FigureCanvasTkAgg
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402


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
    btn = ttk.Button(parent, text="?", width=2, command=lambda: show_explanation(parent, explainer, key))
    return btn


class MplPanel(ttk.Frame):
    """A titled matplotlib figure with a "?" button wired to an explainer key."""

    def __init__(self, master, explainer=None, explain_key: str | None = None, figsize=(5.0, 3.0)):
        super().__init__(master)
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
        self.tree.column("#0", width=210)
        self.tree.column("value", width=160, anchor="e")
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
