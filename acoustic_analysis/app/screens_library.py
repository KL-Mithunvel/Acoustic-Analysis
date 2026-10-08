"""Library screen: browse, rename, move and delete clips like a file manager.

All real work is in ``io/library.Library`` (safe paths, sidecars, database
follow-along, undo) - this screen only maps clicks, keys and drags onto it.
Folders here are real folders on disk, so Explorer sees the same tree.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from ..io.library import LibraryError
from ..io.wavstore import load_clip
from .screens import _Base
from .state import ClipData
from .theme import BAD, FG_DIM, OK, WARN

_LABEL_COLOURS = {"good": OK, "cracked": BAD, "corner_broken": BAD, "other_defect": WARN,
                  "retest": WARN, "discard": FG_DIM}
_DRAG_PX = 6


class LibraryScreen(_Base):
    title = "Library"

    def __init__(self, master, ctx):
        super().__init__(master, ctx)
        self.lib = ctx.library
        self._folder = Path(".")
        self._drag = None

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        for text, cmd, style in (
            ("New folder", self.new_folder, "Accent.TButton"),
            ("Rename  F2", self.rename, "TButton"),
            ("Move to...", self.move_dialog, "TButton"),
            ("Delete  Del", self.delete, "Danger.TButton"),
            ("Undo  Ctrl+Z", self.undo, "TButton"),
        ):
            ttk.Button(bar, text=text, command=cmd, style=style).pack(side="left", padx=(0, 6))
        ttk.Button(bar, text="Open in Analyze  Enter", command=self.open_selected).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.folders = ttk.Treeview(body, show="tree", selectmode="browse", height=18)
        self.folders.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        self.folders.column("#0", width=220)
        self.folders.bind("<<TreeviewSelect>>", self._on_folder)

        cols = ("label", "length", "size")
        self.files = ttk.Treeview(body, columns=cols, show="tree headings", selectmode="extended")
        self.files.grid(row=0, column=1, sticky="nsew")
        self.files.heading("#0", text="name")
        self.files.column("#0", width=300)
        for col, w, txt in (("label", 130, "label"), ("length", 80, "length"), ("size", 80, "size")):
            self.files.heading(col, text=txt)
            self.files.column(col, width=w, anchor="center")
        for name, colour in _LABEL_COLOURS.items():
            self.files.tag_configure(name, foreground=colour)
        self.files.tag_configure("dir", foreground=FG_DIM)
        vsb = ttk.Scrollbar(body, orient="vertical", command=self.files.yview)
        self.files.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=2, sticky="ns")

        self.status = tk.StringVar(
            value="Drag clips onto a folder on the left to move them. Everything is undoable.")
        ttk.Label(self, textvariable=self.status, style="Dim.TLabel").pack(anchor="w", pady=(8, 0))

        self.files.bind("<Double-1>", self._on_double)
        self.files.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.files.bind("<B1-Motion>", self._drag_move)
        self.files.bind("<ButtonRelease-1>", self._drag_end)
        for w in (self.files, self.folders):
            w.bind("<F2>", lambda _e: self.rename())
            w.bind("<Delete>", lambda _e: self.delete())
            w.bind("<Control-z>", lambda _e: self.undo())
            w.bind("<Return>", lambda _e: self.open_selected())

    # -- display -------------------------------------------------------
    def soft_keys(self):
        return [("New folder", self.new_folder), ("Rename", self.rename),
                ("Move to...", self.move_dialog), ("Undo", self.undo)]

    def refresh(self):
        self._fill_folders()
        self._fill_files()

    def _fill_folders(self):
        open_ids = {i for i in self.folders.get_children("") if self.folders.item(i, "open")}
        self.folders.delete(*self.folders.get_children())
        for rel in self.lib.folders():
            iid = rel.as_posix()
            parent = "" if iid == "." else (rel.parent.as_posix())
            name = "All recordings" if iid == "." else rel.name
            self.folders.insert(parent, "end", iid=iid, text=name, open=True)
        for i in open_ids:
            if self.folders.exists(i):
                self.folders.item(i, open=True)
        here = self._folder.as_posix()
        if self.folders.exists(here):
            self.folders.selection_set(here)
        else:
            self._folder = Path(".")
            self.folders.selection_set(".")

    def _labels_by_path(self) -> dict[str, str]:
        out = {}
        for c in self.ctx.db.list_clips():
            lab = (c.get("label") or {}).get("label")
            if lab:
                out[str(Path(c["path"]).resolve())] = lab
        return out

    def _fill_files(self):
        self.files.delete(*self.files.get_children())
        labels = self._labels_by_path()
        try:
            entries = self.lib.list(self._folder)
        except LibraryError:
            return
        for e in entries:
            rel = self.lib.relative(e.path).as_posix()
            if e.is_dir:
                n = sum(1 for _ in e.path.rglob("*.wav"))
                self.files.insert("", "end", iid=rel, text=f"▸  {e.name}",
                                  values=("", f"{n} clips", ""), tags=("dir",))
            else:
                lab = labels.get(str(e.path.resolve()), "")
                length = ""
                try:
                    import soundfile as sf
                    info = sf.info(str(e.path))
                    length = f"{info.frames / info.samplerate:.2f} s"
                except Exception:  # noqa: BLE001 - unreadable file still listed
                    pass
                self.files.insert("", "end", iid=rel, text=f"♪  {e.name}",
                                  values=(lab or "-", length, f"{e.size_bytes / 1024:.0f} KB"),
                                  tags=(lab,) if lab in _LABEL_COLOURS else ())
        if not entries:
            self.status.set("This folder is empty. Record in Collect, or drag clips here.")

    def _on_folder(self, _e=None):
        sel = self.folders.selection()
        if sel:
            self._folder = Path(sel[0])
            self._fill_files()

    def _selected(self) -> list[str]:
        return list(self.files.selection())

    # -- actions ----------------------------------------------------
    def _guard(self, fn, ok_msg: str):
        try:
            result = fn()
        except LibraryError as exc:
            self.status.set(f"Not done: {exc}")
            return None
        self.status.set(ok_msg)
        self.refresh()
        return result

    def new_folder(self):
        name = simpledialog.askstring("New folder", "Folder name:", parent=self)
        if name:
            self._guard(lambda: self.lib.make_folder(self._folder, name), f"Created folder '{name.strip()}'")

    def rename(self):
        sel = self._selected()
        if len(sel) != 1:
            self.status.set("Select one item to rename.")
            return
        old = Path(sel[0]).name
        name = simpledialog.askstring("Rename", "New name:", initialvalue=old, parent=self)
        if name:
            self._guard(lambda: self.lib.rename(sel[0], name), f"Renamed to '{name.strip()}'")

    def delete(self):
        sel = self._selected()
        if not sel:
            self.status.set("Select something to delete.")
            return
        def _do():
            for rel in sel:
                self.lib.delete(rel)
        self._guard(_do, f"Moved {len(sel)} item(s) to trash - press Ctrl+Z to undo.")

    def undo(self):
        self._guard(self.lib.undo, "Undone.")

    def move_dialog(self):
        sel = self._selected()
        if not sel:
            self.status.set("Select something to move.")
            return
        dest = _pick_folder(self, [f.as_posix() for f in self.lib.folders()])
        if dest is not None:
            self._move(sel, dest)

    def _move(self, rels: list[str], dest: str):
        def _do():
            for rel in rels:
                self.lib.move(rel, dest)
        label = "All recordings" if dest == "." else dest
        self._guard(_do, f"Moved {len(rels)} item(s) to {label}.")

    def open_selected(self):
        sel = [r for r in self._selected() if r.lower().endswith(".wav")]
        if not sel:
            return
        for rel in sel:
            path = self.lib.resolve(rel)
            try:
                samples, fs, meta = load_clip(path)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Open", f"{path.name}\n{exc}")
                continue
            idx = self.ctx.state.add_clip(ClipData(name=path.stem, samples=samples, fs=fs,
                                                   source="file", path=str(path), metadata=meta))
            self.ctx.service.submit(idx)
        self.ctx.navigate("Analyze")

    def _on_double(self, event):
        rel = self.files.identify_row(event.y)
        if not rel:
            return
        if self.files.tag_has("dir", rel):
            self._folder = Path(rel)
            self.refresh()
        else:
            self.open_selected()

    # -- drag and drop (files -> folder tree) ------------------------------
    def _drag_start(self, event):
        self._drag = (event.x_root, event.y_root, False)

    def _drag_move(self, event):
        if not self._drag:
            return
        x0, y0, active = self._drag
        if not active and abs(event.x_root - x0) + abs(event.y_root - y0) > _DRAG_PX:
            active = True
            self.files.configure(cursor="hand2")
            self.status.set("Drop on a folder on the left...")
        self._drag = (x0, y0, active)

    def _drag_end(self, event):
        drag, self._drag = self._drag, None
        self.files.configure(cursor="")
        if not drag or not drag[2]:
            return
        target = self.winfo_containing(event.x_root, event.y_root)
        sel = self._selected()
        if target is self.folders and sel:
            dest = self.folders.identify_row(event.y_root - self.folders.winfo_rooty())
            if dest:
                self._move(sel, dest)
                return
        self.status.set("Drag cancelled - drop onto a folder in the left list.")


def _pick_folder(parent, folders: list[str]) -> str | None:
    """Small modal list of folders; returns the chosen relative path or None."""
    top = tk.Toplevel(parent)
    top.title("Move to...")
    top.transient(parent.winfo_toplevel())
    top.geometry("320x360")
    box = tk.Listbox(top, exportselection=False, activestyle="none")
    for f in folders:
        box.insert("end", "All recordings" if f == "." else f)
    box.pack(fill="both", expand=True, padx=10, pady=(10, 6))
    result: dict = {"v": None}

    def ok(_e=None):
        if box.curselection():
            result["v"] = folders[box.curselection()[0]]
        top.destroy()

    row = ttk.Frame(top)
    row.pack(fill="x", padx=10, pady=(0, 10))
    ttk.Button(row, text="Move here", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(row, text="Cancel", command=top.destroy).pack(side="right", padx=(0, 6))
    box.bind("<Double-1>", ok)
    box.bind("<Return>", ok)
    top.grab_set()
    box.focus_set()
    parent.wait_window(top)
    return result["v"]
