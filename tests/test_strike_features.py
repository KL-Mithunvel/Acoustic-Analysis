"""strike_features: synthetic clips with known onset, ring pitch and fade."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.config import load_config
from acoustic_analysis.strike_features import (
    find_onset, flags, percentile_of, ring_envelope_db, ring_spectrum, strike_features,
)

FS = 48000


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _clip(freq_hz: float, tau_s: float, onset_s: float = 0.5, total_s: float = 1.5, noise: float = 1e-3, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(total_s * FS)) / FS
    x = rng.normal(0, noise, t.size)
    m = t >= onset_s
    tt = t[m] - onset_s
    x[m] += 0.6 * np.sin(2 * np.pi * freq_hz * tt) * np.exp(-tt / tau_s)
    return x


def test_onset_found_at_the_strike(cfg):
    on, noise = find_onset(_clip(2000, 0.03), FS, cfg)
    assert abs(on / FS - 0.5) < 0.005
    assert noise > 0


def test_noise_before_the_strike_is_not_the_onset(cfg):
    x = _clip(2000, 0.03)
    x[int(0.10 * FS): int(0.10 * FS) + 200] += 0.3          # a click at 0.10 s, inside the lead-in
    on, _ = find_onset(x, FS, cfg)
    assert on / FS > 0.45                                     # the old detector would have picked 0.10 s


def test_silence_has_no_onset(cfg):
    x = np.random.default_rng(1).normal(0, 1e-3, int(1.5 * FS))
    f = strike_features(x, FS, cfg)
    assert f["onset_found"] is False and f["centroid_hz"] is None


def test_peak_frequency_and_centroid_follow_the_ring(cfg):
    f = strike_features(_clip(2000, 0.05), FS, cfg)
    assert abs(f["peak_hz"] - 2000) < 60
    assert 1800 < f["centroid_hz"] < 2300
    assert f["f_mid"] > 0.8                                   # 2 kHz falls in the 1-3 kHz share


def test_energy_shares_sum_to_one(cfg):
    f = strike_features(_clip(4500, 0.04), FS, cfg)
    assert f["f_low"] + f["f_mid"] + f["f_high"] + f["f_top"] == pytest.approx(1.0, abs=1e-6)
    assert f["f_high"] > 0.8


def test_faster_fade_gives_steeper_slope_and_shorter_t20(cfg):
    slow = strike_features(_clip(1500, 0.080), FS, cfg)
    fast = strike_features(_clip(1500, 0.015), FS, cfg)
    assert fast["slope_db_ms"] < slow["slope_db_ms"] < 0
    assert fast["t20_ms"] < slow["t20_ms"]


def test_t20_matches_the_known_decay(cfg):
    # amplitude exp(-t/tau): 20 dB is a factor 10 -> t = tau*ln(10)
    tau = 0.030
    f = strike_features(_clip(1500, tau, noise=1e-5), FS, cfg)
    assert f["t20_ms"] == pytest.approx(tau * np.log(10) * 1000, rel=0.2)


def test_ring_spectrum_is_normalised(cfg):
    fr, p = ring_spectrum(_clip(2500, 0.05), FS, cfg)
    assert p.sum() == pytest.approx(1.0)
    assert abs(fr[int(np.argmax(p))] - 2500) < 60


def test_percentile_of():
    assert percentile_of(5, [1, 2, 3, 4, 6, 7, 8, 9]) == pytest.approx(50.0)
    assert percentile_of(None, [1, 2]) is None
    assert percentile_of(1, []) is None


def test_flags_tile_vs_no_tile(cfg):
    tile = {"f_mid": 0.17, "f_top": 0.014}
    none = {"f_mid": 0.066, "f_top": 0.158}
    like_tile = {"onset_found": True, "f_mid": 0.18, "f_top": 0.02, "t20_ms": 45.0, "snr_db": 40.0}
    like_none = {"onset_found": True, "f_mid": 0.06, "f_top": 0.17, "t20_ms": 200.0, "snr_db": 40.0}
    assert "tile under" in flags(like_tile, tile, none)[0]
    assert "alone" in flags(like_none, tile, none)[0]
    assert "No strike" in flags({"onset_found": False})[0]
    assert any("did not fade" in n for n in flags({**like_tile, "t20_ms": None}, tile, none))


def test_ring_envelope_starts_at_zero_db_and_fades(cfg):
    t, db = ring_envelope_db(_clip(1500, 0.03, noise=1e-5), FS, cfg)
    assert db[:int(0.01 * FS)].max() == pytest.approx(0.0)
    assert db[int(0.100 * FS)] < -20                          # 100 ms later it is far down
    assert ring_envelope_db(np.random.default_rng(0).normal(0, 1e-3, int(1.5 * FS)), FS, cfg) is None
