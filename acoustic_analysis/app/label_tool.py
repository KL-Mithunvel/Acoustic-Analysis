"""Tile labelling tool: a separate window for looking at every recorded strike and labelling it.

Opens the station's data-collection sessions read-only, analyses each clip, and shows for the
selected strike everything known about it - the tile picture, the camera's and vision model's
verdicts, the striker and distance sensor, and this app's own sound analysis - next to the label
buttons. Labels go to ``data/labels.json`` (``io/label_store``), never into a session folder.

Thin on purpose: loading is ``io/session_reader``, analysis and text are ``label_model``.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..config import load_config, resolve_path
from ..io.label_store import LabelStore
from ..io.session_reader import GROUP_TEXT, GROUPS, StrikeRecord, list_sessions, load_all, load_session
from ..label_model import NO_CAMERA, ReviewData
from .theme import ACCENT, BAD, FG, FG_DIM, FG_MUTE, INPUT, OK, PANEL, WARN, apply_theme, mono_font, ui_font

_ALL = "all"
_GROUP_CHOICES = [_ALL] + list(GROUPS)
_STATUS_CHOICES = [_ALL, "unlabelled", "labelled"]
_PIC_BOX = (520, 300)


def _short_session(name: str) -> str:
    return name.split("_", 1)[-1] if "_" in name else name


class LabelWindow(tk.Tk):
    def __init__(self, cfg: dict | None = None, sessions_dir: str | Path | None = None,
                 labels_path: str | Path | None = None):
        super().__init__()
        self.title("Tile labelling")
        self.minsize(1240, 740)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{min(1480, sw - 24)}x{min(900, sh - 80)}+8+8")
        apply_theme(self)

        self.cfg = cfg or load_config()
        self.labels = LabelStore.from_config(self.cfg, labels_path or resolve_path(self.cfg, "labels_file"))
        self.data = ReviewData([], self.cfg, self.labels)
        self._q: queue.Queue = queue.Queue()
        self._rec: StrikeRecord | None = None
        self._visible: list[StrikeRecord] = []
        self._photo = None
        self._generation = 0                       # a newer load makes an older worker's result stale

        self._build_top()
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_list(body)
        self._build_centre(body)
        self._build_info(body)
        self.status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status, style="Dim.TLabel", padding=(12, 4)).pack(side="bottom", fill="x")

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(100, self._pump)
        self.load(sessions_dir or resolve_path(self.cfg, "sessions_dir"))

    # ------------------------------------------------------------------ layout
    def _build_top(self):
        bar = ttk.Frame(self, padding=(12, 10))
        bar.pack(fill="x")
        ttk.Label(bar, text="Tile labelling", font=ui_font(15, "bold")).pack(side="left")
        self.progress_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.progress_var, foreground=ACCENT, font=ui_font(11, "bold")).pack(side="left", padx=18)
        ttk.Button(bar, text="Export labels (CSV)…", command=self.export).pack(side="right")
        ttk.Button(bar, text="Open sessions folder…", command=self.open_folder).pack(side="right", padx=8)

        flt = ttk.Frame(self, padding=(12, 0, 12, 8))
        flt.pack(fill="x")
        self.f_group = self._combo(flt, "Show", _GROUP_CHOICES, 20, lambda v: GROUP_TEXT.get(v, "everything"))
        self.f_camera = self._combo(flt, "Camera said", [_ALL], 18)
        self.f_status = self._combo(flt, "Label", _STATUS_CHOICES, 12)
        self.f_session = self._combo(flt, "Session", [_ALL], 20)

    def _combo(self, parent, text, values, width, show=None):
        ttk.Label(parent, text=text, style="Dim.TLabel").pack(side="left", padx=(0, 4))
        var = tk.StringVar(value=_ALL)
        cb = ttk.Combobox(parent, textvariable=var, values=values, width=width, state="readonly")
        cb.pack(side="left", padx=(0, 14))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.refresh_list())
        cb.var = var
        return cb

    def _build_list(self, body):
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        cols = ("group", "camera", "label")
        self.tree = ttk.Treeview(left, columns=cols, show="tree headings", height=24, selectmode="browse")
        self.tree.heading("#0", text="strike")
        self.tree.column("#0", width=128)
        for c, w, t in (("group", 92, "what"), ("camera", 78, "camera"), ("label", 92, "your label")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center")
        for tag, colour in (("done", OK), ("none", FG)):
            self.tree.tag_configure(tag, foreground=colour)
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="y", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

    def _build_centre(self, body):
        self.centre = ttk.Frame(body)
        self.centre.grid(row=0, column=1, sticky="nsew")
        self.centre.columnconfigure(0, weight=1)
        self.centre.rowconfigure(1, weight=1)
        self.pic = tk.Label(self.centre, bg=PANEL, fg=FG_MUTE, text="", width=_PIC_BOX[0] // 8, height=_PIC_BOX[1] // 16,
                            font=ui_font(10))
        self.pic.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.plot_area = ttk.Frame(self.centre)        # the plots live here (added with the sound analysis)
        self.plot_area.grid(row=1, column=0, sticky="nsew")

    def _build_info(self, body):
        self.right = ttk.Frame(body, width=440)
        self.right.grid(row=0, column=2, sticky="ns", padx=(10, 0))
        self.right.pack_propagate(False)
        self.flag_var = tk.StringVar(value="")
        ttk.Label(self.right, textvariable=self.flag_var, wraplength=420, foreground=WARN,
                  font=ui_font(10, "bold"), justify="left").pack(anchor="w", pady=(0, 6))
        wrap = ttk.Frame(self.right)
        wrap.pack(fill="both", expand=True)
        self.info = tk.Text(wrap, wrap="word", bg=PANEL, fg=FG, relief="flat", padx=10, pady=8,
                            font=ui_font(10), cursor="arrow", width=1, height=1)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.info.yview)
        self.info.configure(yscrollcommand=sb.set)
        self.info.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.info.tag_configure("h", foreground=ACCENT, font=ui_font(10, "bold"), spacing1=10, spacing3=3)
        self.info.tag_configure("k", foreground=FG_DIM)
        self.info.tag_configure("v", foreground=FG, font=mono_font(10))
        self.info.configure(state="disabled")
        self.controls = ttk.Frame(self.right)          # the label buttons live here (added with labelling)
        self.controls.pack(fill="x", pady=(8, 0))

    # ------------------------------------------------------------------ loading
    def open_folder(self):
        folder = filedialog.askdirectory(title="Choose a sessions folder (or one session)")
        if folder:
            self.load(folder)

    def load(self, folder: str | Path) -> None:
        folder = Path(folder)
        recs = load_session(folder) if (folder / "strikes.json").is_file() else load_all(folder)
        self._generation += 1
        gen = self._generation
        self.data = ReviewData(recs, self.cfg, self.labels)
        self.f_camera.configure(values=[_ALL] + self.data.camera_grades())
        self.f_session.configure(values=[_ALL] + sorted({r.session for r in recs}))
        for cb in (self.f_group, self.f_camera, self.f_status, self.f_session):
            cb.var.set(_ALL)
        self._rec = None
        self.refresh_list()
        if not recs:
            self.status.set(f"No sessions found in {folder}")
            return
        self.status.set(f"Analysing {len(recs)} strikes...")
        data = self.data

        def work():
            data.compute_features(progress=lambda i, n: self._q.put(("progress", gen, (i, n))))
            self._q.put(("done", gen, None))

        threading.Thread(target=work, daemon=True).start()

    def _pump(self):
        try:
            while True:
                kind, gen, payload = self._q.get_nowait()
                if gen != self._generation:
                    continue
                if kind == "progress":
                    self.status.set(f"Analysing strikes... {payload[0]} / {payload[1]}")
                elif kind == "done":
                    self.status.set(f"Ready - {len(self.data.records)} strikes from "
                                    f"{len({r.session for r in self.data.records})} session(s).")
                    self.refresh_list(keep=self._rec)
                    self._show(self._rec)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    # ------------------------------------------------------------------ list
    def refresh_list(self, keep: StrikeRecord | None = None) -> None:
        self._visible = self.data.filter(group=self.f_group.var.get(), camera=self.f_camera.var.get(),
                                         status=self.f_status.var.get(), session=self.f_session.var.get())
        self.tree.delete(*self.tree.get_children())
        for r in self._visible:
            lab = self.labels.get(r.key)
            text = (lab.get("label") or "") + (f" {lab['tier']}" if lab and lab.get("tier") else "") if lab else ""
            cam = (r.camera or {}).get("grade", "-")
            self.tree.insert("", "end", iid=r.key, text=f"{_short_session(r.session)}  {r.id}",
                             values=(r.group.replace("_", " "), cam, text), tags=("done" if lab else "none",))
        done, total = self.data.progress()
        self.progress_var.set(f"{done} of {total} labelled")
        target = keep.key if keep is not None and self.tree.exists(keep.key) else None
        if target is None and self._visible:
            target = self._visible[0].key
        if target:
            self.tree.selection_set(target)
            self.tree.focus(target)
            self.tree.see(target)
        else:
            self._show(None)

    def _on_select(self):
        sel = self.tree.selection()
        rec = next((r for r in self._visible if sel and r.key == sel[0]), None)
        self._rec = rec
        self._show(rec)

    # ------------------------------------------------------------------ detail
    def _show(self, rec: StrikeRecord | None) -> None:
        self._show_picture(rec)
        self._show_info(rec)

    def _show_picture(self, rec: StrikeRecord | None) -> None:
        self._photo = None
        if rec is None:
            self.pic.configure(image="", text="Nothing selected")
            return
        if rec.picture_path is None:
            why = ("Striker alone - there is no tile to photograph." if rec.group in ("no_tile", "ambient")
                   else "No picture of this tile was saved in the session.")
            self.pic.configure(image="", text=why)
            return
        try:
            from PIL import Image, ImageTk

            img = Image.open(rec.picture_path)
            img.thumbnail(_PIC_BOX)
            self._photo = ImageTk.PhotoImage(img)
            self.pic.configure(image=self._photo, text="")
        except Exception as exc:  # noqa: BLE001 - a broken picture must not stop labelling
            self.pic.configure(image="", text=f"Could not open the picture:\n{exc}")

    def _show_info(self, rec: StrikeRecord | None) -> None:
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        if rec is None:
            self.flag_var.set("")
        else:
            self.flag_var.set("  ".join(self.data.flags(rec)) if rec.key in self.data.features else "Analysing...")
            for sec in self.data.sections(rec):
                self.info.insert("end", sec.title + "\n", "h")
                for k, v in sec.rows:
                    self.info.insert("end", f"{k}: ", "k")
                    self.info.insert("end", v + "\n", "v")
        self.info.configure(state="disabled")

    # ------------------------------------------------------------------ export
    def export(self):
        if len(self.labels) == 0:
            messagebox.showinfo("Export", "Nothing is labelled yet.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="station_labels.csv",
                                            initialdir=str(resolve_path(self.cfg, "exports_dir")))
        if not path:
            return
        n = self.labels.export_csv(path, self.data.records, self.data.features)
        self.status.set(f"Exported {n} labelled strikes to {path}")


def run(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="label", description="Look at and label recorded tile strikes.")
    ap.add_argument("sessions", nargs="?", help="a sessions folder, or one session folder (default: config paths.sessions_dir)")
    args = ap.parse_args(argv)
    LabelWindow(sessions_dir=args.sessions).mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
