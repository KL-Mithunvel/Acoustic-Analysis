# TODO

Legend: 🔴 bug / rule violation | 🟡 incomplete feature | 🟢 not started | ✅ done

## In Progress

- [ ] 🟡 **Slice screen: tune it on real footage.** Built and tested 2026-09-20 (v0.2),
  but every video it has ever seen was synthetic. On the first real recording, expect to
  move `config.yaml` `video.onsets.threshold_mult` (the sensitivity slider) and possibly
  `min_gap_s` and `min_peak_ratio`, and to check `video.snippet.post_ms` actually
  outlasts a real tile's ring. Watch for: phone AGC flattening the levels the percentile
  noise floor relies on, and speech between taps being detected as strikes.

## Not Started

### Needs real hardware / data
- [ ] 🟢 Full capture -> analyse loop against a real microphone; verify the Monitor and
  Record screens end to end (only `list_input_devices` has been run so far)
- [ ] 🟢 Verify playback actually makes sound, including the new `audio_out.Player`
  (position-reporting `OutputStream`) that drives the Slice screen's playhead - the
  Slice tests cover navigation and saving, never audio output
- [ ] 🟢 Run a pistonphone calibration (Calibrate screen / `cli calibrate`) and set
  `calibration.counts_per_pascal` so levels are real dB SPL
- [ ] 🟢 Confirm Windows mic "enhancements" are disabled before trusting any level/spectrum
- [ ] 🟢 Record real tiles (good + cracked + corner-broken), tune every provisional value
  in `config.yaml`, build a reference profile, validate grading
- [ ] 🟢 Train a classifier on the exported dataset (separate repo); document the CSV
  schema it expects

### Features
- [ ] 🟢 `dsp/loudness.py` - equal-loudness-contour phon/sone (deferred)
- [ ] 🟢 Slice: a headless CLI counterpart (`cli slice video.mp4 --auto --grade 4
  --defect good`) for bulk work once the onset thresholds are trusted on real footage
- [ ] 🟢 Slice: batch across several videos in one pass - the sidecar format already
  supports it, only the UI assumes one open file
- [ ] 🟢 Live scrolling spectrogram on the Monitor screen (currently latest-block spectrum)
- [ ] 🟢 Repeatability view - tap one part N times, show the spread of every feature
- [ ] 🟢 Per-clip PDF/PNG analysis report export
- [ ] 🟢 Draggable waveform region markers (impact / ring / decay)
- [ ] 🟢 Debounce the Noise-screen strength slider (recomputes denoise on every drag)

### Packaging / housekeeping
- [ ] 🟢 PyInstaller one-file Windows build - note it must now carry or locate an
  ffmpeg binary for the Slice screen
- [ ] 🟢 Interactive usability pass on the GUI (only smoke-tested + one 3 s launch).
  Specifically for Slice: drag-to-select feel, playhead smoothness during playback, and
  whether the frame preview keeps up while scrubbing - all driven programmatically so
  far, never watched
- [ ] 🟢 Verify audio-device handling on Linux/macOS (Windows-only so far)

## Done

- [x] **v0.2 - Slice screen: tap-test video -> labelled snippets** (2026-09-20). New pure
  modules `dsp/segmentation.py` (strike detection over a whole take + min/max envelope
  decimation) and `segments.py` (the snippet model and its list rules); new I/O
  `io/videoaudio.py` (ffmpeg audio extraction with caching + frame grabs) and
  `io/snippets.py` (per-video sidecar); `io/audio_out.Player` (position-reporting
  playback, for the playhead); `io/dataset.py` gained a `grade_tier` column plus a
  migration for older database files; `app/screens_video.py` is the screen itself, 13th
  in the sidebar under DATA. Labels are now **two independent axes** - defect class and
  cosmetic grade tier - by the owner's decision. 64 new tests (197 total), including a
  scripted end-to-end run of the screen against a real generated `.mp4`. Never seen real
  footage - see In Progress.
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
