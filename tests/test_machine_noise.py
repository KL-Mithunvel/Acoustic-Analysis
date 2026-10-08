"""Sound trigger + machine-noise removal, on synthetic rigs with known answers."""

import numpy as np
import pytest

from acoustic_analysis.config import load_config
from acoustic_analysis.dsp.machine_noise import build_striker_template, clean_clip, subtract_striker
from acoustic_analysis.dsp.trigger import SoundTrigger

FS = 48000


def _cfg():
    return load_config()


def _striker(n, seed=0):
    """A short, sharp, repeatable mechanism click (ball/solenoid stand-in)."""
    rng = np.random.default_rng(1234)                    # same shape every call
    t = np.arange(n) / FS
    click = rng.normal(0, 1, n) * np.exp(-t / 0.002)
    click += 0.8 * np.sin(2 * np.pi * 3100 * t) * np.exp(-t / 0.004)
    return click


def _tile_ring(n):
    t = np.arange(n) / FS
    return np.sin(2 * np.pi * 2200 * t) * np.exp(-t / 0.05)


def _clip(cfg, motor_rms=0.003, tile=0.0, strike=0.6, jitter=0, seed=0, dur=0.6):
    rng = np.random.default_rng(seed)
    n = int(dur * FS)
    x = rng.normal(0, motor_rms, n)
    on = int(cfg["capture"]["pre_trigger_ms"] / 1000 * FS) + jitter
    s = _striker(int(0.15 * FS))
    x[on : on + s.size] += strike * s
    if tile:
        r = _tile_ring(n - on)
        x[on:] += tile * r
    return x, on


def test_trigger_captures_one_clip_per_event_and_respects_cooldown():
    trig = SoundTrigger(FS, 1024, 100, 0.5, 1.0, threshold=0.05)
    sig = np.zeros(FS * 4)
    sig[FS : FS + 200] = 0.5
    sig[int(1.2 * FS) : int(1.2 * FS) + 200] = 0.5        # inside cooldown -> ignored
    sig[int(2.8 * FS) : int(2.8 * FS) + 200] = 0.5
    clips = [c for i in range(0, sig.size - 1024, 1024) if (c := trig.process_block(sig[i : i + 1024])) is not None]
    assert len(clips) == 2
    assert all(c.size == int(0.5 * FS) for c in clips)
    assert np.abs(clips[0]).max() > 0.4                    # event present
    assert np.abs(clips[0][: int(0.05 * FS)]).max() == 0   # pre-roll shows quiet before it


def test_adaptive_threshold_rides_over_loud_motor():
    rng = np.random.default_rng(0)
    trig = SoundTrigger(FS, 1024, 100, 0.3, 0.5, floor_mult=5.0, warmup_s=0.3)
    hum = lambda n: rng.normal(0, 0.02, n)                 # motor: rms 0.02 > a naive 0.01 threshold
    got = []
    for _ in range(80):                                    # ~1.7 s of hum alone
        got.append(trig.process_block(hum(1024)))
    assert all(g is None for g in got), "motor hum alone must not trigger"
    assert trig.threshold == pytest.approx(5 * 0.02, rel=0.3)
    blk = hum(1024)
    blk[:100] += 1.0
    out = [trig.process_block(blk)] + [trig.process_block(hum(1024)) for _ in range(30)]
    assert sum(o is not None for o in out) == 1


def test_trigger_does_not_fire_during_warmup():
    trig = SoundTrigger(FS, 1024, 100, 0.3, 0.5, threshold=0.05, warmup_s=0.5)
    assert trig.process_block(np.ones(1024)) is None
    assert trig.state == "warming up"


def test_template_repeatability_high_for_identical_strikes():
    cfg = _cfg()
    clips = [_clip(cfg, seed=i)[0] for i in range(10)]
    tpl = build_striker_template(clips, FS, cfg)
    assert tpl.n_used == 10 and tpl.repeatability > 0.9


def test_template_refuses_when_too_few_strikes():
    cfg = _cfg()
    quiet = [np.random.default_rng(i).normal(0, 0.003, int(0.6 * FS)) for i in range(8)]
    with pytest.raises(ValueError):
        build_striker_template(quiet, FS, cfg)


def test_template_low_repeatability_when_strikes_differ():
    cfg = _cfg()
    clips = []
    for i in range(10):
        x = np.random.default_rng(i).normal(0, 0.003, int(0.6 * FS))
        on = int(cfg["capture"]["pre_trigger_ms"] / 1000 * FS)
        rng = np.random.default_rng(100 + i)               # a DIFFERENT click each time
        x[on : on + 900] += 0.6 * rng.normal(0, 1, 900) * np.exp(-np.arange(900) / 100)
        clips.append(x)
    assert build_striker_template(clips, FS, cfg).repeatability < 0.6


def test_subtraction_removes_striker_and_keeps_tile():
    cfg = _cfg()
    tpl = build_striker_template([_clip(cfg, seed=i)[0] for i in range(12)], FS, cfg)
    x, on = _clip(cfg, tile=0.3, seed=99)
    on_found = on                                          # onset by construction
    cleaned, scale = subtract_striker(x, FS, tpl, on_found, cfg)
    assert 0.7 < scale < 1.4
    span = slice(on, on + int(0.01 * FS))                  # the click region
    truth = 0.3 * _tile_ring(x.size - on)                  # what should remain: the tile only
    err_before = np.sqrt(np.mean((x[span] - truth[: span.stop - span.start]) ** 2))
    err_after = np.sqrt(np.mean((cleaned[span] - truth[: span.stop - span.start]) ** 2))
    assert err_after < 0.25 * err_before                   # striker click gone, tile left
    ring = slice(on + int(0.03 * FS), on + int(0.2 * FS))  # tile ring survives
    ref = 0.3 * _tile_ring(x.size - on)[int(0.03 * FS) : int(0.2 * FS)]
    corr = np.corrcoef(cleaned[ring], ref)[0, 1]
    assert corr > 0.9


def test_alignment_tolerates_small_onset_jitter():
    cfg = _cfg()
    tpl = build_striker_template([_clip(cfg, seed=i)[0] for i in range(12)], FS, cfg)
    x, on = _clip(cfg, jitter=40, seed=7)                  # ~0.8 ms late
    cleaned, _ = subtract_striker(x, FS, tpl, on - 40 + 0, cfg)   # detector was 40 samples early
    span = slice(on, on + int(0.01 * FS))
    assert np.sqrt(np.mean(cleaned[span] ** 2)) < 0.4 * np.sqrt(np.mean(x[span] ** 2))


def test_clean_clip_verdicts():
    cfg = _cfg()
    tpl = build_striker_template([_clip(cfg, seed=i)[0] for i in range(12)], FS, cfg)
    motor = np.random.default_rng(5).normal(0, 0.003, 3 * FS)

    dry, _ = _clip(cfg, seed=50)                           # striker, no tile
    assert clean_clip(dry, FS, cfg, tpl, motor).verdict == "no_tile"

    hit, _ = _clip(cfg, tile=0.3, seed=51)                 # striker + tile
    r = clean_clip(hit, FS, cfg, tpl, motor)
    assert r.verdict == "tile" and r.residual_snr_db > cfg["machine"]["min_residual_snr_db"]
    assert r.samples.size == hit.size

    silent = np.random.default_rng(6).normal(0, 0.003, int(0.6 * FS))
    assert clean_clip(silent, FS, cfg, tpl, motor).verdict == "no_strike"


def test_clean_clip_without_profiles_still_runs():
    cfg = _cfg()
    hit, _ = _clip(cfg, tile=0.3, seed=51)
    r = clean_clip(hit, FS, cfg)
    assert r.verdict in ("tile", "no_tile") and r.scale == 0.0


def test_profile_roundtrip(tmp_path):
    from acoustic_analysis.io.machine_profile import MachineProfile, load_profile, save_profile

    cfg = _cfg()
    tpl = build_striker_template([_clip(cfg, seed=i)[0] for i in range(8)], FS, cfg)
    motor = np.random.default_rng(1).normal(0, 0.003, FS)
    save_profile(MachineProfile(FS, motor, tpl), tmp_path / "p" / "machine.npz")
    got = load_profile(tmp_path / "p" / "machine.npz")
    assert got.fs == FS and got.template.pre_n == tpl.pre_n
    assert got.template.repeatability == pytest.approx(tpl.repeatability)
    assert np.allclose(got.template.samples, tpl.samples, atol=1e-6)
    assert load_profile(tmp_path / "missing.npz") is None
    (tmp_path / "bad.npz").write_bytes(b"junk")
    assert load_profile(tmp_path / "bad.npz") is None
