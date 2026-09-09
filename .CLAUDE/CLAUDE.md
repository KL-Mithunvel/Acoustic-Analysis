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
  soundfile. Plots: matplotlib. Storage: SQLite. Config: YAML. Tests: pytest.
- **Status:** v0.1, end-to-end working. DSP core, feature extraction, noise/filter
  modules, I/O (WAV + SQLite + recorder + playback), rule-based classification, the
  headless CLI, and the full Tkinter GUI (12 screens, dark instrument-look shell with a
  left sidebar nav, opening on a Home launcher/session-summary screen) are all built and
  tested - 133 tests. Not yet done: real-mic verification, pistonphone calibration
  against hardware, threshold tuning on real tiles, PyInstaller build, `dsp/loudness.py`.
  See `TODO.md`.
- **Entry points:**
  - `python main.py` — one-command launcher: bootstraps `./venv` + deps on first run,
    then the GUI (or forwards args to the CLI)
  - `python -m acoustic_analysis` — GUI (Home / Monitor / Record / Analyze / Compare /
    Filters / Noise / Label / Dataset / Calibrate / Learn / Settings)
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
    loudness.py         equal-loudness-contour phon/sone   [DEFERRED - not written]
  features.py           conditioned_windows (shared), extract_features -> flat dict + validity gate
  classify/
    reference.py        ReferenceProfile.build / compare / save / load
    rules.py            grade(features, profile, cfg) -> RETEST/UNGRADED/GOOD/BORDERLINE/DEFECTIVE
  io/                   the only modules that touch mic / speakers / disk / db
    recorder.py         list_input_devices, LiveMonitor, Recorder (manual/rms trigger)  [hardware - smoke only]
    audio_out.py        peak-limited playback                                           [hardware - smoke only]
    wavstore.py         save_clip / load_clip (float WAV + JSON sidecar)
    dataset.py          SQLite: sessions / clips / features / labels; export_csv / export_json
  app/                  Tkinter, laptop desktop, dark instrument-look shell
    main_window.py      Tk root, status bar + left sidebar nav + button rail + soft-key bar, worker poll
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
config.yaml             all tunable parameters
tests/                  test_<module>.py, synthetic signals; test_app_gui_smoke.py (skips w/o display)
data/                   recordings/, acoustic_analysis.sqlite, exports/, presets/  (git-ignored)
docs/METHODS.md         analysis methods + standards
docs/UI_DESIGN.md       GUI layout and the instrument look
docs/EXPLAIN.md         the text behind every in-app "?" panel
```

### Data flow (per clip)

```text
mic (sounddevice, background thread)  OR  imported WAV
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
- **`io/`** — mic / speakers / disk / SQLite wrappers. `recorder`/`audio_out` are
  hardware, lazy-import `sounddevice`, smoke-tested only.
- **`app/`** — Tk on the main thread, `AnalysisService` worker off it. `plots.py` and
  `explain.py` are Tk-free and unit-tested; the screens are covered by
  `test_app_gui_smoke.py` (constructs the window, analyses a clip, visits every screen).

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
  is a guess.
- `dsp/loudness.py` (equal-loudness-contour phon/sone) — deferred, not written.
- Denoise (`noise.reduce_noise`) can run in the analysis path (`noise.apply_in_analysis`)
  but features from denoised audio are not validated and can mislead.
- GUI verified by a construction/smoke test + one manual 3 s launch; no sustained
  interactive session or usability pass.
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
