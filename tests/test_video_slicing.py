"""The video-to-dataset path end to end.

Builds a real video file whose audio track holds taps at known times, then
drives the whole chain the Slice screen drives - extract, detect, cut, label,
save - and checks that what lands in the database is what went into the video.

These touch ffmpeg and the filesystem, so they are integration tests rather
than unit tests; they skip when ffmpeg is not installed.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import soundfile as sf

from acoustic_analysis import segments as segmod
from acoustic_analysis.config import load_config
from acoustic_analysis.dsp import segmentation as seg
from acoustic_analysis.io import snippets, videoaudio
from acoustic_analysis.io.dataset import Dataset
from acoustic_analysis.io.wavstore import save_clip
from acoustic_analysis.segments import Segment, SnippetSet
from tests.synth import make_tap_sequence

_FS = 48000
_TAPS = [0.6, 1.5, 2.4, 3.3]

pytestmark = pytest.mark.skipif(
    not videoaudio.is_available(), reason="ffmpeg not installed"
)


@pytest.fixture(scope="module")
def tap_video(tmp_path_factory):
    """A 4 s video with a test pattern for picture and four taps for sound."""
    tmp = tmp_path_factory.mktemp("video")
    wav = tmp / "track.wav"
    sf.write(wav, make_tap_sequence(_FS, _TAPS, duration_s=4.0).astype(np.float32),
             _FS, subtype="FLOAT")

    out = tmp / "taps.mp4"
    import subprocess

    subprocess.run(
        [videoaudio.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=4",
         "-i", str(wav), "-shortest",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         # PCM in an mp4 is unusual but keeps the taps bit-exact, so the
         # detector is tested against the signal and not against a codec.
         "-c:a", "pcm_s16le", str(out)],
        check=True, capture_output=True,
    )
    return out


# -- videoaudio ------------------------------------------------------------
def test_probe_reports_streams_and_duration(tap_video):
    meta = videoaudio.probe(tap_video)
    assert meta["has_audio"] and meta["has_video"]
    assert meta["duration_s"] == pytest.approx(4.0, abs=0.2)
    assert (meta["width"], meta["height"]) == (320, 240)


def test_extract_audio_returns_mono_float_at_the_asked_rate(tap_video, tmp_path):
    samples, fs, wav = videoaudio.extract_audio(tap_video, _FS, tmp_path / "cache")
    assert fs == _FS
    assert samples.ndim == 1
    assert samples.size == pytest.approx(4.0 * _FS, rel=0.05)
    assert wav.is_file()


def test_extract_audio_reuses_the_cache(tap_video, tmp_path):
    cache = tmp_path / "cache"
    _, _, first = videoaudio.extract_audio(tap_video, _FS, cache)
    stamp = first.stat().st_mtime_ns
    _, _, second = videoaudio.extract_audio(tap_video, _FS, cache)
    assert second == first
    assert second.stat().st_mtime_ns == stamp   # not re-decoded


def test_extract_audio_rejects_a_file_with_no_audio(tmp_path):
    silent = tmp_path / "silent.mp4"
    import subprocess

    subprocess.run(
        [videoaudio.ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)],
        check=True, capture_output=True,
    )
    with pytest.raises(ValueError, match="no audio stream"):
        videoaudio.extract_audio(silent, _FS, tmp_path / "cache")


def test_extract_frame_returns_png_bytes(tap_video):
    png = videoaudio.extract_frame_png(tap_video, 2.0, width=200)
    assert png and png[:4] == b"\x89PNG"


def test_extract_frame_of_a_missing_file_is_none_not_an_error():
    assert videoaudio.extract_frame_png("no_such_file.mp4", 1.0) is None


# -- sidecar ---------------------------------------------------------------
def test_sidecar_round_trips_beside_the_video(tap_video, tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"not really a video")
    original = SnippetSet(
        source=str(media), duration_s=4.0, sample_rate=_FS,
        segments=segmod.renumber([Segment(start_s=1.0, end_s=1.7, grade="3A", defect="good")]),
    )
    path = snippets.save_snippets(media, original)

    assert path.name == "clip.mp4.snippets.json"
    assert snippets.has_snippets(media)
    back = snippets.load_snippets(media)
    assert back.segments[0].grade == "3A"
    assert back.duration_s == pytest.approx(4.0)


def test_missing_sidecar_is_none_and_a_broken_one_raises(tmp_path):
    media = tmp_path / "x.mp4"
    media.write_bytes(b"x")
    assert snippets.load_snippets(media) is None

    snippets.sidecar_path(media).write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="readable JSON"):
        snippets.load_snippets(media)


# -- the whole chain -------------------------------------------------------
def test_video_becomes_labelled_dataset_rows(tap_video, tmp_path):
    cfg = load_config()
    samples, fs, _ = videoaudio.extract_audio(tap_video, _FS, tmp_path / "cache")

    onsets = seg.detect_onsets(samples, fs)
    found = [o / fs for o in onsets]
    assert len(found) == len(_TAPS), f"expected {_TAPS}, detected {found}"
    for got, want in zip(found, _TAPS):
        assert got == pytest.approx(want, abs=0.03)

    windows = seg.segments_from_onsets(onsets, samples.size, fs)
    items: list[Segment] = []
    # Two grades in one video - the case the whole screen exists for.
    for i, ((a, b), onset) in enumerate(zip(windows, onsets)):
        items = segmod.add(items, Segment(
            start_s=a / fs, end_s=b / fs, onset_s=onset / fs,
            grade="3A" if i < 2 else "4",
            defect="good" if i < 2 else "cracked",
        ), samples.size / fs)
    assert len(items) == len(_TAPS)

    db = Dataset(tmp_path / "d.sqlite")
    try:
        sid = db.create_session("slice-test")
        for s in items:
            a, b = int(s.start_s * fs), int(s.end_s * fs)
            wav = save_clip(samples[a:b], fs, tmp_path / "rec" / f"s{s.sid}.wav")
            cid = db.add_clip(sid, str(wav), "video", fs, s.duration_s,
                              notes=f"from taps.mp4 [{s.start_s:.3f}-{s.end_s:.3f}s]")
            db.set_label(cid, s.defect, grader="slice", grade_tier=s.grade)

        rows = db.list_clips()
        assert len(rows) == 4
        assert [r["label"]["grade_tier"] for r in rows] == ["3A", "3A", "4", "4"]
        assert [r["label"]["label"] for r in rows] == ["good", "good", "cracked", "cracked"]

        csv_path = db.export_csv(tmp_path / "out.csv")
        header, *lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
        assert "grade_tier" in header.split(",")
        assert len(lines) == 4

        payload = json.loads(db.export_json(tmp_path / "out.json").read_text(encoding="utf-8"))
        # Provenance survives the export, so a bad row can be traced back to
        # the moment in the footage it came from.
        assert payload[0]["notes"].startswith("from taps.mp4 [")
    finally:
        db.close()


def test_snippets_cut_from_the_video_do_not_overlap(tap_video, tmp_path):
    samples, fs, _ = videoaudio.extract_audio(tap_video, _FS, tmp_path / "cache")
    onsets = seg.detect_onsets(samples, fs)
    windows = seg.segments_from_onsets(onsets, samples.size, fs)
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert prev_end <= next_start
