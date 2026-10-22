"""label_model: features cached, medians per group, filtering, sections and flags."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from acoustic_analysis.config import load_config
from acoustic_analysis.io.label_store import LabelStore
from acoustic_analysis.io.session_reader import StrikeRecord
from acoustic_analysis.label_model import NO_CAMERA, ReviewData, fmt_feature

FS = 48000


def _clip(path: Path, freq: float, tau: float, seed: int):
    rng = np.random.default_rng(seed)
    t = np.arange(int(1.5 * FS)) / FS
    x = rng.normal(0, 1e-3, t.size)
    m = t >= 0.5
    x[m] += 0.6 * np.sin(2 * np.pi * freq * (t[m] - 0.5)) * np.exp(-(t[m] - 0.5) / tau)
    sf.write(path, x.astype("float32"), FS)


@pytest.fixture()
def data(tmp_path):
    cfg = load_config()
    recs = []
    for i in range(4):                                       # tiles: a 2 kHz ring that fades fast
        p = tmp_path / f"S{i}.wav"; _clip(p, 2000, 0.02, i)
        recs.append(StrikeRecord("s1", f"S{i:04d}", "strike", "tof", "tile", tof_mm=88, clip_path=p, tile_id=f"T{i}",
                                 camera={"grade": "Grade A" if i % 2 else "Reject", "model_used": False, "model_grade": None,
                                         "crack_detected": False, "corner_broken": bool(i % 2 == 0), "corner_fill_ratio": 0.95}))
    for i in range(3):                                       # striker alone: a 7 kHz click that rings long
        p = tmp_path / f"N{i}.wav"; _clip(p, 7000, 0.08, 10 + i)
        recs.append(StrikeRecord("s1", f"S{10 + i:04d}", "strike", "manual", "no_tile", clip_path=p))
    recs.append(StrikeRecord("s1", "S0099", "strike", "tof", "tile", clip_path=None))     # clip missing
    labels = LabelStore(tmp_path / "labels.json", ["good", "cracked"], ["3A", "3B"])
    rd = ReviewData(recs, cfg, labels)
    rd.compute_features()
    return rd


def test_features_and_medians(data):
    assert len(data.features) == 7                           # the record without a clip is skipped, not fatal
    assert data.medians["tile"]["f_mid"] > 0.7
    assert data.medians["no_tile"]["f_top"] > 0.7
    assert data.medians["tile"]["t20_ms"] < data.medians["no_tile"]["t20_ms"]


def test_flags_say_tile_or_striker_alone(data):
    tile = next(r for r in data.records if r.group == "tile" and r.clip_path)
    none = next(r for r in data.records if r.group == "no_tile")
    assert "tile under" in data.flags(tile)[0]
    assert "alone" in data.flags(none)[0]
    assert "No audio clip" in data.flags(data.records[-1])[0]


def test_percentile_is_within_the_group(data):
    tiles = [r for r in data.records if r.group == "tile" and r.clip_path]
    ps = [data.percentile(r, "centroid_hz") for r in tiles]
    assert all(0 <= p < 100 for p in ps) and len(set(ps)) > 1


def test_filters(data):
    assert len(data.filter(group="no_tile")) == 3
    assert {r.group for r in data.filter(camera="Grade A")} == {"tile"}
    assert len(data.filter(camera="Grade A")) == 2
    assert len(data.filter(camera=NO_CAMERA)) == 4           # 3 no-tile strikes + the one without a camera result
    first = data.records[0]
    data.labels.set(first.key, label="good")
    assert first not in data.filter(status="unlabelled") and first in data.filter(status="labelled")
    assert data.progress() == (1, 7)


def test_camera_grades_listed(data):
    assert data.camera_grades() == ["Grade A", "Reject", NO_CAMERA]


def test_sections_carry_everything(data):
    rec = next(r for r in data.records if r.group == "tile" and r.camera and r.camera["grade"] == "Reject")
    sec = {s.title: dict(s.rows) for s in data.sections(rec)}
    assert sec["Camera (vision) result"]["Camera grade"] == "Reject"
    assert sec["Camera (vision) result"]["Vision-model grade"].startswith("not used")
    assert sec["Camera (vision) result"]["Corner broken"] == "yes"
    assert sec["Striker and distance sensor"]["Distance (ToF)"] == "88 mm"
    assert "Sound analysis (this app)" in sec
    assert "th pct" in sec["Sound analysis (this app)"]["Spectral centroid (brightness)"]
    none = next(r for r in data.records if r.group == "no_tile")
    secs = data.sections(none)
    assert secs[1].title == "Sound analysis (this app)"              # right after "This recording"
    assert dict(next(x for x in secs if x.title.startswith("Camera")).rows) == {"Camera": NO_CAMERA}


def test_unreadable_clip_is_recorded_not_raised(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"not a wav")
    rd = ReviewData([StrikeRecord("s", "S1", "strike", "tof", "tile", clip_path=bad)], load_config())
    rd.compute_features()
    assert rd.features["s/S1"]["onset_found"] is False and rd.features["s/S1"]["error"] is True


def test_fmt_feature():
    assert fmt_feature("f_mid", 0.168) == "17 %"
    assert fmt_feature("centroid_hz", 917.7) == "918 Hz"
    assert fmt_feature("slope_db_ms", -0.195) == "-0.20 dB/ms"
    assert fmt_feature("t20_ms", None) == "-"


def test_reference_curves_and_waveform(data):
    ref = data.reference
    assert set(ref) >= {"tile", "no_tile"}
    f, med, q1, q3 = ref["tile"]["spec"]
    assert abs(f[int(np.argmax(med))] - 2000) < 100            # the tile group rings at 2 kHz
    f2, med2, _, _ = ref["no_tile"]["spec"]
    assert abs(f2[int(np.argmax(med2))] - 7000) < 150
    assert (q1 <= q3 + 1e-12).all()
    t, m, _, _ = ref["tile"]["env"]
    assert m[0] > m[len(m) // 2]                               # fading
    rec = next(r for r in data.records if r.group == "tile" and r.clip_path)
    tw, x, on = data.waveform(rec)
    assert tw[0] < 0 < tw[-1] and on == 0.0 and abs(x[np.searchsorted(tw, 0.0):][:50]).max() > 0.1
    assert data.waveform(data.records[-1]) is None             # no clip
