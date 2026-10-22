# TODO

Legend: 🔴 bug / rule violation | 🟡 incomplete feature | 🟢 not started | ✅ done

## In Progress

- [ ] 🟡 **Test Tile + striker: first run on the real rig (v0.4).** Built 2026-10-22 and tested
  only against a scripted fake serial port, a fake microphone ring and real clips from the
  2026-10-19 station sessions. On the first real run: `python main.py flash` with the Nano
  plugged into the laptop (check it uploads at 115200 and boots: HELLO + HB), connect, watch the
  tile-sensor distance (tile ~91 mm, empty 112-142 mm), press Strike now and check the clip really
  has the strike about 0.5 s in (`strike.expect_s`; station onsets ran 0.47-0.57 s), the striker
  sprung solenoid and VL53L0X have never been exercised together with this app. Check the coil
  temperature at `striker.hold_pct`.

- [ ] 🟡 **Label real tiles, build the sound reference, read its self-check (v0.4).** The sound
  grade (`strike_reference.py`) compares a strike with tiles labelled good; it has never been built
  from real labels. Label at least 8 good tiles (more is better, plus real cracked / chipped ones),
  press Build sound reference, and read the leave-one-out numbers before trusting a verdict.
  `strike.reference.*` (z_ok 3, z_bad 6, features) are provisional guesses.

- [ ] 🟡 **Explain the first six tile strikes of the 2026-10-19 session.** S0001-S0009 of
  `2026-10-19_18-44-39` sit apart from the other 16 (higher centroid, a ring that never fades 20 dB in
  250 ms). Mic gain, tile or striker placement? Nobody has checked; the session note does not say.

- [ ] 🟡 **`detect_impact` misfires on station clips.** On a tile clip it put the impact 0.3 s before the
  loudest sample (the retract noise?). `strike_features` avoids it by trusting a quiet lead-in; the older
  `features.extract_features` (Analyze screen) still uses `detect_impact`.

- [ ] 🟡 **Collect screen: first run on the real rig.** Built 2026-10-08 (v0.3) and
  tested on synthetic signals only. On the first real session: run Setup A + B and read the
  repeatability score; tune the Sensitivity slider and `machine.min_residual_snr_db`; check
  dry strikes really land in `rejected/` and real taps don't; confirm the adaptive trigger
  doesn't fire on the motor alone; confirm Space-to-start and the level bar feel right.
  Watch for a low repeatability score (fix the striker mounting, not the thresholds).

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
- [ ] 🟢 Settings presets ("Quiet room" / "Noisy workshop") - deliberately not shipped in
  v0.3: the numbers would be invented before any real recording exists
- [ ] 🟢 Collect: let the owner choose whether labelling a clip "good" also flags it into
  the reference set
- [ ] 🟢 Library: drag a clip onto a folder inside the right-hand list (currently only onto
  the folder tree); rename/move multi-selection prompts
- [ ] 🟢 Grade tier (3A/3B/4/5) one-key labelling on Collect -> Review (defect class only
  for now; tiers still available on Slice)
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

- [x] **v0.4 - Labelling tool, Nano striker and Test Tile screen** (2026-10-22, branch
  `feature/striker-and-labelling`, plan in `docs/PLAN_striker_labelling.md`, 360 tests). One
  commit per step:
  - Labelling tool (`python main.py label`): `strike_features.py` (strike features anchored on a known
    strike time, f55c2e8), `io/session_reader.py` (read-only loader for station sessions, 21ab9c8),
    `io/label_store.py` (labels.json, atomic writes, CSV export, aee04a9), `label_model.py` (da207a9),
    `app/label_tool.py` (a334c85, 821bad2, 879ef2d).
  - Striker: `striker/` firmware + protocol spec copied from the tile-line project (89b9db5),
    `io/nano_protocol.py` (c3ab3c1), `io/nano_flash.py` + `python main.py flash` - a real compile for
    AVR works, 17,308 B flash / 1,397 B RAM (fbc0b39), `io/nano_link.py` (4f86ac0),
    `io/audio_ring.py` (00ce530).
  - Sound grade: `strike_reference.py` + Build sound reference button + leave-one-out self-check (043daa9).
  - Test Tile: `tile_test.py` + `io/strike_log.py` (34dd5a8), `app/screens_tester.py` (864d45a), the
    Label tiles hub screen and the app opening on Test Tile (a0d8c2e).
  - Analysed the 55 real strike clips from 2026-10-19: tile vs striker alone separates cleanly (energy at
    1-3 kHz, AUC 1.00); good vs defective cannot be told without labels (the camera's 13/22 Rejects with
    corner fill 0.89-0.97 look like false rejects, so it is not ground truth).
  - Not verified: any of it on the real rig (see In Progress). Found a real bug while testing: the link's
    heartbeat state stored the distance under a different key than it was initialised with.

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
