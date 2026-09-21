"""The snippet model: one labelled time range inside a longer recording.

Pure data and list arithmetic - no numpy, no files, no Tk. The Slice screen
edits a ``list[Segment]`` through these functions and only touches disk when
the operator saves, so every rule about what a valid snippet set looks like is
testable without a GUI or a video.

Two independent labels per snippet, by the owner's decision (2026-09-20):

``grade``   cosmetic tier of the tile - 3A / 3B / 4 / 5, the same tiers the
            camera station classifies into.
``defect``  what is physically wrong with it - good / cracked / corner_broken
            / other_defect.

They are separate fields rather than one merged class because a grade-4 tile
can be intact and a grade-3A tile can be cracked; merging them would make the
exported dataset unable to answer either question cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

SCHEMA_VERSION = 1


@dataclass
class Segment:
    """One snippet: a time range in the source recording, plus its labels.

    Times are seconds from the start of the *recording*, not the video's
    timeline offset, so a snippet stays valid if the video is later re-encoded.
    ``sid`` is a display number assigned by :func:`renumber`; it is not an
    identity that survives editing and is not what the database keys on.
    """

    start_s: float
    end_s: float
    grade: str = ""
    defect: str = ""
    notes: str = ""
    sid: int = 0
    onset_s: float | None = None  # detected strike, when it came from the detector
    saved: bool = False           # already written to the dataset

    def __post_init__(self) -> None:
        if self.end_s <= self.start_s:
            raise ValueError(
                f"Segment: end_s ({self.end_s}) must be after start_s ({self.start_s})"
            )
        if self.start_s < 0:
            raise ValueError(f"Segment: start_s must be >= 0, got {self.start_s}")

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def labelled(self) -> bool:
        """Both fields set. A half-labelled snippet is not exportable - it
        would land in the CSV as a row the trainer cannot use."""
        return bool(self.grade) and bool(self.defect)

    def overlaps(self, other: "Segment") -> bool:
        """Touching end-to-start is not an overlap; sharing any duration is."""
        return self.start_s < other.end_s and other.start_s < self.end_s

    def contains(self, t_s: float) -> bool:
        return self.start_s <= t_s < self.end_s

    def clamped(self, duration_s: float) -> "Segment":
        """A copy fitted inside a recording of ``duration_s``."""
        start = max(0.0, min(self.start_s, duration_s))
        end = max(start + 1e-6, min(self.end_s, duration_s))
        return replace(self, start_s=start, end_s=end)

    def to_dict(self) -> dict:
        return {
            "start_s": round(self.start_s, 6),
            "end_s": round(self.end_s, 6),
            "grade": self.grade,
            "defect": self.defect,
            "notes": self.notes,
            "onset_s": None if self.onset_s is None else round(self.onset_s, 6),
            "saved": self.saved,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Segment":
        return cls(
            start_s=float(d["start_s"]),
            end_s=float(d["end_s"]),
            grade=str(d.get("grade", "")),
            defect=str(d.get("defect", "")),
            notes=str(d.get("notes", "")),
            onset_s=None if d.get("onset_s") is None else float(d["onset_s"]),
            saved=bool(d.get("saved", False)),
        )


@dataclass
class SnippetSet:
    """Every snippet cut from one source file, plus what it was cut from.

    This is what the sidecar JSON holds, so closing the app mid-video and
    coming back later resumes exactly where the work stopped.
    """

    source: str
    duration_s: float = 0.0
    sample_rate: int = 0
    segments: list[Segment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "source": self.source,
            "duration_s": round(self.duration_s, 4),
            "sample_rate": int(self.sample_rate),
            "segments": [s.to_dict() for s in self.segments],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SnippetSet":
        schema = int(d.get("schema", SCHEMA_VERSION))
        if schema > SCHEMA_VERSION:
            raise ValueError(
                f"SnippetSet: sidecar schema {schema} is newer than this build "
                f"understands ({SCHEMA_VERSION}) - update the app rather than "
                f"letting it silently drop fields"
            )
        return cls(
            source=str(d.get("source", "")),
            duration_s=float(d.get("duration_s", 0.0)),
            sample_rate=int(d.get("sample_rate", 0)),
            segments=renumber([Segment.from_dict(s) for s in d.get("segments", [])]),
        )


# -- list operations -------------------------------------------------------
def renumber(segments: list[Segment]) -> list[Segment]:
    """Sort by start time and number 1..n, so the snippet numbers an operator
    reads off the table always run in the order they are heard."""
    ordered = sorted(segments, key=lambda s: (s.start_s, s.end_s))
    for i, seg in enumerate(ordered, start=1):
        seg.sid = i
    return ordered


def find_overlap(segments: list[Segment], candidate: Segment) -> Segment | None:
    """The first existing segment ``candidate`` would overlap, if any.

    Overlapping snippets are rejected rather than merged: the same strike
    exported twice under two labels is worse for a training set than a gap.
    """
    for seg in segments:
        if seg is not candidate and seg.overlaps(candidate):
            return seg
    return None


def add(segments: list[Segment], candidate: Segment, duration_s: float = 0.0) -> list[Segment]:
    """Return a new list with ``candidate`` inserted in time order.

    Raises ValueError if it would overlap an existing snippet.
    """
    if duration_s > 0:
        candidate = candidate.clamped(duration_s)
    clash = find_overlap(segments, candidate)
    if clash is not None:
        raise ValueError(
            f"snippet {candidate.start_s:.3f}-{candidate.end_s:.3f}s overlaps "
            f"#{clash.sid} ({clash.start_s:.3f}-{clash.end_s:.3f}s)"
        )
    return renumber([*segments, candidate])


def remove(segments: list[Segment], sid: int) -> list[Segment]:
    return renumber([s for s in segments if s.sid != sid])


def at_time(segments: list[Segment], t_s: float) -> Segment | None:
    for seg in segments:
        if seg.contains(t_s):
            return seg
    return None


def snap_to_onsets(
    segment: Segment, onset_times: list[float], max_shift_s: float = 0.15
) -> Segment:
    """Pull a hand-drawn selection onto the nearest detected strike.

    Dragging a selection by eye lands the start a few tens of milliseconds off,
    which shifts every time-referenced feature by that much. Snapping keeps the
    drag rough and the cut exact. The segment keeps its length - the whole
    window moves - and if no onset is within ``max_shift_s`` it is returned
    unchanged rather than yanked somewhere wrong.
    """
    if not onset_times:
        return segment
    # Snap whatever currently marks the strike: the detected onset if this
    # segment has one, otherwise the start of the hand-drawn selection.
    target = segment.onset_s if segment.onset_s is not None else segment.start_s
    nearest = min(onset_times, key=lambda t: abs(t - target))
    shift = nearest - target
    if abs(shift) > max_shift_s or shift == 0.0:
        return segment
    start = max(0.0, segment.start_s + shift)
    return replace(
        segment,
        start_s=start,
        end_s=start + segment.duration_s,
        onset_s=nearest,
    )


def apply_labels(
    segments: list[Segment], sids, grade: str | None = None, defect: str | None = None
) -> int:
    """Set one or both labels on the given snippets. Returns how many changed.

    ``None`` leaves a field alone, so "set every selected row to 3A" does not
    wipe the defect labels already entered.
    """
    wanted = set(sids)
    n = 0
    for seg in segments:
        if seg.sid not in wanted:
            continue
        if grade is not None:
            seg.grade = grade
        if defect is not None:
            seg.defect = defect
        n += 1
    return n


def summary(segments: list[Segment]) -> dict:
    """Counts for the status line: total, labelled, saved, and per-class
    tallies - the numbers that tell an operator whether a video is finished."""
    by_grade: dict[str, int] = {}
    by_defect: dict[str, int] = {}
    for seg in segments:
        if seg.grade:
            by_grade[seg.grade] = by_grade.get(seg.grade, 0) + 1
        if seg.defect:
            by_defect[seg.defect] = by_defect.get(seg.defect, 0) + 1
    return {
        "total": len(segments),
        "labelled": sum(1 for s in segments if s.labelled),
        "saved": sum(1 for s in segments if s.saved),
        "total_duration_s": round(sum(s.duration_s for s in segments), 3),
        "by_grade": by_grade,
        "by_defect": by_defect,
    }
