# TODO

Legend: 🔴 bug / rule violation | 🟡 incomplete feature | 🟢 not started | ✅ done

## In Progress

- [ ] 🟢 Repo scaffolding — `requirements.txt`, `config.yaml`, `acoustic_analysis/`
  package skeleton (`__init__.py`, `__main__.py`, `config.py`, `cli.py`), `tests/`,
  `.gitignore` (`data/`, `*.wav`, `venv/`). Docs done 2026-09-08 (README, docs/METHODS.md,
  .CLAUDE/CLAUDE.md, CLAUDE-LOG.md).

## Not Started

### DSP core (`acoustic_analysis/dsp/`) — pure, do first, one pytest module each
- [ ] 🟢 `conditioning.py` — `remove_dc`, `apply_calibration`, `bandpass`, `detect_impact`,
  `window_ring` / `window_decay`. Tests: synthetic step + noise → known impact index.
- [ ] 🟢 `spectrum.py` — `fft_magnitude` (Hann), `dominant_frequency`, `pick_peaks` (freq,
  amp, Q), `spectral_centroid` / `bandwidth` / `rolloff` / `flatness`. Tests: known
  multi-tone → known peaks/centroid.
- [ ] 🟢 `octave_bands.py` — IEC 61260 base-2 band edges, `fractional_octave_levels(x, fs, n)`,
  normalisation, band ratios. Tests: white noise → flat band levels; single tone → one band.
- [ ] 🟢 `decay.py` — `envelope` (Hilbert), `reverb_time` (T20/T30), `decay_rate`,
  `per_band_decay`. Tests: synthetic `A·e^(−t/τ)·sin` → recovered τ.
- [ ] 🟢 `weighting.py` — A / C / Z IIR filters (IEC 61672). Tests: 1 kHz gain = 0 dB for
  A and C; known A-weight at 100 Hz / 10 kHz within tolerance.
- [ ] 🟢 `sound_level.py` — `leq`, `lpeak`, Fast/Slow/Impulse exponential time weighting,
  `percentile_levels` (Ln). Tests: constant tone → Leq = level; burst → Impulse hold.
- [ ] 🟢 `loudness.py` *(deferred)* — equal-loudness-contour phon/sone.

### Feature orchestration
- [ ] 🟢 `features.py` — `extract_features(clip, fs, cfg) -> dict` wiring all of `dsp/*`.
  Test: end-to-end on a synthetic "good" vs "cracked" pair → expected feature deltas.

### Audio + data I/O (`acoustic_analysis/io/`)
- [ ] 🟢 `recorder.py` — `sounddevice.InputStream` wrapper, pre-trigger ring buffer,
  RMS / manual trigger, `list_devices()`. Hardware wrapper — not unit-tested; the
  file-import path is its simulated equivalent.
- [ ] 🟢 `wavstore.py` — `save_clip` / `load_clip` (WAV + JSON sidecar with metadata).
- [ ] 🟢 `dataset.py` — SQLite store: `clips`, `features`, `labels` tables;
  `add_clip`, `set_features`, `set_label`, `export_csv` / `export_parquet`.

### CLI
- [ ] 🟢 `cli.py` — `devices`, `analyze <path|dir> [--export csv]`, `export`.

### Classification (`acoustic_analysis/classify/`)
- [ ] 🟢 `reference.py` — `ReferenceProfile.build(good_clips)` / `.compare(features)`.
- [ ] 🟢 `rules.py` — `grade(features, profile, cfg)` per docs/METHODS.md §6.3.

### GUI (`acoustic_analysis/app/`) — Tkinter, thin
- [ ] 🟢 `main_window.py` — Tk root, tab container, background analysis thread, shared state.
- [ ] 🟢 `record_tab.py` — device pick, level meter, arm/record, save.
- [ ] 🟢 `analyze_tab.py` — embedded matplotlib: waveform, spectrum, 1/3-octave bars,
  decay waterfall; overlay two clips / clip vs reference.
- [ ] 🟢 `label_tab.py` — assign class + grader + notes; mark for reference set.
- [ ] 🟢 `dataset_tab.py` — table of clips + labels + key features; export button.

### Later
- [ ] 🟢 Package as a Windows executable (PyInstaller) for non-Python users.
- [ ] 🟢 Collect a real dataset (good + cracked + corner-broken tiles) and tune every
  threshold in `config.yaml` against it — currently all placeholders.
- [ ] 🟢 Confirm Windows mic enhancements disabled + run a pistonphone calibration.
- [ ] 🟢 Train a classifier on the exported dataset (separate repo); document the export
  schema it expects.

## Done

- [x] Repository created, MIT licence, standalone-repo docs written (README,
  docs/METHODS.md, .CLAUDE/CLAUDE.md, CLAUDE-LOG.md) — 2026-09-08.
