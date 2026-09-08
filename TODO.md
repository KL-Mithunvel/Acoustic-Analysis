# TODO

Legend: 🔴 bug / rule violation | 🟡 incomplete feature | 🟢 not started | ✅ done

## In Progress

- [ ] 🟡 Phase 3 - I/O layer (`acoustic_analysis/io/`)
  - [ ] `wavstore.py` - save_clip / load_clip (WAV + JSON sidecar)
  - [ ] `dataset.py` - SQLite: sessions / clips / features / labels; add/query/export_csv
  - [ ] `recorder.py` - sounddevice InputStream wrapper: list_devices, input gain,
    pre-trigger ring buffer, RMS / manual trigger, live-monitor block callback
  - [ ] `audio_out.py` - playback (sounddevice OutputStream) for A/B listening
- [ ] 🟡 Phase 3.5 - pure noise / filter modules (`acoustic_analysis/dsp/`)
  - [ ] `filters.py` - composable FilterChain (bandpass + notch list + weighting),
    `.apply(x, fs)` and `.frequency_response(fs)` for the Bode plot
  - [ ] `noise.py` - noise profile (spectrum / octave / Ln / broadband level) +
    spectral subtraction / spectral gating denoise with adjustable strength
  - [ ] `environment.py` - environmental noise: NC rating, octave spectrum, Leq / L90 /
    L10, dominant tones over a long recording
- [ ] 🟡 Phase 4 - CLI (`cli.py`): `devices`, `analyze <path|dir>`, `noise <path>`,
  `calibrate <tone.wav>`, `export`
- [ ] 🟡 Phase 5 - classification (`acoustic_analysis/classify/`)
  - [ ] `reference.py` - ReferenceProfile.build / compare / save / load
  - [ ] `rules.py` - grade(features, profile, cfg) per docs/METHODS.md section 6.3
- [ ] 🟡 Phase 6 - GUI (`acoustic_analysis/app/`), plain `ttk.Notebook` tabs first,
  instrument-look restyle after (see `docs/UI_DESIGN.md`)
  - [ ] `main_window.py` + `state.py` - Tk root, notebook, background worker thread
  - [ ] `widgets.py` - reusable plot panel (title + "what is this" info toggle),
    param slider, level meter, feature table
  - [ ] Monitor tab - device pick, gain, level meter, live spectrum + spectrogram,
    OS-enhancement warning
  - [ ] Analyze tab - one clip: waveform, spectrum, 1/3-octave, energy-decay curve,
    feature table; every panel has an explanation
  - [ ] Filters tab - live filter-chain params, frequency-response (Bode) plot,
    before/after spectrum + spectrogram, A/B listen
  - [ ] Compare tab - N clips overlaid + "what differs most" table
  - [ ] Noise tab - noise-profile capture, environmental analysis, denoise preview
  - [ ] Record tab - arm / trigger / record, save into a session
  - [ ] Label tab - class + grader + notes, add-to-reference
  - [ ] Dataset tab - clip table, filter, export, delete, per-clip report
  - [ ] Calibrate tab - reference-tone -> counts_per_pascal workflow
  - [ ] Learn tab - synthesise a tone/decay, apply a filter, watch what changes
  - [ ] Settings tab - config presets, paths
  - [ ] Instrument-look restyle: `theme.py` (dark), fixed top status bar,
    persistent button rail, bottom soft-key bar (`docs/UI_DESIGN.md`)
- [ ] 🟡 Phase 7 - polish
  - [ ] Fill `docs/EXPLAIN.md` (the text behind every info panel)
  - [ ] PyInstaller one-file Windows build
  - [ ] Sync `.CLAUDE/CLAUDE.md` / `README.md` / `docs/METHODS.md` to the built state

## Not Started

- [ ] 🟢 `dsp/loudness.py` - equal-loudness-contour phon/sone (deferred)
- [ ] 🟢 Repeatability view - tap one part N times, show the spread of every feature
- [ ] 🟢 Per-clip PDF / PNG analysis report export
- [ ] 🟢 Reference-profile overlay (golden band shape +/- tolerance) on the octave chart
- [ ] 🟢 Waveform region markers (impact / ring / decay), draggable
- [ ] 🟢 Collect a real dataset (good + cracked + corner-broken tiles) and tune every
  threshold in `config.yaml` against it - currently all placeholders
- [ ] 🟢 Confirm Windows mic enhancements disabled + run a pistonphone calibration on the
  real mic
- [ ] 🟢 Train a classifier on the exported dataset (separate repo); document the export
  schema it expects

## Done

- [x] Repository created, MIT licence, standalone-repo docs (README, docs/METHODS.md,
  .CLAUDE/CLAUDE.md, CLAUDE-LOG.md) - 2026-09-08.
- [x] Phase 0 - scaffold: requirements, config.yaml, config.py, pytest harness,
  tests/synth.py - commit bb6cf5a (2026-09-09).
- [x] Phase 1 - DSP core: conditioning, spectrum, octave_bands, decay (Schroeder EDC),
  weighting (A/C/Z, IEC 61672), sound_level - commits 0e1cb9b, 59af2be, 2c982cd.
- [x] Phase 2 - `features.extract_features` orchestrator + validity gate - commit 252bea7.
  83 tests passing.
