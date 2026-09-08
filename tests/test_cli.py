"""Tests for acoustic_analysis.cli."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.cli import main
from acoustic_analysis.config import load_config
from acoustic_analysis.features import extract_features
from acoustic_analysis.io.wavstore import save_clip
from tests.synth import make_tone, make_white_noise

_FS = 48000


def _impact_clip(dominant, extras, tau, seed=0):
    rng = np.random.default_rng(seed)
    n, n_pre = int(0.6 * _FS), int(0.1 * _FS)
    clip = rng.normal(0.0, 1e-4, n)
    t = np.arange(n - n_pre) / _FS
    ring = np.exp(-t / tau) * np.sin(2 * np.pi * dominant * t)
    for f in extras:
        ring += 0.6 * np.exp(-t / tau) * np.sin(2 * np.pi * f * t)
    ring[: int(0.001 * _FS)] += 0.4
    clip[n_pre:] += ring
    return clip.astype(np.float64)


def test_devices_runs(capsys):
    rc = main(["devices"])
    assert rc in (0, 2)  # 2 if PortAudio missing


def test_analyze_file(tmp_path, capsys):
    p = save_clip(_impact_clip(1800.0, [4200.0, 8000.0], 0.10, seed=1), _FS, tmp_path / "a.wav")
    rc = main(["analyze", str(p)])
    assert rc == 0
    assert "OK" in capsys.readouterr().out


def test_analyze_directory_with_csv_export(tmp_path):
    for i in range(2):
        save_clip(_impact_clip(1800.0, [4200.0], 0.10, seed=i), _FS, tmp_path / f"c{i}.wav")
    out = tmp_path / "feat.csv"
    rc = main(["analyze", str(tmp_path), "--export", str(out)])
    assert rc == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("file,status,grade,")
    assert len(lines) == 3


def test_analyze_with_profile_flags_defective(tmp_path, capsys):
    cfg = load_config()
    from acoustic_analysis.classify.reference import ReferenceProfile

    goods = [
        extract_features(_impact_clip(1800.0, [4200.0, 8000.0], 0.10, seed=s), _FS, cfg)
        for s in range(5)
    ]
    ref = ReferenceProfile.build(goods).save(tmp_path / "ref.json")
    cracked = save_clip(_impact_clip(1400.0, [3000.0], 0.03, seed=9), _FS, tmp_path / "x.wav")

    rc = main(["analyze", str(cracked), "--profile", str(ref)])
    assert rc == 0
    assert "DEFECTIVE" in capsys.readouterr().out


def test_noise_command(tmp_path, capsys):
    p = save_clip(make_white_noise(2.0, _FS, rms=0.05, seed=3), _FS, tmp_path / "room.wav")
    rc = main(["noise", str(p)])
    assert rc == 0
    assert "NC rating" in capsys.readouterr().out


def test_calibrate_command(tmp_path, capsys):
    tone = make_tone(1000.0, 1.0, _FS, amplitude=0.1)
    p = save_clip(tone, _FS, tmp_path / "cal.wav")
    rc = main(["calibrate", str(p), "--level-db", "94", "--freq", "1000"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "counts_per_pascal" in out
    expected = (0.1 / np.sqrt(2)) / (10 ** (94 / 20) * 20e-6)
    printed = [float(w) for line in out.splitlines() if "counts_per_pascal:" in line for w in line.split()[-1:]]
    assert printed and printed[0] == pytest.approx(expected, rel=0.05)


def test_export_command(tmp_path):
    from acoustic_analysis.io.dataset import Dataset

    db_path = tmp_path / "d.sqlite"
    with Dataset(db_path) as db:
        sid = db.create_session("s")
        cid = db.add_clip(sid, "a.wav", "recorded", _FS, 0.6)
        db.set_features(cid, {"status": "OK", "dominant_freq_hz": 1800.0, "band_ratios": {}})
        db.set_label(cid, "good")
    out = tmp_path / "out.csv"
    rc = main(["export", str(db_path), str(out)])
    assert rc == 0
    assert out.exists() and "good" in out.read_text(encoding="utf-8")
