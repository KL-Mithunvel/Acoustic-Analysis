"""Loader for ``docs/EXPLAIN.md`` - the text behind every in-app "?" panel.

The file is a sequence of blocks headed ``## key: Title``. This module parses it
into ``{key: (title, body)}`` and is the only place the GUI gets that text, so
the content stays editable without touching code.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..config import repo_root

_HEADER = re.compile(r"^##\s+([A-Za-z0-9_-]+)\s*:\s*(.+?)\s*$")
_DEFAULT_PATH = repo_root() / "docs" / "EXPLAIN.md"


def load_explanations(path: str | Path | None = None) -> dict[str, tuple[str, str]]:
    """Return ``{key: (title, body)}`` from EXPLAIN.md. Missing file -> ``{}``."""
    md_path = Path(path) if path is not None else _DEFAULT_PATH
    if not md_path.is_file():
        return {}

    entries: dict[str, tuple[str, str]] = {}
    key: str | None = None
    title = ""
    body: list[str] = []

    def flush() -> None:
        if key is not None:
            entries[key] = (title, "\n".join(body).strip())

    for line in md_path.read_text(encoding="utf-8").splitlines():
        m = _HEADER.match(line)
        if m:
            flush()
            key, title, body = m.group(1), m.group(2), []
        elif key is not None:
            body.append(line)
    flush()
    return entries


class Explainer:
    """Small facade the widgets use: ``Explainer().text('spectrum')``."""

    def __init__(self, path: str | Path | None = None):
        self._entries = load_explanations(path)

    def has(self, key: str) -> bool:
        return key in self._entries

    def title(self, key: str) -> str:
        return self._entries.get(key, (key, ""))[0]

    def body(self, key: str) -> str:
        return self._entries.get(key, ("", "No explanation for this yet."))[1]

    def text(self, key: str) -> str:
        title, body = self._entries.get(key, (key, "No explanation for this yet."))
        return f"{title}\n\n{body}" if body else title

    def keys(self) -> list[str]:
        return list(self._entries)

    def glossary(self) -> list[tuple[str, str]]:
        """``[(title, body), ...]`` sorted by title, for a glossary screen."""
        return sorted(self._entries.values(), key=lambda tb: tb[0].lower())
