# Acoustic-Analysis

A desktop workbench for **impact-acoustic analysis and data labelling** — record or
import tap-test sound clips, run a full acoustic-analysis suite on them (octave bands,
spectral descriptors, decay/damping, level metrics), compare them side by side, assign a
quality label, and export a labelled feature dataset for training a classifier.

Built for **acoustic non-destructive testing** — striking an object with a repeatable
impact and reading its ringing response to tell a sound part from a cracked one. The
first use case is clay/ceramic roofing tiles, but nothing in the analysis is
tile-specific.

> **Status: early scaffolding (v0.1).** The design and documentation are in place; the
> Python package is being built module by module. See [`TODO.md`](TODO.md).

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

Working toward v0.1:

- **Capture** — record clips from any input device (`sounddevice`), with a pre-trigger
  ring buffer and an amplitude trigger, or import existing WAV files.
- **Analysis suite** (see [`docs/METHODS.md`](docs/METHODS.md)):
  - fractional-octave-band levels (1/1 … 1/12 octave, IEC 61260 band edges)
  - FFT spectrum + descriptors: dominant frequency, peak list with Q, spectral
    centroid / bandwidth / roll-off / flatness
  - decay analysis: Hilbert envelope, T20 / T30, exponential decay rate, **per-octave-band
    decay rate** (the damping signature of a crack)
  - level metrics: L_eq, L_peak, Fast/Slow/Impulse time weighting, statistical levels Ln
  - A / C / Z frequency weighting (IEC 61672)
  - equal-loudness-contour loudness in sones *(planned)*
- **Visualise** — embedded plots: waveform, spectrum, 1/3-octave bar chart, decay
  waterfall; overlay two clips or a clip against a reference profile.
- **Label** — assign a quality class (configurable set) with grader + notes; build a
  golden reference profile from known-good clips.
- **Dataset** — every clip + its features + its label in a local SQLite database;
  one-click export to CSV / Parquet for model training.
- **Headless CLI** — analyse a file or a folder and dump features without opening the GUI.

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

# Or analyse files headlessly
python -m acoustic_analysis.cli analyze recordings\tile_0001.wav
python -m acoustic_analysis.cli analyze recordings\ --export features.csv
```

Run the tests:

```powershell
python -m pytest -q
```

## Project layout

```
acoustic_analysis/
  config.py            load config.yaml
  cli.py               headless: devices | analyze | export
  dsp/                 PURE signal processing — numpy in, numbers out, no I/O
    conditioning.py      DC removal, calibration, band-pass, impact detection, windowing
    spectrum.py          FFT + spectral descriptors + peak picking
    octave_bands.py      fractional-octave-band levels (IEC 61260)
    weighting.py         A / C / Z weighting (IEC 61672)
    sound_level.py       L_eq, L_peak, time weighting, statistical levels
    decay.py             envelope, T20/T30, decay rate, per-band decay
    loudness.py          equal-loudness-contour loudness  (planned)
  features.py          orchestrates dsp/* -> one feature dict per clip
  classify/            reference profile + rule-based grading
  io/                  recorder (sounddevice), wavstore, dataset (SQLite)
  app/                 Tkinter GUI (thin — wires widgets to the backend)
config.yaml            all tunable parameters
tests/                 one test module per dsp module, synthetic signals
data/                  recordings, SQLite db, exports  (git-ignored)
docs/METHODS.md        the analysis methods and how this app implements them
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
