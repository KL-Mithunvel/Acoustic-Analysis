"""Read a station data-collection session folder, read-only.

A session is what the Tile_Sorting Pi station writes while it records (``strikes.json``,
``events.jsonl``, ``clips/``, ``tiles/``, ``manifest.json``). Every file in it is covered by a
SHA-256 manifest, so this module only ever opens files for reading - labels go to
``io/label_store.py``, never into the session.

The two code bases stay independent: this reads the *files*, it imports nothing from the station.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

GROUPS = ("tile", "no_tile", "rest", "ambient")
GROUP_TEXT = {
    "tile": "Tile struck",
    "no_tile": "Striker alone (no tile)",
    "rest": "Striker lowered to rest",
    "ambient": "Room noise",
}


@dataclass
class StrikeRecord:
    session: str
    id: str                              # S0001 / A0001
    kind: str                            # strike | ambient
    source: str                          # tof | manual | rest | operator ...
    group: str                           # one of GROUPS
    t: float | None = None               # station wall clock, seconds
    nano_ms: int | None = None
    tof_mm: int | None = None
    tile_present: bool | None = None
    tile_id: str | None = None
    retract_to_strike_ms: float | None = None
    run_type: str = ""
    session_note: str = ""
    session_labels: dict = field(default_factory=dict)   # the station's own condition/defect/tier
    clip_path: Path | None = None
    retract_clip_path: Path | None = None
    picture_path: Path | None = None
    camera: dict | None = None
    acoustic: dict | None = None
    final: dict | None = None

    @property
    def key(self) -> str:
        """Stable identity across sessions - what a label is attached to."""
        return f"{self.session}/{self.id}"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _tile_messages(events: Path) -> dict[str, dict[str, dict]]:
    """``{tile_id: {"camera": ..., "acoustic": ..., "final": ...}}``, the last message of each kind
    winning. A damaged line is skipped, never fatal."""
    out: dict[str, dict[str, dict]] = {}
    try:
        lines = events.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            e = json.loads(line)
            topic = str(e.get("topic", ""))
            payload = e["payload"]
        except (ValueError, KeyError, TypeError):
            continue
        parts = topic.split("/")
        if len(parts) >= 3 and parts[0] == "tile":
            tile_id, rest = parts[1], "/".join(parts[2:])
            kind = {"camera/result": "camera", "acoustic/result": "acoustic", "final": "final"}.get(rest)
            if kind and isinstance(payload, dict):
                out.setdefault(tile_id, {})[kind] = payload
    return out


def _group(ev: dict) -> str:
    cond = (ev.get("labels") or {}).get("condition")
    if ev.get("kind") == "ambient" or cond == "ambient":
        return "ambient"
    if cond == "no_tile":
        return "no_tile"
    if ev.get("source") == "rest":
        return "rest"
    return "tile"


def list_sessions(root: str | Path) -> list[Path]:
    """Session folders under ``root`` (those with a ``strikes.json``), oldest first."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "strikes.json").is_file())


def load_session(folder: str | Path) -> list[StrikeRecord]:
    folder = Path(folder)
    events = _read_json(folder / "strikes.json")
    if not isinstance(events, list):
        return []
    manifest = _read_json(folder / "manifest.json") or {}
    msgs = _tile_messages(folder / "events.jsonl")
    by_id = {e.get("id"): e for e in events if isinstance(e, dict)}
    records: list[StrikeRecord] = []
    for ev in events:
        if not isinstance(ev, dict) or ev.get("kind") not in ("strike", "ambient"):
            continue                                  # retractions are attached to their strike below
        rid, kind = str(ev["id"]), ev["kind"]
        clip = folder / "clips" / f"{rid}_{kind}.wav"
        tile_id = ev.get("tile_id")
        retract = by_id.get(ev.get("cycle")) if kind == "strike" else None
        retract_clip = None
        if retract and retract.get("kind") == "retract":
            cand = folder / "clips" / f"{retract['id']}_retract.wav"
            retract_clip = cand if cand.is_file() else None
        picture = None
        if tile_id:
            for ext in (".jpg", ".jpeg", ".png"):
                cand = folder / "tiles" / f"{tile_id}{ext}"
                if cand.is_file():
                    picture = cand
                    break
        m = msgs.get(tile_id, {}) if tile_id else {}
        records.append(StrikeRecord(
            session=folder.name, id=rid, kind=kind, source=str(ev.get("source", "")), group=_group(ev),
            t=ev.get("t"), nano_ms=ev.get("nano_ms"), tof_mm=ev.get("tof_mm"),
            tile_present=ev.get("tile_present"), tile_id=tile_id,
            retract_to_strike_ms=ev.get("retract_to_strike_ms"),
            run_type=str(manifest.get("run_type", "")), session_note=str(manifest.get("note", "")),
            session_labels=dict(ev.get("labels") or {}),
            clip_path=clip if clip.is_file() else None, retract_clip_path=retract_clip,
            picture_path=picture, camera=m.get("camera"), acoustic=m.get("acoustic"), final=m.get("final"),
        ))
    return records


def load_all(root: str | Path) -> list[StrikeRecord]:
    out: list[StrikeRecord] = []
    for folder in list_sessions(root):
        out.extend(load_session(folder))
    return out
