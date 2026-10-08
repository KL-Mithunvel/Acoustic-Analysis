# CLAUDE.md

> **IMPORTANT:** Read `CLAUDE-COMMON.md` first — it contains general must-follow instructions (companion files, deployment model, workflow, template structure). This file contains repo-specific instructions. Anything here overrides `CLAUDE-COMMON.md`.
>
> **Also read `PROJ_STARTER.md`** — it contains the owner's personal preferences (interaction rules, coding standards, tech stack choices, commit style). Those rules apply to this project; the User Rules section at the bottom points to them.

---

## Project Overview

**Acoustic-Analysis** is a Windows desktop workbench for impact-acoustic analysis and
data labelling. Record or import tap-test sound clips, run a full acoustic-analysis
suite (fractional-octave bands, spectral descriptors, decay/damping, level metrics),
visualise and compare them, assign a quality label, and export a labelled feature
dataset for training a classifier.

- **Problem it solves:** a sound part rings clearly when tapped; a cracked one sounds
  duller, shorter, lower. Those differences are measurable. This tool measures them
  consistently, shows them, and captures labelled examples so a model can learn the
  boundary. First use case: clay roofing tiles — but the analysis is not tile-specific.
- **Owner:** kl mithunvel (klm@smtw.in). MIT licence (`LICENSE`).
- **Relationship to Tile Sorting:** developed for the Tile Sorting inspection project
  (VIT Chennai BMEE497J/BMHA497J) but deliberately standalone. That project consumes
  only the *exported dataset* and the *model trained from it* — never this repo's code.
  No import goes either direction; code is copied by hand when needed.
- **Runtime:** Python 3.13+. GUI: Tkinter. DSP: numpy / scipy. Audio: sounddevice /
  soundfile. Video/audio demux: ffmpeg via imageio-ffmpeg. Plots: matplotlib. Storage:
  SQLite. Config: YAML. Tests: pytest.
- **Status:** v0.2, end-to-end working. DSP core, feature extraction, noise/filter
  modules, **video slicing** (import tap-test footage, detect every strike, cut and
  label one snippet per tap), I/O (WAV + SQLite + recorder + playback + ffmpeg),
  rule-based classification, the headless CLI, and the full Tkinter GUI (13 screens,
  dark instrument-look shell with a left sidebar nav, opening on a Home
  launcher/session-summary screen) are all built and tested - 197 tests. Not yet done:
  real-mic verification, pistonphone calibration against hardware, threshold tuning on
  real tiles *and on real footage*, PyInstaller build, `dsp/loudness.py`. See
  `TODO.md`.
- **v0.3 (2026-10-08) - collection workflow.** Added a guided **Collect** screen
  (Setup / Listen / Review; sound-triggered capture, motor spectral profile + striker
  time-domain template removed from every strike, automatic tile / no-tile sort), a
  **Library** file manager (real folders, rename/move/drag-drop/delete with undo, keeps
  wav + sidecar + db path together), a sidebar cut to Collect / Library / Analyze /
  Export + APP + a collapsible ADVANCED group (the old right icon rail and native menu
  bar are gone), and plain-language **Basic settings** saved to
  `data/user_settings.yaml` (never rewrites `config.yaml`, which would strip its
  comments). 237 tests. **All of it is verified on synthetic signals only - none of it
  has touched the real microphone or the real striker rig.**
- **Entry points:**
  - `python main.py` — one-command launcher: bootstraps `./venv` + deps on first run,
    then the GUI (or forwards args to the CLI)
  - `python -m acoustic_analysis` — GUI, opens on **Collect**. Sidebar: Collect / Library /
    Analyze / Export; Home / Settings / Learn; ADVANCED (Slice / Compare / Filters /
    Noise / Calibrate / Monitor / Record / Label)
  - `python tools/make_screenshots.py` — regenerates `docs/screenshots/` (README images)
    from the real app on synthetic demo data (Windows, needs a visible desktop)
  - `python -m acoustic_analysis.cli devices | analyze | noise | calibrate | export`

---

## Running the System

```powershell
# Activate the venv first, every session (Windows / PowerShell)
python -m venv venv          # first time only
venv\Scripts\activate
pip install -r requirements.txt   # first time / after dependency changes

# List input devices; put the right index in config.yaml
python -m acoustic_analysis.cli devices

# GUI
python -m acoustic_analysis

# Headless analysis
python -m acoustic_analysis.cli analyze recordings\tile_0001.wav
python -m acoustic_analysis.cli analyze recordings\ --export features.csv

# Tests + lint (before every commit)
python -m pytest -q
Get-ChildItem -Recurse -Filter *.py acoustic_analysis | ForEach-Object { python -m py_compile $_.FullName }
```

There is no hardware or production mode — this is a desktop app. Its only device
dependency is a microphone (`io/recorder.py`); the simulated equivalent, per
`CLAUDE-COMMON.md`'s deployment model, is importing a WAV file or a synthetic signal.

---

## Architecture

Everything below is built and tested unless marked otherwise.

```
main.py                 one-command launcher: bootstrap ./venv + deps, then GUI or CLI
acoustic_analysis/
  __main__.py           launches the GUI (falls back to CLI help)
  config.py             load_config / resolve_path
  cli.py                devices | analyze | noise | calibrate | export
  dsp/                  PURE - numpy array in, numbers out, no audio/file/GUI I/O
    conditioning.py     remove_dc, apply_calibration, bandpass, detect_impact, window_relative
    spectrum.py         fft_magnitude, dominant_frequency, pick_peaks, spectral_*
    octave_bands.py     octave_band_frequencies, fractional_octave_levels, band_shape, band_ratios
    decay.py            energy_decay_curve (Schroeder), reverb_time, decay_rate, per_band_decay
    weighting.py        A/C/Z weighting (IEC 61672 -> bilinear -> SOS)
    sound_level.py      leq, lpeak, exp_time_weight (fast/slow/impulse), percentile_levels
    filters.py          FilterChain: bandpass + notches + weighting; .apply / .frequency_response
    noise.py            noise_profile, reduce_noise (STFT spectral subtraction / gating)
    environment.py      nc_rating, dominant_tones, environmental_analysis
    segmentation.py     moving_rms, envelope_minmax, noise_floor, detect_onsets,
                        segments_from_onsets - cutting a long take into strikes
    trigger.py          SoundTrigger - block-by-block continuous trigger, adaptive threshold
                        (floor_mult x tracked background), pre-roll, cooldown
    machine_noise.py    build_striker_template (aligned average of dry strikes + repeatability),
                        subtract_striker (align +/-max_shift_ms, LS-scale, clamp), clean_clip
                        (strike -> template -> motor spectral -> tile/no_tile/no_strike verdict)
    loudness.py         equal-loudness-contour phon/sone   [DEFERRED - not written]
  features.py           conditioned_windows (shared), extract_features -> flat dict + validity gate
  segments.py           PURE - Segment / SnippetSet + add/remove/renumber/snap/summary
  classify/
    reference.py        ReferenceProfile.build / compare / save / load
    rules.py            grade(features, profile, cfg) -> RETEST/UNGRADED/GOOD/BORDERLINE/DEFECTIVE
  io/                   the only modules that touch mic / speakers / disk / db
    recorder.py         list_input_devices, LiveMonitor, Recorder (manual/rms trigger)  [hardware - smoke only]
    audio_out.py        peak-limited playback                                           [hardware - smoke only]
    wavstore.py         save_clip / load_clip (float WAV + JSON sidecar)
    videoaudio.py       ffmpeg: extract_audio (cached), extract_frame_png, probe  [subprocess - smoke only]
    snippets.py         <video>.snippets.json sidecar - in-progress cuts, save/load
    library.py          Library - the ONLY place clips are renamed/moved/deleted: root-confined
                        paths, no overwrite, delete -> .trash, undo stack, on_path_changed hook
                        (-> Dataset.update_path). Dot-folders (.trash, .raw) are hidden.
    session.py          SessionStore.handle - clean + file one captured clip: tile ->
                        <session>/, no tile -> <session>/rejected/, raw -> <session>/.raw/
    machine_profile.py  MachineProfile (motor recording + StrikerTemplate) save/load as .npz
    dataset.py          SQLite: sessions / clips / features / labels (label + grade_tier);
                        export_csv / export_json; _migrate() adds columns to old files
  app/                  Tkinter, laptop desktop, dark instrument-look shell
    main_window.py      Tk root, status bar (+ Open/Help buttons) + left sidebar nav (collapsible ADVANCED) + soft-key bar, worker poll
    theme.py            dark ttk style + matching matplotlib rcParams
    state.py            SharedState + ClipData - thread-safe clip list, selection, profile
    service.py          AnalysisService - feature extraction + grade on a worker thread
    explain.py          loads docs/EXPLAIN.md -> Explainer facade
    plots.py            draw_* functions onto a given Axes (Agg-testable)
    widgets.py          MplPanel (figure + "?" popup), FeatureTree, info_button
    screens_home.py     Home - launcher + current-session summary (clip count, last grade,
                        calibration state, reference-profile state, recent clips)
    screens.py          Analyze, Compare, Filters, Noise, Label, Dataset, Learn
    screens_live.py     Monitor, Record, Calibrate, Settings
    screens_video.py    Slice - video -> waveform -> cut -> label -> dataset
    screens_collect.py  Collect - Setup / Listen / Review. Audio callbacks only put items on a
                        queue; the Tk thread drains it (_pump, 50 ms). Owns no DSP.
    screens_library.py  Library - file manager UI over io/library.Library (drag-drop onto tree)
config.yaml             all tunable parameters
tests/                  test_<module>.py, synthetic signals; test_app_gui_smoke.py +
                        test_app_slice_gui.py (skip w/o display); test_video_slicing.py
                        (skips w/o ffmpeg - builds a real video and slices it)
data/                   recordings/, acoustic_analysis.sqlite, exports/, presets/,
                        cache/ (decoded video audio)  (git-ignored)
docs/METHODS.md         analysis methods + standards
docs/UI_DESIGN.md       GUI layout and the instrument look
docs/EXPLAIN.md         the text behind every in-app "?" panel
```

### Data flow (per clip)

```text
mic (sounddevice, background thread)  OR  imported WAV
  OR  tap-test video -> io/videoaudio (ffmpeg) -> dsp/segmentation -> one clip per strike
        |
        v
io/recorder or io/wavstore  ->  raw mono float array + sample rate
        |
        v
dsp/conditioning  ->  calibrate, DC-remove, detect impact t0, band-pass, window ring/decay
        |
        v
features.extract_features()  ->  {octave bands, spectral descriptors, decay, levels, SNR, ...}
        |
        +--> io/dataset  (SQLite: clip row + feature blob)
        |
        +--> classify/rules.grade()  (if a reference profile is loaded)
        |
        v
app/*  ->  plots + label entry ; or cli ->  stdout / CSV
```

### Threading model

- `io/recorder.py`'s `sounddevice.InputStream` runs its callback on PortAudio's own
  thread; captured clips cross to the app via a `queue.Queue`.
- The GUI runs feature extraction on a single background worker thread; results are
  pushed back to the Tk main thread via a queue + `after()` poll. `dsp/` and `features`
  are pure and hold no shared state, so no locking is needed there.

### Simulation vs real

The only "real" component is the microphone. `io/recorder.py` is the thin hardware
wrapper; importing a WAV (`io/wavstore.py`) or generating a synthetic signal (tests) is
the dev-machine path and exercises the entire pipeline downstream of capture.

---

## Key Modules

`docs/METHODS.md` §3 is the spec for what each `dsp` function computes and the standard
it follows; `docs/EXPLAIN.md` is the user-facing version of the same.

- **`config.py`** — `load_config(path=None) -> dict`, `resolve_path(cfg, key)` (repo-root
  anchored), `repo_root()`.
- **`dsp/*`** — pure functions, each covered by `tests/test_<module>.py` with synthetic
  signals whose correct output is hand-derivable.
- **`features.py`** — `conditioned_windows(clip, fs, cfg)` does the shared
  calibrate → impact → window → band-pass and is used by both `extract_features` and
  `app/plots.py` so the GUI shows exactly the analysed signal. `extract_features` returns
  a flat dict + `valid`/`status`/`reasons`; the dict is the dataset row and the classifier
  input.
- **`classify/`** — `ReferenceProfile` (mean/std of scalar features + octave shape,
  z-score `compare`); `grade()` rule verdict + reasons, thresholds from `config.grading`.
- **`dsp/segmentation.py`** — the long-take -> snippets half of the pipeline:
  `detect_onsets` (envelope + percentile noise floor + refractory gap + loudness
  filter, each onset walked back to its attack), `segments_from_onsets` (windows,
  clamped and trimmed so consecutive snippets never share audio),
  `envelope_minmax` (min/max decimation, so a 10-minute waveform can be drawn).
  Pure; `docs/METHODS.md` §1a is the spec.
- **`segments.py`** — `Segment` (a time range + a grade tier + a defect class) and
  the list rules: time-ordered numbering, overlap refusal, snapping a hand-drawn
  selection onto a detected strike, per-axis label application, summary counts.
  Pure, no numpy.
- **`io/`** — mic / speakers / disk / SQLite / ffmpeg wrappers. `recorder`/`audio_out`
  are hardware, lazy-import `sounddevice`, smoke-tested only. `videoaudio` shells out
  to ffmpeg (system PATH first, then the `imageio-ffmpeg` bundled binary) and caches
  decoded audio under `data/cache/` keyed by path+mtime+rate. `audio_out.Player` is an
  `OutputStream` that reports its position, which `sd.play` cannot - that is what makes
  a moving playhead possible.
- **`app/`** — Tk on the main thread, `AnalysisService` worker off it. `plots.py` and
  `explain.py` are Tk-free and unit-tested; the screens are covered by
  `test_app_gui_smoke.py` (constructs the window, analyses a clip, visits every screen)
  and `test_app_slice_gui.py` (drives Slice against a real video: open, detect, label,
  save, and check the resulting database rows).
  **`app/screens_video.py` (Slice)** owns no logic of its own - detection, snippet
  arithmetic and file work all live in `dsp/segmentation.py`, `segments.py` and `io/`.
  Its own background threads do audio extraction, frame grabs and the slow half of
  saving (WAV + features); **database writes happen on the Tk thread**, because
  `Dataset`'s sqlite3 connection belongs to the thread that opened it.

---

## Data Files

| Path | What | Git |
|---|---|---|
| `config.yaml` | all tunable parameters (audio device, sample rate, window timings, band-pass, octave fraction, weighting, calibration factor, label set, paths) | tracked |
| `data/recordings/` | saved clip WAVs + JSON sidecars | ignored |
| `data/acoustic_analysis.sqlite` | sessions / clips / features / labels | ignored |
| `data/exports/` | CSV / JSON feature-dataset exports | ignored |
| `data/reference_profile.json` | the active reference profile (auto-loaded on start) | ignored |
| `data/presets/` | saved config presets | ignored |
| `data/cache/` | audio tracks decoded out of videos, keyed by path+mtime+rate (`video.cache_dir`, relative to `paths.data_dir`) | ignored |
| `<video>.snippets.json` | in-progress cuts + labels, written beside the source video (not under `data/`, so the work travels with the footage) | n/a - lives with the video |

`.gitignore` covers `data/`, `venv/`, `*.wav`, `*.sqlite`, and images (the CoCo-80X
reference screenshot in `docs/` stays local). Audio datasets are never committed.

---

## Platform Constraints

- **Primary target: Windows 10/11.** The `dsp/` core is pure numpy/scipy and
  cross-platform; audio device handling is only tested on Windows.
- `sounddevice` / PortAudio is cross-platform, but the device index in `config.yaml` is
  machine-specific — re-check `cli.py devices` on every new machine.
- **Windows "microphone enhancements" (AGC / noise suppression)** must be disabled
  manually in Sound Control Panel → input device → Properties → Enhancements. They
  cannot be controlled from Python and make level and spectrum data untrustworthy until
  off. See `docs/METHODS.md` §8.
- No GPIO / serial / I2C. The microphone is the only device dependency.
- `tkinter` ships with the python.org Windows installer; on a stripped Python it may
  need to be added.

---

## Known Technical Debt

- **Every threshold in `config.yaml` is provisional** — band-pass edges, impact
  multiplier, window timings, SNR floor, all of `grading` — none tuned against real
  recordings. Marked `provisional` in the file.
- **Never run against a real microphone.** `io/recorder.py` / `audio_out.py` are written
  and smoke-tested (`list_input_devices` works, 12 devices found) but a full
  capture → analyse loop with a real mic has not happened. Live monitoring and the
  Record screen are unverified end to end.
- **No calibration performed.** `calibrate` (CLI + screen) is implemented; no pistonphone
  tone has been measured, so levels are relative (dBFS-referenced), not dB SPL.
- **No real tile recordings.** No reference profile exists; grading is untested on real
  good vs defective parts. Label taxonomy (`good`/`cracked`/`corner_broken`/`other_defect`)
  is a guess, and so is the grade-tier set (`3A`/`3B`/`4`/`5`, taken from the camera
  station).
- **Video slicing has never seen real footage** (added 2026-09-20). The Slice screen,
  `dsp/segmentation.py`, `io/videoaudio.py` and the sidecar are built and tested end to
  end - including against real `.mp4` files - but every one of those videos was
  *generated*: clean synthetic taps, no room reverb, no handling noise, no talking, no
  phone-mic AGC. Expect `config.yaml` `video.onsets` to need real tuning on the first
  actual recording. The likely failure modes, in order: phone AGC flattening the level
  differences the percentile noise floor depends on; speech between taps clearing
  `min_peak_ratio`; and taps faster than `min_gap_s` being merged. The sensitivity
  slider is on the toolbar precisely because the default will be wrong.
- **`video.snippet.post_ms` (700 ms) is a guess.** It has to outlast the ring of a real
  tile, and no real tile has been recorded. Too short truncates the decay fit, which is
  one of the more discriminating features.
- **Collect / machine-noise removal has never run on the real rig** (added 2026-10-08).
  `SessionRecorder`, `SoundTrigger`'s adaptive threshold, the striker-template
  subtraction and the tile/no-tile verdict are tested only against synthetic signals
  with known answers. Unknowns: whether the real striker is repeatable enough (the
  repeatability score exists to tell), whether `machine.*` thresholds
  (`min_residual_snr_db`, `max_shift_ms`, `fit_ms`, ...) suit real tiles, and how the
  solenoid click overlapping the first ms of the tile ring affects features. The
  `machine:` and `capture.floor_mult` values are provisional. With no template recorded a
  striker click reads as a tile, so tile/no-tile only works after Setup step B.
- **`Collect` does not set the reference-set flag** when labelling; "Build reference from
  flagged" still needs the Label screen's "add to reference set". Left as-is on purpose
  (whether "good" implies "reference" is the owner's call).
- **Tk test flakiness:** creating many `tk.Tk()` roots in one pytest process intermittently
  raises `TclError` inside `tk.Tk()` (seen as a missing `init.tcl` / `tcl_findLibrary`).
  `test_app_collect_gui.py` therefore shares one module-scoped window; keep new GUI
  tests on a shared window rather than one per test.
- `Library` renames/moves only keep the database in step when done through it; moving
  files in Explorer leaves `clips.path` pointing at the old location.
- `dsp/loudness.py` (equal-loudness-contour phon/sone) — deferred, not written.
- Denoise (`noise.reduce_noise`) can run in the analysis path (`noise.apply_in_analysis`)
  but features from denoised audio are not validated and can mislead.
- GUI verified by construction/smoke tests, the scripted Slice run in
  `test_app_slice_gui.py`, and one manual 3 s launch; no sustained interactive session
  or usability pass. In particular the Slice screen has been driven programmatically but
  never *watched* - drag-to-select feel, playhead smoothness, and how the frame preview
  keeps up while scrubbing are all unassessed.
- **Playback while slicing is untested against hardware.** `audio_out.Player` is new and,
  like the rest of `io/audio_out.py`, has never produced sound in a verified run; the
  Slice tests exercise navigation and saving, not audio output.
- `bilinear` A/C weighting drifts from the IEC curve above ~5 kHz (no pre-warp) — fine
  for a feature, not for certified SLM use. Noted in `weighting.py`.
- No PyInstaller build yet — runs from source only.
- Windows-only. Linux/macOS audio-device handling unverified.

---

## Development Rules

1. **DSP stays pure.** Everything in `dsp/` and `features.py` takes numpy arrays and
   returns numbers/dicts — no audio, file, or GUI calls. Hardware and file I/O live only
   in `io/`; GUI only in `app/`.
2. **No hardcoded parameters.** Sample rate, device, band-pass edges, window timings,
   octave fraction, thresholds — all in `config.yaml`, passed in as arguments. Never
   inline in source.
3. **Provisional thresholds are labelled as such.** Any value tuned on a laptop mic or a
   substitute impactor is marked provisional in code and docs until recalibrated on the
   real measurement rig.
4. **GUI stays thin.** `app/*` only wires widgets to backend functions. If it contains
   analysis logic, that logic belongs in a backend module.
5. **Every `dsp/` function has a pytest test with synthetic signals** — a known input
   whose correct output can be computed by hand (sine → FFT peak, `e^(−t/τ)` → T20, …).
6. **This repo is standalone.** It never imports from the Tile Sorting project and vice
   versa. Data crosses as exported files; code crosses by manual copy only.

---

## Project TODO List

Tracked in `TODO.md` at the repo root, not duplicated here.

---

## User Rules

The owner's standing rules live in `PROJ_STARTER.md` and the Standard User Rules in
`CLAUDE-COMMON.md` — both apply to this project in full. Key points that bite most often:

- Open every response with **"ok KLM"** + a one-line statement of what you are about to
  do.
- **Explain before acting** — before any file write or code change, list every file that
  will change and what changes, and wait for explicit confirmation.
- Every commit ends with `Co-authored-by: kl mithunvel <klm@smtw.in>`.
- Commit subject: imperative, ≤ 72 chars, no trailing period, no vague messages.
- Activate the venv before any `python` / `pip`. Keep `requirements.txt` pinned to at
  least the major version. `uv` migration is planned — flag it when relevant.
- `CLAUDE-COMMON.md` is a shared file from another repo — **do not edit it**; raise
  needed changes with the owner.

### Project-Specific Overrides

_None yet._
