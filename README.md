# Acoustic-Analysis

A desktop workbench for **impact-acoustic analysis and data labelling** — record or
import tap-test sound clips, run a full acoustic-analysis suite on them (octave bands,
spectral descriptors, decay/damping, level metrics), compare them side by side, assign a
quality label, and export a labelled feature dataset for training a classifier.

Built for **acoustic non-destructive testing** — striking an object with a repeatable
impact and reading its ringing response to tell a sound part from a cracked one. The
first use case is clay/ceramic roofing tiles, but nothing in the analysis is
tile-specific.

> **Status: v0.1, working end to end.** DSP core, feature extraction, noise + filter
> tools, WAV/SQLite storage, rule-based grading, a headless CLI and an 11-screen
> Tkinter GUI (styled like a handheld analyser) are all built and tested (133 tests).
> Not yet done: real-microphone verification, pistonphone calibration, threshold
> tuning on real tiles, a packaged executable. See [`TODO.md`](TODO.md).

> Part of the **Tile Sorting** automated inspection project (VIT Chennai,
> BMEE497J/BMHA497J). This repo is deliberately standalone and reusable — the tile line
> consumes only the *exported dataset* and the *model trained from it*, never this app's
> code directly.

---

## Why

A good tile, tapped, gives a clear sonorous ring. A tile with a crack or an internal
void gives a duller, shorter, lower sound — the resonance shifts, the high-frequency
bands drain, and the ring decays faster. Those differences are measurable. This tool
exists to **measure them consistently, look at them, label them, and build a dataset**
so a model can learn the boundary.

## Features

- **Capture** — record clips from any input device (`sounddevice`) with a pre-trigger
  ring buffer and manual/amplitude trigger, or import WAV files (many at once).
- **Analysis suite** (see [`docs/METHODS.md`](docs/METHODS.md)):
  - fractional-octave-band levels (1/1 … 1/12 octave, IEC 61260 band edges)
  - FFT spectrum + descriptors: dominant frequency, peaks with Q, spectral
    centroid / bandwidth / roll-off / flatness
  - decay: Schroeder energy-decay curve, T20 / T30, decay rate, **per-octave-band
    decay rate** (the damping signature of a crack)
  - level metrics: L_eq, L_peak, Fast/Slow/Impulse time weighting, statistical levels Ln
  - A / C / Z frequency weighting (IEC 61672)
  - equal-loudness-contour loudness in sones *(deferred)*
- **Compare** — several clips overlaid on spectrum / octave / decay, with a ranked
  "biggest differences" view.
- **Filters** — the whole filter chain (band-pass + notches + weighting) with
  live-editable parameters, a frequency-response plot, and before/after of the selected
  clip. What you see is what feeds analysis.
- **Noise** — capture a noise profile, run environmental analysis (Leq, L10/50/90, NC
  rating, dominant tones), and preview spectral-subtraction denoising.
- **Label & dataset** — assign a quality class + grader + notes; build a reference
  profile from flagged clips; everything in a local SQLite database; export to CSV / JSON
  for model training.
- **Grade** — rule-based GOOD / BORDERLINE / DEFECTIVE / RETEST against the reference,
  with the reasons that decided it.
- **Learn** — a synthetic-signal bench and a glossary, because every chart in the app
  also carries a "?" that explains what it is.
- **Headless CLI** — `devices`, `analyze`, `noise`, `calibrate`, `export`.

The GUI is a plain windowed Tkinter app styled like a handheld acoustic analyser: a dark
screen, a fixed top status bar, a persistent button rail, and a per-screen soft-key row
(see [`docs/UI_DESIGN.md`](docs/UI_DESIGN.md)).

## Requirements

- Windows 10/11 (primary target; the DSP core is cross-platform, audio device handling
  is tested on Windows)
- Python 3.13+
- A microphone. For real measurement work a measurement mic is strongly preferred over a
  laptop's built-in array — see [`docs/METHODS.md`](docs/METHODS.md).

## Install

```powershell
git clone https://github.com/KL-Mithunvel/Acoustic-Analysis.git
cd Acoustic-Analysis
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Quick start

```powershell
venv\Scripts\activate

# List input devices, pick the index of your mic, put it in config.yaml
python -m acoustic_analysis.cli devices

# Launch the GUI
python -m acoustic_analysis

# Or headlessly
python -m acoustic_analysis.cli analyze recordings\tile_0001.wav
python -m acoustic_analysis.cli analyze recordings\ --export features.csv --profile ref.json
python -m acoustic_analysis.cli noise room.wav
python -m acoustic_analysis.cli calibrate pistonphone.wav --level-db 94
```

Run the tests:

```powershell
python -m pytest -q
```

## Project layout

```
acoustic_analysis/
  config.py            load config.yaml
  cli.py               headless: devices | analyze | noise | calibrate | export
  dsp/                 PURE signal processing — numpy in, numbers out, no I/O
    conditioning · spectrum · octave_bands · decay · weighting · sound_level
    filters (chain + Bode) · noise (profile + denoise) · environment (NC / Ln / tones)
  features.py          conditioned_windows + extract_features -> one dict per clip
  classify/            reference.py (profile) + rules.py (grade)
  io/                  recorder + audio_out (sounddevice), wavstore, dataset (SQLite)
  app/                 Tkinter GUI: theme, state, service, explain, plots, widgets,
                       screens (Analyze/Compare/Filters/Noise/Label/Dataset/Learn),
                       screens_live (Monitor/Record/Calibrate/Settings)
config.yaml            all tunable parameters
tests/                 test_<module>.py (synthetic signals) + test_app_gui_smoke.py
data/                  recordings, SQLite db, exports, presets  (git-ignored)
docs/METHODS.md        analysis methods + standards
docs/UI_DESIGN.md      GUI layout / the instrument look
docs/EXPLAIN.md        the text behind every in-app "?" panel
```

## How it works

Each clip goes through the same chain — condition → detect impact → window the ring →
extract features → (optionally) grade against a reference. The methods, the standards
they follow, and the reasoning behind each metric are in
**[`docs/METHODS.md`](docs/METHODS.md)**.

## Roadmap

See [`TODO.md`](TODO.md). Short version: DSP core + tests → audio I/O + dataset store →
GUI → reference-profile / rule grading → (separate repo) train a model on the exported
dataset.

## Contributing

Issues and PRs welcome. The one hard rule: keep `dsp/` pure and synthetic-testable — no
audio, file, or GUI calls in there. See [`.CLAUDE/CLAUDE.md`](.CLAUDE/CLAUDE.md)
Development Rules.

## Licence

MIT — see [`LICENSE`](LICENSE).

## Acknowledgements

The analysis method set is informed by Crystal Instruments' *Acoustic Analysis*
overview (<https://www.crystalinstruments.com/acoustic-analysis>) and the referenced
standards (IEC 61260, IEC 61672, ANSI S1.11, ISO 3744/3745).
