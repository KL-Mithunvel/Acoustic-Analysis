# TODO

Legend: 🔴 bug / rule violation | 🟡 incomplete feature | 🟢 not started | ✅ done

## In Progress

_(nothing - v0.1 build is complete; see Not Started for what remains)_

## Not Started

### Needs real hardware / data
- [ ] 🟢 Full capture -> analyse loop against a real microphone; verify the Monitor and
  Record screens end to end (only `list_input_devices` has been run so far)
- [ ] 🟢 Run a pistonphone calibration (Calibrate screen / `cli calibrate`) and set
  `calibration.counts_per_pascal` so levels are real dB SPL
- [ ] 🟢 Confirm Windows mic "enhancements" are disabled before trusting any level/spectrum
- [ ] 🟢 Record real tiles (good + cracked + corner-broken), tune every provisional value
  in `config.yaml`, build a reference profile, validate grading
- [ ] 🟢 Train a classifier on the exported dataset (separate repo); document the CSV
  schema it expects

### Features
- [ ] 🟢 `dsp/loudness.py` - equal-loudness-contour phon/sone (deferred)
- [ ] 🟢 Live scrolling spectrogram on the Monitor screen (currently latest-block spectrum)
- [ ] 🟢 Repeatability view - tap one part N times, show the spread of every feature
- [ ] 🟢 Per-clip PDF/PNG analysis report export
- [ ] 🟢 Draggable waveform region markers (impact / ring / decay)
- [ ] 🟢 Debounce the Noise-screen strength slider (recomputes denoise on every drag)

### Packaging / housekeeping
- [ ] 🟢 PyInstaller one-file Windows build
- [ ] 🟢 Interactive usability pass on the GUI (only smoke-tested + one 3 s launch)
- [ ] 🟢 Verify audio-device handling on Linux/macOS (Windows-only so far)

## Done

- [x] Repo docs (README, docs/METHODS.md, .CLAUDE/CLAUDE.md, CLAUDE-LOG.md) - 2026-09-08.
- [x] Plan revision for expanded scope (noise tools, filter UI, instrument look,
  per-panel explanations) + `docs/UI_DESIGN.md` - commit 145b8ec.
- [x] Phase 0 - scaffold, config, pytest harness, `tests/synth.py` - commit bb6cf5a.
- [x] Phase 1 - DSP core: conditioning, spectrum, octave_bands, decay (Schroeder EDC),
  weighting (IEC 61672), sound_level - commits 0e1cb9b / 59af2be / 2c982cd.
- [x] Phase 2 - `features.extract_features` + validity gate - commit 252bea7.
- [x] Phase 3.5 - `dsp/filters` (FilterChain + Bode), `dsp/noise` (profile + spectral
  subtraction), `dsp/environment` (NC / Ln / tones) - commit 169b451.
- [x] Phase 3 - I/O: `wavstore`, `dataset` (SQLite), `recorder`, `audio_out` - commit fa1554f.
- [x] Phase 5 - `classify/reference` + `classify/rules` - commit 10b7ffa.
- [x] Phase 4 - CLI: devices / analyze / noise / calibrate / export - commit ae7afb9.
- [x] Phase 6 - GUI: explain + state + service (2606546); plots + widgets + main window +
  Analyze/Compare/Filters/Noise/Label/Dataset/Learn (eacd502); Monitor/Record/Calibrate/
  Settings (fbac568); dark instrument-look restyle - status bar, button rail, soft-keys
  (e546ae9).
- [x] Phase 7 - docs sync (this pass). 133 tests passing.
- [x] GUI restyle follow-on (branch `gui-restyle`): `main.py` one-command launcher
  (b71f6dc), theme-palette refresh (f8dd63f), tab bar -> left sidebar nav + instrument
  frame (d8a7c5f), and Home screen (`app/screens_home.py`) wired in as screen 0 +
  `AppContext.navigate`/`open_files` hooks. Docs synced. 2026-09-09.
