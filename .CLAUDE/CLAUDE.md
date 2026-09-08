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
- **Status:** v0.1, in active build. DSP core + `features.py` are done and tested
  (Phases 0-2, 83 tests). `io/`, `classify/`, `app/` and the noise/filter `dsp` modules
  are next — see `TODO.md` for the phase plan and `docs/UI_DESIGN.md` for the GUI.
  Sections below marked `[built]` are real; the rest is planned - keep in sync as
  modules land.
- **Entry points (planned):**
  - `python -m acoustic_analysis` — GUI
  - `python -m acoustic_analysis.cli devices` — list input devices
  - `python -m acoustic_analysis.cli analyze <path|dir> [--export features.csv]` — headless

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

> DSP core + `features.py` are built (Phases 0-2). `io/`, `classify/`, `app/` and the
> extra `dsp` modules below are planned - update as they land. Build order and the
> GUI screen list are in `TODO.md`; the GUI look is in `docs/UI_DESIGN.md`.

```
acoustic_analysis/
  __init__.py
  __main__.py           launches the GUI
  config.py             load_config / resolve_path            [built]
  cli.py                devices | analyze | noise | calibrate | export
  dsp/                  PURE - numpy array in, numbers out, no audio/file/GUI I/O
    conditioning.py     remove_dc, apply_calibration, bandpass, detect_impact, window_*   [built]
    spectrum.py         fft_magnitude, dominant_frequency, pick_peaks, spectral_*         [built]
    octave_bands.py     fractional_octave_levels, band_shape, band_ratios (IEC 61260)     [built]
    decay.py            energy_decay_curve (Schroeder), reverb_time, decay_rate, per_band_decay  [built]
    weighting.py        a/c/z weighting (IEC 61672)                                        [built]
    sound_level.py      leq, lpeak, exp time weighting, percentile_levels                 [built]
    filters.py          FilterChain: bandpass + notches + weighting; .apply / .frequency_response
    noise.py            noise profile + spectral subtraction / gating denoise
    environment.py      NC rating, octave spectrum, Leq/L90/L10, dominant tones
    loudness.py         equal-loudness-contour phon/sone   (deferred)
  features.py           extract_features(clip, fs, cfg) -> dict   (orchestrates dsp/*)    [built]
  classify/
    reference.py        ReferenceProfile.build / compare / save / load
    rules.py            grade(features, profile, cfg) -> good / borderline / defective / retest
  io/
    recorder.py         sounddevice InputStream wrapper: devices, gain, ring buffer, trigger, live monitor
    audio_out.py        sounddevice OutputStream playback (A/B listening)
    wavstore.py         save_clip / load_clip  (WAV + JSON sidecar)
    dataset.py          SQLite: sessions / clips / features / labels; add / query / export_csv
  app/                  Tkinter, laptop desktop, mouse+keyboard. Plain ttk.Notebook tabs
                        first, then an instrument-look restyle (docs/UI_DESIGN.md)
    main_window.py      Tk root, notebook/shell, background worker thread, shared state
    state.py            SharedState - thread-safe latest-value store
    widgets.py          plot panel (+ "?" explainer), param slider, level meter, feature table
    screen_*.py         monitor / record / analyze / compare / filters / noise / label /
                        dataset / calibrate / learn / settings
    theme.py            dark instrument ttk style + dark matplotlib style   (restyle phase)
config.yaml             all tunable parameters
tests/                  one module per pure module, synthetic signals
data/                   recordings/, acoustic_analysis.sqlite, exports/   (git-ignored)
docs/METHODS.md         analysis methods + standards
docs/UI_DESIGN.md       GUI layout and the instrument look
docs/EXPLAIN.md         the text behind every in-app "what is this" panel
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

> Planned interfaces — fill in real signatures, return types, and raised exceptions as
> each module is written. Until then, `docs/METHODS.md` is the spec.

- **`config.py`** — `load_config(path=None) -> dict`. Reads `config.yaml` from the repo
  root (or a given path). No other responsibility.
- **`dsp/*`** — pure functions, each covered by `tests/test_<module>.py` with synthetic
  signals. See `docs/METHODS.md` §3 for what each computes and the standard it follows.
- **`features.py`** — `extract_features(clip: np.ndarray, fs: int, cfg: dict) -> dict`.
  The single orchestration point; the dict it returns is the dataset row and the
  classifier input.
- **`classify/`** — rule-based grading against a reference profile built from known-good
  clips. `docs/METHODS.md` §6.
- **`io/`** — the only modules that touch the mic, the filesystem, or SQLite. Not unit
  tested (hardware/IO wrappers); smoke-tested manually.
- **`app/`** — Tkinter, thin. Widgets wired to backend calls; no analysis logic here.

---

## Data Files

| Path | What | Git |
|---|---|---|
| `config.yaml` | all tunable parameters (audio device, sample rate, window timings, band-pass, octave fraction, weighting, calibration factor, label set, paths) | tracked |
| `data/recordings/` | captured / imported WAV clips + JSON sidecars | ignored |
| `data/acoustic_analysis.sqlite` | clips / features / labels database | ignored |
| `data/exports/` | CSV / Parquet feature-dataset exports | ignored |

`.gitignore` covers `data/`, `*.wav`, `venv/`. Audio datasets are never committed.

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

- DSP core + `features.py` are built and tested; `io/`, `classify/`, `app/` and the
  noise/filter `dsp` modules are still planned (see `TODO.md`).
- Every threshold that will land in `config.yaml` (band-pass edges, impact multiplier,
  window timings, grading limits) is a placeholder — none tuned against real recordings.
- No calibration path yet; levels will be relative until a pistonphone calibration is
  implemented and run (`docs/METHODS.md` §7).
- `dsp/loudness.py` (equal-loudness-contour loudness) is deferred, not designed.
- The label taxonomy in `config.yaml` (`good` / `cracked` / `corner_broken` /
  `other_defect`) is provisional — no labelled data exists to validate it against.
- No real damaged-tile recordings exist. Calibration and threshold tuning are blocked on
  getting good *and* defective sample parts.
- Windows-only audio testing; Linux/macOS device handling unverified.

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
