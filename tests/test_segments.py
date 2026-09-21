"""segments.py - the snippet model and the rules about a valid snippet set."""

from __future__ import annotations

import pytest

from acoustic_analysis.segments import (
    Segment,
    SnippetSet,
    add,
    apply_labels,
    at_time,
    find_overlap,
    remove,
    renumber,
    snap_to_onsets,
    summary,
)


def seg(start, end, **kw) -> Segment:
    return Segment(start_s=start, end_s=end, **kw)


# -- Segment ---------------------------------------------------------------
def test_segment_rejects_a_backwards_or_negative_range():
    with pytest.raises(ValueError):
        seg(2.0, 1.0)
    with pytest.raises(ValueError):
        seg(1.0, 1.0)
    with pytest.raises(ValueError):
        seg(-0.5, 1.0)


def test_duration_and_contains():
    s = seg(1.0, 1.7)
    assert s.duration_s == pytest.approx(0.7)
    assert s.contains(1.0) and s.contains(1.69)
    assert not s.contains(1.7)   # half-open, so touching snippets share nothing


def test_labelled_needs_both_axes():
    assert not seg(0, 1, grade="3A").labelled
    assert not seg(0, 1, defect="cracked").labelled
    assert seg(0, 1, grade="3A", defect="cracked").labelled


def test_overlap_is_shared_duration_not_touching():
    assert seg(0, 1).overlaps(seg(0.5, 1.5))
    assert not seg(0, 1).overlaps(seg(1.0, 2.0))
    assert seg(0, 3).overlaps(seg(1, 2))   # fully contained


def test_clamped_fits_inside_the_recording():
    out = seg(9.0, 12.0).clamped(10.0)
    assert out.start_s == pytest.approx(9.0)
    assert out.end_s == pytest.approx(10.0)


def test_segment_round_trips_through_a_dict():
    s = seg(1.0, 1.5, grade="4", defect="good", notes="third tap", onset_s=1.03, saved=True)
    back = Segment.from_dict(s.to_dict())
    assert (back.start_s, back.end_s, back.grade, back.defect) == (1.0, 1.5, "4", "good")
    assert back.onset_s == pytest.approx(1.03)
    assert back.saved is True


# -- list operations -------------------------------------------------------
def test_renumber_orders_by_time_and_numbers_from_one():
    items = renumber([seg(2.0, 2.5), seg(0.5, 1.0), seg(1.2, 1.4)])
    assert [s.sid for s in items] == [1, 2, 3]
    assert [round(s.start_s, 1) for s in items] == [0.5, 1.2, 2.0]


def test_add_inserts_in_order_and_refuses_an_overlap():
    items = add(add([], seg(1.0, 1.5)), seg(0.1, 0.4))
    assert [round(s.start_s, 1) for s in items] == [0.1, 1.0]
    with pytest.raises(ValueError, match="overlaps"):
        add(items, seg(1.2, 1.9))


def test_add_clamps_to_the_recording_when_given_a_duration():
    items = add([], seg(9.5, 20.0), duration_s=10.0)
    assert items[0].end_s == pytest.approx(10.0)


def test_remove_and_renumber_close_the_gap():
    items = add(add(add([], seg(0, 1)), seg(2, 3)), seg(4, 5))
    items = remove(items, 2)
    assert [s.sid for s in items] == [1, 2]
    assert [round(s.start_s) for s in items] == [0, 4]


def test_find_overlap_and_at_time():
    items = renumber([seg(0, 1), seg(2, 3)])
    assert find_overlap(items, seg(0.5, 2.5)) is items[0]
    assert find_overlap(items, seg(1.2, 1.8)) is None
    assert at_time(items, 2.5) is items[1]
    assert at_time(items, 1.5) is None


# -- snapping --------------------------------------------------------------
def test_snap_moves_the_whole_window_onto_the_nearest_strike():
    s = seg(1.04, 1.74)
    out = snap_to_onsets(s, [0.2, 1.0, 2.0], max_shift_s=0.15)
    assert out.start_s == pytest.approx(1.0)
    assert out.duration_s == pytest.approx(s.duration_s)   # length preserved
    assert out.onset_s == pytest.approx(1.0)


def test_snap_uses_the_detected_onset_when_the_segment_has_one():
    # Window starts 30 ms before its strike; snapping must align the strike,
    # not the window edge, or every auto-cut would drift by the pre-roll.
    s = seg(0.97, 1.67, onset_s=1.0)
    out = snap_to_onsets(s, [1.02], max_shift_s=0.15)
    assert out.onset_s == pytest.approx(1.02)
    assert out.start_s == pytest.approx(0.99)


def test_snap_refuses_to_move_too_far_or_with_nothing_to_snap_to():
    s = seg(5.0, 5.7)
    assert snap_to_onsets(s, [1.0], max_shift_s=0.15) is s
    assert snap_to_onsets(s, [], max_shift_s=0.15) is s


def test_snap_never_produces_a_negative_start():
    out = snap_to_onsets(seg(0.02, 0.72), [0.0], max_shift_s=0.15)
    assert out.start_s >= 0.0


# -- labels and summary ----------------------------------------------------
def test_apply_labels_touches_only_the_named_rows():
    items = renumber([seg(0, 1), seg(2, 3), seg(4, 5)])
    assert apply_labels(items, [1, 3], grade="3A") == 2
    assert [s.grade for s in items] == ["3A", "", "3A"]


def test_apply_labels_leaves_the_other_axis_alone():
    items = renumber([seg(0, 1, grade="4", defect="good")])
    apply_labels(items, [1], grade="5")
    assert items[0].defect == "good"   # setting one axis must not wipe the other


def test_summary_counts_by_state_and_class():
    items = renumber([
        seg(0, 1, grade="3A", defect="good", saved=True),
        seg(2, 3, grade="3A", defect="cracked"),
        seg(4, 5),
    ])
    info = summary(items)
    assert info["total"] == 3
    assert info["labelled"] == 2
    assert info["saved"] == 1
    assert info["by_grade"] == {"3A": 2}
    assert info["by_defect"] == {"good": 1, "cracked": 1}


# -- SnippetSet ------------------------------------------------------------
def test_snippet_set_round_trips():
    original = SnippetSet(
        source="C:/clips/tiles.mp4", duration_s=63.5, sample_rate=48000,
        segments=renumber([seg(1, 2, grade="4", defect="good"), seg(5, 6)]),
    )
    back = SnippetSet.from_dict(original.to_dict())
    assert back.source == original.source
    assert back.sample_rate == 48000
    assert [s.sid for s in back.segments] == [1, 2]
    assert back.segments[0].grade == "4"


def test_snippet_set_refuses_a_newer_schema():
    # Loading a future file by ignoring the fields it does not know would
    # silently drop work, so it is an error instead.
    with pytest.raises(ValueError, match="newer"):
        SnippetSet.from_dict({"schema": 99, "source": "x", "segments": []})
