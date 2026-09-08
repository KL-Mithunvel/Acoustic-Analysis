"""Headless command line: devices | analyze | noise | calibrate | export.

    python -m acoustic_analysis.cli devices
    python -m acoustic_analysis.cli analyze recording.wav
    python -m acoustic_analysis.cli analyze clips/ --export features.csv --profile ref.json
    python -m acoustic_analysis.cli noise room.wav
    python -m acoustic_analysis.cli calibrate pistonphone.wav --level-db 94
    python -m acoustic_analysis.cli export data/acoustic_analysis.sqlite out.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

from .config import load_config
from .dsp.conditioning import bandpass, rms
from .features import extract_features


def _wav_paths(target: Path, recursive: bool) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(target.rglob("*.wav") if recursive else target.glob("*.wav"))
    raise FileNotFoundError(target)


def _load(path: Path):
    from .io.wavstore import load_clip

    return load_clip(path)


# -- commands ---------------------------------------------------------------
def cmd_devices(_args) -> int:
    from .io.recorder import list_input_devices

    try:
        devices = list_input_devices()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not devices:
        print("no input devices found")
        return 0
    print(f"{'idx':>4}  {'ch':>3}  {'rate':>7}  name")
    for d in devices:
        print(f"{d['index']:>4}  {d['channels']:>3}  {d['default_samplerate']:>7.0f}  {d['name']}")
    return 0


_SUMMARY_KEYS = [
    ("status", "status"),
    ("dominant_freq_hz", "f_dom"),
    ("t30_s", "T30"),
    ("decay_rate_db_s", "decay"),
    ("spectral_centroid_hz", "centroid"),
    ("snr_db", "SNR"),
]


def cmd_analyze(args) -> int:
    cfg = load_config(args.config)
    profile = None
    if args.profile:
        from .classify.reference import ReferenceProfile

        profile = ReferenceProfile.load(args.profile)

    paths = _wav_paths(Path(args.target), args.recursive)
    if not paths:
        print("no .wav files found", file=sys.stderr)
        return 1

    rows = []
    print(f"{'file':<28} {'status':<8} {'f_dom':>8} {'T30':>7} {'decay':>8} {'centroid':>9} {'SNR':>7}  grade")
    for path in paths:
        samples, fs, _ = _load(path)
        try:
            feats = extract_features(samples, fs, cfg)
        except ValueError as exc:
            print(f"{path.name:<28} ERROR: {exc}")
            continue

        grade_str = ""
        if profile is not None:
            from .classify.rules import grade

            grade_str = grade(feats, profile, cfg)["grade"]

        def fmt(v):
            return f"{v:.3g}" if isinstance(v, (int, float)) else "-"

        print(
            f"{path.name:<28} {str(feats.get('status')):<8} "
            f"{fmt(feats.get('dominant_freq_hz')):>8} {fmt(feats.get('t30_s')):>7} "
            f"{fmt(feats.get('decay_rate_db_s')):>8} {fmt(feats.get('spectral_centroid_hz')):>9} "
            f"{fmt(feats.get('snr_db')):>7}  {grade_str}"
        )
        rows.append({"file": str(path), "features": feats, "grade": grade_str})

    if args.export:
        _export_analysis(rows, Path(args.export))
        print(f"\nwrote {args.export}")
    return 0


def _export_analysis(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".json":
        out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return
    keys = [
        "dominant_freq_hz", "spectral_centroid_hz", "spectral_bandwidth_hz",
        "spectral_rolloff_hz", "spectral_flatness", "t20_s", "t30_s",
        "decay_rate_db_s", "fastest_band_decay_db_s", "snr_db", "leq_z_db", "crest_factor",
    ]
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["file", "status", "grade", *keys])
        for r in rows:
            f = r["features"]
            writer.writerow(
                [r["file"], f.get("status"), r["grade"], *[f.get(k) for k in keys]]
            )


def cmd_noise(args) -> int:
    cfg = load_config(args.config)
    from .dsp.environment import environmental_analysis
    from .dsp.noise import noise_profile

    samples, fs, _ = _load(Path(args.target))
    prof = noise_profile(samples, fs, cfg)
    env = environmental_analysis(samples, fs, cfg)

    print(f"duration            {prof['duration_s']} s")
    print(f"broadband level     {prof['broadband_level_db']} dB")
    print(f"Leq / L10/50/90     {env['leq_db']} / {env['l10_db']} / {env['l50_db']} / {env['l90_db']} dB")
    print(f"NC rating           {env.get('nc_rating')}  (limiting band {env.get('nc_limiting_band_hz')} Hz)")
    if env["tones"]:
        print("dominant tones:")
        for t in env["tones"]:
            print(f"   {t['freq_hz']:>8.1f} Hz   +{t['prominence_db']:.1f} dB prominence")
    else:
        print("dominant tones:     none above threshold")
    return 0


def cmd_calibrate(args) -> int:
    samples, fs, _ = _load(Path(args.target))
    f0 = args.freq
    band = bandpass(samples, fs, max(20.0, f0 * 0.7), min(0.49 * fs, f0 * 1.4))
    counts_rms = rms(band)
    p_ref_rms = 10.0 ** (args.level_db / 20.0) * 20e-6
    counts_per_pascal = counts_rms / p_ref_rms

    print(f"reference tone      {args.level_db} dB SPL @ {f0:.0f} Hz")
    print(f"recorded RMS        {counts_rms:.6g}  (counts)")
    print(f"counts_per_pascal   {counts_per_pascal:.6g}")
    print("\nput this in config.yaml:")
    print("  calibration:")
    print("    enabled: true")
    print(f"    counts_per_pascal: {counts_per_pascal:.6g}")
    return 0


def cmd_export(args) -> int:
    from .io.dataset import Dataset

    with Dataset(args.database) as db:
        out = Path(args.out)
        if out.suffix.lower() == ".json":
            db.export_json(out, session_id=args.session)
        else:
            db.export_csv(out, session_id=args.session)
    print(f"wrote {args.out}")
    return 0


# -- parser ---------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="acoustic_analysis.cli", description=__doc__)
    p.add_argument("--config", default=None, help="path to config.yaml (default: repo root)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list input devices").set_defaults(func=cmd_devices)

    a = sub.add_parser("analyze", help="extract features from a WAV file or folder")
    a.add_argument("target")
    a.add_argument("--export", help="write results to a .csv or .json file")
    a.add_argument("--profile", help="reference profile JSON to grade against")
    a.add_argument("--recursive", action="store_true", help="recurse into subfolders")
    a.set_defaults(func=cmd_analyze)

    n = sub.add_parser("noise", help="environmental noise summary for a recording")
    n.add_argument("target")
    n.set_defaults(func=cmd_noise)

    c = sub.add_parser("calibrate", help="compute counts_per_pascal from a reference tone")
    c.add_argument("target")
    c.add_argument("--level-db", type=float, default=94.0, dest="level_db")
    c.add_argument("--freq", type=float, default=1000.0)
    c.set_defaults(func=cmd_calibrate)

    e = sub.add_parser("export", help="export a dataset database to CSV/JSON")
    e.add_argument("database")
    e.add_argument("out")
    e.add_argument("--session", type=int, default=None)
    e.set_defaults(func=cmd_export)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
