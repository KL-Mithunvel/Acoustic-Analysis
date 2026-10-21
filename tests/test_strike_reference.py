"""strike_reference: build from good tiles, grade by robust distance, and measure itself on labels."""

from __future__ import annotations

import numpy as np
import pytest

from acoustic_analysis.config import load_config
from acoustic_analysis.strike_reference import (
    ReferenceError, StrikeReference, build_reference, describe_evaluation, evaluate, grade_strike,
)


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def _feat(rng, centroid=900.0, f_mid=0.16, f_top=0.015, slope=-0.20, snr=40.0, jitter=1.0):
    j = lambda scale: float(rng.normal(0, scale * jitter))  # noqa: E731
    return {"onset_found": True, "snr_db": snr, "centroid_hz": centroid + j(60), "f_low": 0.78 + j(0.03),
            "f_mid": f_mid + j(0.015), "f_high": 0.045 + j(0.01), "f_top": f_top + j(0.003), "slope_db_ms": slope + j(0.01)}


def _goods(n=20, seed=0):
    rng = np.random.default_rng(seed)
    return [_feat(rng) for _ in range(n)]


def test_build_needs_enough_good_tiles(cfg):
    with pytest.raises(ReferenceError, match="at least 8"):
        build_reference(_goods(5), cfg)
    with pytest.raises(ReferenceError):
        build_reference([{"onset_found": False}] * 20, cfg)         # strikes with no clear onset do not count
    ref = build_reference(_goods(20), cfg)
    assert ref.n_good == 20 and set(ref.features) == set(cfg["strike"]["reference"]["features"])
    assert ref.features["centroid_hz"]["median"] == pytest.approx(900, abs=40)


def test_a_typical_tile_is_good_and_a_far_one_is_defective(cfg):
    ref = build_reference(_goods(30), cfg)
    rng = np.random.default_rng(9)
    ok = grade_strike(_feat(rng, jitter=0.5), ref, cfg)
    assert ok["grade"] == "GOOD" and "within" in ok["reasons"][0]
    dull = grade_strike(_feat(rng, centroid=2000.0, f_mid=0.06, f_top=0.12, slope=-0.11), ref, cfg)
    assert dull["grade"] == "DEFECTIVE" and dull["worst"] in ref.features
    text = " ".join(dull["reasons"])
    assert "higher" in text and "spreads away" in text


def test_borderline_sits_between_the_two_limits(cfg):
    ref = build_reference(_goods(30), cfg)
    s = ref.features["centroid_hz"]["sigma"]
    f = {**_goods(1, seed=5)[0], "centroid_hz": ref.features["centroid_hz"]["median"] + 4.5 * s,
         "f_low": ref.features["f_low"]["median"], "f_mid": ref.features["f_mid"]["median"],
         "f_high": ref.features["f_high"]["median"], "f_top": ref.features["f_top"]["median"],
         "slope_db_ms": ref.features["slope_db_ms"]["median"]}
    r = grade_strike(f, ref, cfg)
    assert r["grade"] == "BORDERLINE" and r["worst"] == "centroid_hz" and "higher" in r["reasons"][0]
    f["centroid_hz"] = ref.features["centroid_hz"]["median"] - 4.5 * s
    assert "lower" in grade_strike(f, ref, cfg)["reasons"][0]


def test_retest_notile_and_ungraded(cfg):
    ref = build_reference(_goods(20), cfg)
    rng = np.random.default_rng(1)
    assert grade_strike({"onset_found": False}, ref, cfg)["grade"] == "RETEST"
    assert grade_strike(None, ref, cfg)["grade"] == "RETEST"
    weak = grade_strike(_feat(rng, snr=8.0), ref, cfg)
    assert weak["grade"] == "RETEST" and "8 dB" in weak["reasons"][0]
    assert grade_strike(_feat(rng), ref, cfg, tile_present=False)["grade"] == "NO TILE"
    none = grade_strike(_feat(rng), None, cfg)
    assert none["grade"] == "UNGRADED" and "label some tiles good" in none["reasons"][0]


def test_a_few_wild_good_tiles_do_not_blow_up_the_spread(cfg):
    clean = _goods(25, seed=2)
    wild = clean + [{**clean[0], "centroid_hz": 5000.0}, {**clean[1], "centroid_hz": 100.0}]
    a, b = build_reference(clean, cfg), build_reference(wild, cfg)
    assert b.features["centroid_hz"]["sigma"] < 1.5 * a.features["centroid_hz"]["sigma"]     # MAD, not standard deviation
    assert b.features["centroid_hz"]["median"] == pytest.approx(a.features["centroid_hz"]["median"], abs=30)


def test_identical_tiles_do_not_give_a_zero_spread(cfg):
    same = [{"onset_found": True, "snr_db": 40, "centroid_hz": 900.0, "f_low": 0.8, "f_mid": 0.15, "f_high": 0.04,
             "f_top": 0.01, "slope_db_ms": -0.2}] * 10
    ref = build_reference(same, cfg)
    assert all(v["sigma"] > 0 for v in ref.features.values())
    assert grade_strike(same[0], ref, cfg)["grade"] == "GOOD"             # no division by zero


def test_save_and_load_roundtrip(cfg, tmp_path):
    ref = build_reference(_goods(20), cfg)
    p = tmp_path / "data" / "ref.json"
    ref.save(p)
    back = StrikeReference.load(p)
    assert back.features == ref.features and back.n_good == 20
    assert not list(p.parent.glob("*.tmp"))
    p.write_text("not json")
    with pytest.raises(ReferenceError):
        StrikeReference.load(p)
    with pytest.raises(ReferenceError):
        StrikeReference.load(tmp_path / "missing.json")


def test_evaluate_counts_what_it_gets_right_and_wrong(cfg):
    rng = np.random.default_rng(3)
    items = [(f"g{i}", _feat(rng), "good") for i in range(30)]
    items += [(f"c{i}", _feat(rng, centroid=1700.0, f_mid=0.07, f_top=0.09, slope=-0.12), "cracked") for i in range(6)]
    items += [("sneaky", _feat(rng), "corner_broken")]                       # sounds exactly like a good tile
    items += [("junk", {"onset_found": False}, "good")]                       # unusable: not counted
    r = evaluate(items, cfg)
    assert r["possible"] and r["n_good"] == 30 and r["n_defect"] == 7
    assert r["good_accepted"] >= 27                                           # leave-one-out: good tiles mostly accepted
    assert r["defect_caught"] == 6 and "sneaky" in r["missed"]                # the honest limit: same sound = missed
    assert r["good_accepted"] + r["good_borderline"] + r["good_rejected"] == 30


def test_evaluate_with_too_few_good_tiles_says_so(cfg):
    r = evaluate([(f"g{i}", f, "good") for i, f in enumerate(_goods(3))], cfg)
    assert r["possible"] is False and "at least 8" in r["why"]


def test_describe_evaluation_is_plain_language(cfg):
    rng = np.random.default_rng(4)
    items = [(f"g{i}", _feat(rng), "good") for i in range(20)]
    ref = build_reference([f for _, f, _l in items], cfg)
    none = describe_evaluation(ref, evaluate(items, cfg))
    assert "built from 20 tiles" in none and "No defective tiles labelled yet" in none
    items += [("c1", _feat(rng, centroid=1800.0, f_mid=0.05, f_top=0.1), "cracked")]
    some = describe_evaluation(ref, evaluate(items, cfg))
    assert "Defective tiles caught: 1 of 1" in some and "NOT" not in some
    few = describe_evaluation(ref, evaluate([("g", _feat(rng), "good")], cfg))
    assert "Could not check" in few
