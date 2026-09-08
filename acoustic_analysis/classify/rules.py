"""Rule-based grade against a reference profile (docs/METHODS.md section 6.3).

First-pass, explainable classification: an invalid clip is RETEST; otherwise the
clip is scored against the reference and lands as GOOD / BORDERLINE / DEFECTIVE
with the reasons that decided it. Thresholds come from ``config.yaml`` ->
``grading`` and are provisional until tuned on real data.
"""

from __future__ import annotations

from .reference import ReferenceProfile

_DEFAULT_GRADING = {
    "dominant_freq_tolerance": 0.15,
    "t30_min_ratio": 0.60,
    "high_low_ratio_min": 0.50,
    "band_decay_max_ratio": 3.0,
    "centroid_borderline_sigma": 1.0,
    "aggregate_defective": 4.0,
    "aggregate_borderline": 2.5,
}


def grade(features: dict, profile: ReferenceProfile | None = None, cfg: dict | None = None) -> dict:
    """Return ``{"grade", "reasons", "deviation"}``.

    ``grade`` is one of RETEST, UNGRADED (no profile), GOOD, BORDERLINE, DEFECTIVE.
    """
    if not features.get("valid", False):
        return {
            "grade": "RETEST",
            "reasons": list(features.get("reasons", ["clip failed the validity gate"])),
            "deviation": None,
        }

    g = {**_DEFAULT_GRADING, **((cfg or {}).get("grading", {}))}

    if profile is None:
        return {"grade": "UNGRADED", "reasons": ["no reference profile loaded"], "deviation": None}

    cmp = profile.compare(features)
    deviation = cmp["aggregate"]
    reasons: list[str] = []
    verdict = "GOOD"

    def worse(new: str) -> None:
        nonlocal verdict
        order = {"GOOD": 0, "BORDERLINE": 1, "DEFECTIVE": 2}
        if order[new] > order[verdict]:
            verdict = new

    ref_dom = profile.stats.get("dominant_freq_hz", {}).get("mean")
    dom = features.get("dominant_freq_hz")
    if ref_dom and dom:
        rel = abs(dom - ref_dom) / ref_dom
        if rel > g["dominant_freq_tolerance"]:
            worse("DEFECTIVE")
            reasons.append(f"dominant frequency {rel * 100:.0f}% off reference ({dom:.0f} vs {ref_dom:.0f} Hz)")

    ref_t30 = profile.stats.get("t30_s", {}).get("mean")
    t30 = features.get("t30_s")
    if ref_t30 and t30 is not None and t30 < g["t30_min_ratio"] * ref_t30:
        worse("DEFECTIVE")
        reasons.append(f"ring decays much faster than reference (T30 {t30:.3f}s vs {ref_t30:.3f}s)")

    ref_hl = profile.stats.get("high_to_low", {}).get("mean")
    hl = features.get("band_ratios", {}).get("high_to_low")
    if ref_hl and hl is not None and hl < g["high_low_ratio_min"] * ref_hl:
        worse("DEFECTIVE")
        reasons.append("high-frequency energy is well below reference (dull)")

    ref_fbd = profile.stats.get("fastest_band_decay_db_s", {}).get("mean")
    fbd = features.get("fastest_band_decay_db_s")
    if ref_fbd and fbd is not None and ref_fbd < 0 and fbd < g["band_decay_max_ratio"] * ref_fbd:
        worse("DEFECTIVE")
        reasons.append("a frequency band collapses far faster than reference (localised crack)")

    centroid_z = cmp["z"].get("spectral_centroid_hz")
    if centroid_z is not None and centroid_z <= -g["centroid_borderline_sigma"]:
        worse("BORDERLINE")
        reasons.append(f"spectral centroid {abs(centroid_z):.1f}sigma below reference (duller tone)")

    if deviation is not None:
        if deviation > g["aggregate_defective"]:
            worse("DEFECTIVE")
            reasons.append(f"overall deviation from reference is large ({deviation:.1f})")
        elif deviation > g["aggregate_borderline"]:
            worse("BORDERLINE")
            reasons.append(f"overall deviation from reference is elevated ({deviation:.1f})")

    if not reasons:
        reasons.append("within reference tolerance on every checked feature")

    return {"grade": verdict, "reasons": reasons, "deviation": deviation}
