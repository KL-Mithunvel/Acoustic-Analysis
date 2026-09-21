"""Per-video snippet sidecars: the slicing work, saved next to the video.

Cutting a long take into labelled snippets is not a one-sitting job, and the
dataset itself is the wrong place to keep work in progress - an unfinished,
unlabelled snippet has no business in the training data. So the in-progress
set lives beside the source file as ``<video>.snippets.json`` and is only
promoted into the database when the operator saves.

Keeping it next to the video (rather than in ``data/``) means the work travels
with the footage: copy the video to another machine and the cuts come along.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..segments import SnippetSet

SIDECAR_SUFFIX = ".snippets.json"


def sidecar_path(media_path) -> Path:
    """``C:/clips/tiles.mp4`` -> ``C:/clips/tiles.mp4.snippets.json``.

    Appended to the full name rather than replacing the extension, so
    ``tiles.mp4`` and ``tiles.mov`` shot in the same session do not collide.
    """
    p = Path(media_path)
    return p.with_name(p.name + SIDECAR_SUFFIX)


def save_snippets(media_path, snippet_set: SnippetSet) -> Path:
    """Write the sidecar. Returns its path.

    Written to a temporary file and moved into place, so an interrupted save
    cannot leave a truncated JSON file that fails to load next time - which
    would silently lose an afternoon of cutting.
    """
    path = sidecar_path(media_path)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snippet_set.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def load_snippets(media_path) -> SnippetSet | None:
    """Read the sidecar, or None when there is none.

    A corrupt sidecar raises, rather than being treated as "none": silently
    starting from an empty set would look identical to losing the work.
    """
    path = sidecar_path(media_path)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not readable JSON: {exc}") from exc
    return SnippetSet.from_dict(payload)


def has_snippets(media_path) -> bool:
    return sidecar_path(media_path).is_file()
