"""The clip library: a real folder tree on disk with safe file operations.

Everything the app records or imports lives under one root folder
(``paths.recordings_dir``). This module is the only place that renames, moves,
or deletes clips, so the three things that must stay together - the ``.wav``,
its ``.wav.json`` sidecar, and the path stored in the dataset database - cannot
drift apart. Pure file logic, no GUI: tested against a temp directory.

Safety rules:
* every path is resolved and must stay inside the root (no ``..`` escapes);
* nothing is overwritten - a name clash is an error, not a silent replace;
* delete moves to ``<root>/.trash`` and can be undone, it never unlinks.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

TRASH_DIR = ".trash"
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class LibraryError(Exception):
    """A refused operation (bad name, clash, outside root). Message is user-facing."""


@dataclass(frozen=True)
class Entry:
    name: str
    path: Path
    is_dir: bool
    size_bytes: int = 0


@dataclass
class _Undo:
    kind: str                 # "move" | "delete" | "rename" | "mkdir"
    src: Path                 # where it was
    dst: Path                 # where it went


def clean_name(name: str) -> str:
    """Validate a user-typed file/folder name; return it stripped."""
    name = name.strip().rstrip(".")
    if not name:
        raise LibraryError("name cannot be empty")
    if _BAD_NAME.search(name) or name in (".", ".."):
        raise LibraryError('name cannot contain  < > : " / \\ | ? *')
    if name == TRASH_DIR:
        raise LibraryError("that name is reserved")
    return name


class Library:
    def __init__(self, root, on_path_changed=None):
        """``on_path_changed(old: Path, new: Path | None)`` is called after every
        wav move/rename (``new`` is ``None`` when a clip is deleted) so the
        dataset can follow. For folders it is called once per wav inside."""
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._on_path_changed = on_path_changed
        self._undo: list[_Undo] = []

    # -- paths ---------------------------------------------------------
    def resolve(self, rel) -> Path:
        """Absolute path for ``rel`` (relative to root, or absolute inside it)."""
        p = Path(rel)
        p = (p if p.is_absolute() else self.root / p).resolve()
        if p != self.root and self.root not in p.parents:
            raise LibraryError("path is outside the library")
        return p

    def relative(self, path) -> Path:
        return self.resolve(path).relative_to(self.root)

    @staticmethod
    def _sidecar(wav: Path) -> Path:
        return wav.with_suffix(wav.suffix + ".json")

    # -- browsing ------------------------------------------------------
    def list(self, folder="") -> list[Entry]:
        """Sub-folders first, then ``.wav`` files, each alphabetical."""
        d = self.resolve(folder)
        if not d.is_dir():
            raise LibraryError(f"not a folder: {folder}")
        dirs, files = [], []
        for p in d.iterdir():
            if p.name == TRASH_DIR:
                continue
            if p.is_dir():
                dirs.append(Entry(p.name, p, True))
            elif p.suffix.lower() == ".wav":
                files.append(Entry(p.name, p, False, p.stat().st_size))
        key = lambda e: e.name.lower()  # noqa: E731
        return sorted(dirs, key=key) + sorted(files, key=key)

    def folders(self) -> list[Path]:
        """Every folder under root (relative paths, root itself as ``.``)."""
        out = [Path(".")]
        for p in sorted(self.root.rglob("*")):
            if p.is_dir() and TRASH_DIR not in p.relative_to(self.root).parts:
                out.append(p.relative_to(self.root))
        return out

    def unique_name(self, folder, stem: str, suffix: str = ".wav") -> Path:
        """First free ``stem``, ``stem-2``, ``stem-3`` ... inside ``folder``."""
        d = self.resolve(folder)
        cand = d / f"{stem}{suffix}"
        n = 2
        while cand.exists():
            cand = d / f"{stem}-{n}{suffix}"
            n += 1
        return cand

    # -- operations ------------------------------------------------------
    def make_folder(self, parent, name: str) -> Path:
        dst = self.resolve(parent) / clean_name(name)
        if dst.exists():
            raise LibraryError(f"'{dst.name}' already exists")
        dst.mkdir(parents=True)
        self._undo.append(_Undo("mkdir", dst, dst))
        return dst

    def rename(self, path, new_name: str) -> Path:
        src = self.resolve(path)
        if src == self.root:
            raise LibraryError("cannot rename the library root")
        new_name = clean_name(new_name)
        if src.is_file() and src.suffix and not Path(new_name).suffix:
            new_name += src.suffix            # typing "tile7" keeps ".wav"
        dst = src.with_name(new_name)
        if dst == src:
            return src
        self._relocate(src, dst, "rename")
        return dst

    def move(self, path, dest_folder) -> Path:
        src = self.resolve(path)
        folder = self.resolve(dest_folder)
        if not folder.is_dir():
            raise LibraryError("destination is not a folder")
        if src.is_dir() and (folder == src or src in folder.parents):
            raise LibraryError("cannot move a folder into itself")
        dst = folder / src.name
        if dst == src:
            return src
        self._relocate(src, dst, "move")
        return dst

    def delete(self, path) -> Path:
        """Move to ``.trash`` (undoable). Returns the trash location."""
        src = self.resolve(path)
        if src == self.root:
            raise LibraryError("cannot delete the library root")
        trash = self.root / TRASH_DIR
        trash.mkdir(exist_ok=True)
        dst = trash / src.name
        n = 2
        while dst.exists():
            dst = trash / f"{src.stem}-{n}{src.suffix}"
            n += 1
        self._relocate(src, dst, "delete", notify_deleted=True)
        return dst

    def empty_trash(self) -> int:
        trash = self.root / TRASH_DIR
        if not trash.is_dir():
            return 0
        n = sum(1 for _ in trash.iterdir())
        shutil.rmtree(trash)
        self._undo = [u for u in self._undo if u.kind != "delete"]
        return n

    def can_undo(self) -> bool:
        return bool(self._undo)

    def undo(self) -> str:
        """Reverse the last operation; returns a one-line description."""
        if not self._undo:
            raise LibraryError("nothing to undo")
        u = self._undo.pop()
        if u.kind == "mkdir":
            try:
                u.dst.rmdir()
            except OSError as exc:
                self._undo.append(u)
                raise LibraryError("folder is no longer empty") from exc
            return f"removed folder {u.dst.name}"
        if not u.dst.exists():
            raise LibraryError("file to restore is gone")
        if u.src.exists():
            self._undo.append(u)
            raise LibraryError(f"'{u.src.name}' now exists - cannot restore over it")
        self._relocate(u.dst, u.src, u.kind, record=False)
        return f"undid {u.kind} of {u.src.name}"

    # -- internals -------------------------------------------------------
    def _relocate(self, src: Path, dst: Path, kind: str, record: bool = True,
                  notify_deleted: bool = False) -> None:
        if dst.exists():
            raise LibraryError(f"'{dst.name}' already exists")
        if src.is_dir():
            moves = [(w, dst / w.relative_to(src)) for w in sorted(src.rglob("*.wav"))]
        else:
            moves = [(src, dst)]
        if src.is_file() and self._sidecar(src).exists():
            side_dst = self._sidecar(dst)
            if side_dst.exists():
                raise LibraryError(f"'{side_dst.name}' already exists")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self._sidecar(src)), str(side_dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))   # a folder carries its sidecars with it
        if record:
            self._undo.append(_Undo(kind, src, dst))
        if self._on_path_changed:
            for old, new in moves:
                self._on_path_changed(old, None if notify_deleted else new)
