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
from ..io import audio_out
from ..io.label_store import LabelStore
from ..io.session_reader import GROUP_TEXT, GROUPS, StrikeRecord, load_all, load_session
from ..label_model import ReviewData, load_wav
from .plots import draw_strike_overview
from .theme import ACCENT, FG, FG_DIM, FG_MUTE, OK, PANEL, WARN, apply_theme, mono_font, ui_font
from .widgets import MplPanel

_ALL = "all"
_GROUP_CHOICES = [_ALL] + list(GROUPS)
_STATUS_CHOICES = [_ALL, "unlabelled", "labelled"]
_PIC_BOX = (560, 250)


def _short_session(name: str) -> str:
    return name.split("_", 1)[-1] if "_" in name else name


class LabelWindow(tk.Tk):
    def __init__(self, cfg: dict | None = None, sessions_dir: str | Path | None = None,
                 labels_path: str | Path | None = None):
        super().__init__()
        self.title("Tile labelling")
        self.minsize(1300, 720)
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
        self.tree.column("#0", width=112, stretch=False)
        for c, w, t in (("group", 70, "what"), ("camera", 66, "camera"), ("label", 84, "your label")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center", stretch=False)
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
        # A Label's width/height are text units until it shows an image, then pixels - so the box is a
        # fixed-size Frame and the Label just fills it.
        box = tk.Frame(self.centre, bg=PANEL, height=_PIC_BOX[1])
        box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        box.pack_propagate(False)
        self.pic = tk.Label(box, bg=PANEL, fg=FG_MUTE, text="", font=ui_font(10))
        self.pic.pack(fill="both", expand=True)
        self.plot = MplPanel(self.centre, figsize=(5.0, 2.6))
        self.plot.grid(row=1, column=0, sticky="nsew")

    def _build_info(self, body):
        self.right = ttk.Frame(body, width=400)
        self.right.grid(row=0, column=2, sticky="ns", padx=(10, 0))
        self.right.pack_propagate(False)
        self.flag_var = tk.StringVar(value="")
        ttk.Label(self.right, textvariable=self.flag_var, wraplength=390, foreground=WARN,
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
        self.controls = ttk.Frame(self.right)
        self.controls.pack(fill="x", pady=(8, 0))
        self._build_controls()

    # ------------------------------------------------------------------ labelling controls
    def _build_controls(self):
        c = self.controls
        self.cur_label_var = tk.StringVar(value="")
        self.cur_label = ttk.Label(c, textvariable=self.cur_label_var, font=ui_font(11, "bold"))
        self.cur_label.pack(anchor="w")
        ttk.Label(c, text="What is the TILE like? (look at it and listen)", style="Dim.TLabel").pack(anchor="w", pady=(4, 2))
        grid = ttk.Frame(c)
        grid.pack(fill="x")
        self._label_keys: dict[str, str] = {}
        used: set[str] = set()
        for i, name in enumerate(self.labels.classes + self.labels.extra):
            # first letter of each word (corner_broken -> c, then b), then any letter still free
            cands = [w[0] for w in name.split("_") if w] + [ch for ch in name if ch.isalpha()]
            key = next((ch for ch in cands if ch not in used), name[0])
            used.add(key)
            self._label_keys[key] = name
            ttk.Button(grid, text=f"{name.replace('_', ' ')}  [{key.upper()}]",
                       command=lambda n=name: self.set_label(n)).grid(row=i // 3, column=i % 3, sticky="ew", padx=2, pady=2)
        for col in range(3):
            grid.columnconfigure(col, weight=1, uniform="lab")
        tiers = ttk.Frame(c)
        tiers.pack(fill="x", pady=(4, 0))
        ttk.Label(tiers, text="Look grade", style="Dim.TLabel").pack(side="left", padx=(0, 6))
        self._tier_keys = {str(i + 1): g for i, g in enumerate(self.labels.grades)}
        for key, g in self._tier_keys.items():
            ttk.Button(tiers, text=f"{g} [{key}]", width=7, command=lambda t=g: self.set_tier(t)).pack(side="left", padx=2)
        note = ttk.Frame(c)
        note.pack(fill="x", pady=(6, 0))
        ttk.Label(note, text="Note", style="Dim.TLabel").pack(side="left", padx=(0, 6))
        self.note_var = tk.StringVar()
        self._note_for: str | None = None
        self.note_entry = ttk.Entry(note, textvariable=self.note_var)
        self.note_entry.pack(side="left", fill="x", expand=True)
        self.note_entry.bind("<Return>", lambda _e: self.save_note())
        self.note_entry.bind("<FocusOut>", lambda _e: self.save_note())
        acts = ttk.Frame(c)
        acts.pack(fill="x", pady=(6, 0))
        ttk.Button(acts, text="Play sound  [Space]", command=self.play).pack(side="left")
        ttk.Button(acts, text="Clear label", command=self.clear_label).pack(side="left", padx=6)
        ttk.Label(c, text="Keys: letters / digits label  -  Left, Right = previous / next",
                  style="Dim.TLabel").pack(anchor="w", pady=(6, 0))
        self.bind("<Key>", self._on_key)
        self.bind("<Right>", lambda _e: self._step(1))
        self.bind("<Left>", lambda _e: self._step(-1))

    def _typing(self) -> bool:
        return isinstance(self.focus_get(), (tk.Entry, ttk.Entry, ttk.Combobox))

    def _on_key(self, e):
        if self._typing():
            return
        ch = (e.char or "").lower()
        if ch == " ":
            self.play()
        elif ch in self._label_keys:
            self.set_label(self._label_keys[ch])
        elif ch in self._tier_keys:
            self.set_tier(self._tier_keys[ch])

    def _step(self, delta: int) -> None:
        if self._typing() or not self._visible:
            return
        i = self._visible.index(self._rec) if self._rec in self._visible else 0
        j = min(max(i + delta, 0), len(self._visible) - 1)
        self.tree.selection_set(self._visible[j].key)
        self.tree.see(self._visible[j].key)

    def _next_unlabelled(self, after: StrikeRecord) -> StrikeRecord | None:
        if after not in self._visible:
            return None
        for r in self._visible[self._visible.index(after) + 1:]:
            if self.labels.get(r.key) is None and r.clip_path is not None:
                return r
        return None

    def set_label(self, name: str) -> None:
        rec = self._rec
        if rec is None:
            return
        self.save_note()
        self.labels.set(rec.key, label=name)
        self.status.set(f"{rec.id}: {name.replace('_', ' ')}")
        self.refresh_list(keep=self._next_unlabelled(rec) or rec)       # on to the next one still to do

    def set_tier(self, tier: str) -> None:
        if self._rec is None:
            return
        self.save_note()
        self.labels.set(self._rec.key, tier=tier)
        self.status.set(f"{self._rec.id}: look grade {tier}")
        self.refresh_list(keep=self._rec)

    def clear_label(self) -> None:
        if self._rec is None:
            return
        self.labels.clear(self._rec.key)
        self.status.set(f"{self._rec.id}: label cleared")
        self.refresh_list(keep=self._rec)

    def save_note(self) -> None:
        key = self._note_for
        if key is None:
            return
        text = self.note_var.get().strip()
        if text == ((self.labels.get(key) or {}).get("note") or ""):
            return
        self.labels.set(key, note=text)
        rec = next((r for r in self.data.records if r.key == key), None)
        if rec is not None and rec is self._rec:
            self._show_controls(rec)

    def play(self) -> None:
        rec = self._rec
        if rec is None or rec.clip_path is None:
            return
        if not audio_out.is_available():
            self.status.set("No audio output available on this machine.")
            return
        x, fs = load_wav(rec.clip_path)
        audio_out.play(x, fs)

    def _show_controls(self, rec: StrikeRecord | None) -> None:
        lab = self.labels.get(rec.key) if rec else None
        if rec is None:
            self.cur_label_var.set("")
        elif lab and (lab.get("label") or lab.get("tier")):
            bits = [(lab.get("label") or "no class yet").replace("_", " ")]
            if lab.get("tier"):
                bits.append(f"look grade {lab['tier']}")
            self.cur_label_var.set("Your label:  " + "  -  ".join(bits))
            self.cur_label.configure(foreground=OK)
        else:
            self.cur_label_var.set("Not labelled yet")
            self.cur_label.configure(foreground=FG_DIM)
        self._note_for = rec.key if rec else None
        self.note_var.set((lab or {}).get("note") or "")

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
        self._show_plot(rec)
        self._show_info(rec)
        self._show_controls(rec)

    def _show_plot(self, rec: StrikeRecord | None) -> None:
        if rec is None:
            self.plot.clear()
            return
        cur = self.data.curves.get(rec.key, {})
        try:
            wave = self.data.waveform(rec)
        except Exception:  # noqa: BLE001 - an unreadable clip shows an empty plot, not a crash
            wave = None
        draw_strike_overview(self.plot.figure, wave, cur.get("spec"), cur.get("env"), self.data.reference,
                             title=f"{rec.session}  {rec.id}")
        self.plot.canvas.draw_idle()

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
