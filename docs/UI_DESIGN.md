# UI Design

A **laptop desktop application** (Windows, mouse + keyboard) styled to look and feel
like a **handheld acoustic analyser** - a dark instrument screen framed by controls
that are always present, inspired by the Crystal Instruments CoCo-80X layout. It is not
a tablet or touch app; the "device" styling is purely a look.

The screenshot that inspired this is a third-party product image and is kept local
(git-ignored), not committed.

## Build order

1. **Plain tabs first.** A `ttk.Notebook` with one tab per screen, working end to end.
2. **Instrument-look restyle after.** Wrap the working screens in the frame below -
   dark theme, fixed status bar, persistent button rail, bottom soft-key bar. No screen
   logic changes in this pass, only layout and style.

## Frame layout (after the restyle)

```
+--------------------------------------------------------------+
| STATUS BAR:  <screen title>      src: USB Mic   CAL   17:43 REC|
+-------------------------------------------------+------------+
|                                                 |  BUTTON    |
|                                                 |  RAIL      |
|                 CONTENT AREA                     |            |
|            (the current screen)                  |  [Rec]     |
|                                                 |  [Play]    |
|                                                 |  [Open]    |
|                                                 |  [Save]    |
|                                                 |  [Snap]    |
|                                                 |  [Prev]    |
|                                                 |  [Next]    |
|                                                 |  [Back]    |
|                                                 |  [Home]    |
+-------------------------------------------------+------------+
| SOFT-KEYS:   [F1]   [F2]   [F3]   [F4]    Cancel     Apply   |
+--------------------------------------------------------------+
```

### Status bar (top, fixed)
Screen title, active input source, calibration state (`CAL` green / `uncal` grey),
clock, and a red `REC` indicator while recording.

### Button rail (right, fixed, never changes)
Global actions, same on every screen, each with a keyboard shortcut:

| Button | Action | Key |
|---|---|---|
| Record | arm / start-stop a capture | R |
| Play / Stop | play the selected clip through the speakers | Space |
| Open | import WAV file(s) | Ctrl+O |
| Save | save the selected clip / current state | Ctrl+S |
| Snapshot | PNG of the current view | F12 |
| Prev / Next | step through clips in the current list | [ / ] |
| Back | undo / leave the current screen | Esc |
| Home | go to the Home screen | H |

### Soft-key bar (bottom, context)
Up to four labelled actions that change per screen (e.g. `Add to reference`, `Label`,
`Export`, `Reset filters`) plus a right-aligned `Cancel` / `Apply` pair on screens that
edit something.

### Content area
Hosts the current screen. One screen visible at a time; the rail and soft-keys switch it.

## Screens

| Screen | Purpose |
|---|---|
| Home | launcher + current session summary (clip count, last grade, calibration age) |
| Monitor | live input: device picker, gain, level meter, live spectrum + scrolling spectrogram, OS-enhancement warning |
| Record | arm / trigger / record a clip, save into the session |
| Analyze | one clip - waveform, spectrum, 1/3-octave, energy-decay curve, feature table; every panel explained |
| Compare | several clips overlaid; a "what differs most" ranked table |
| Filters | the filter chain - live params, frequency-response (Bode) plot, before/after spectrum + spectrogram, A/B listen |
| Noise | capture a noise profile; environmental analysis (NC, Ln, tones); denoise preview |
| Slice | import a tap-test video, find its strikes, cut and label one snippet per tap, save them into the dataset |
| Label | assign a quality class, grader, notes; add to the reference set |
| Dataset | table of clips + labels + key features; filter, export, delete, per-clip report |
| Calibrate | reference-tone -> counts_per_pascal workflow |
| Learn | synthesise a tone / decay, apply a filter, watch what changes - a teaching bench |
| Settings | config presets, paths, theme |

### Slice screen layout

The only screen that is not about a single clip, so it gets its own arrangement:

```
+-------------------------------------------------------------------------+
| Open video... | taps.mp4        sensitivity [====]  Find strikes  Save   |
+-------------------------------------------------------+-----------------+
| Whole take (min/max envelope, cuts, view box)          | video frame at  |
+--------------------------------------------------------+ the playhead    |
| Detail - drag to select                                 |                |
|                                                         +-----------------+
|                                                         | grade  [ 3A v ] |
|                                                         | defect [good v] |
+---------------------------------------------------------+ Add selection   |
| |< strike  Play  Play sel  Stop  strike >|  [=scrub=]   | Apply to rows   |
+---------------------------------------------------------+ Play / Snap /   |
| # | start | dur | grade | defect | saved                 | Delete / Send   |
+---------------------------------------------------------+-----------------+
```

Two waveforms, not one: the overview answers "where am I and what is left to
do" (cuts are amber unlabelled, blue labelled, green saved), the detail answers
"exactly where does this cut start". The video frame is a labelling aid - it
says which tile is under the hammer - and deliberately does not play.

Number keys 1..n on the snippet table set the grade of the selected rows, Space
plays them and Delete removes them; taps come in runs of one tile, so the fast
path has to be one keystroke per snippet.

## Transparency / education

Every plot and every metric panel carries a small **"?"** toggle that opens a short
explanation: what it shows, how it is computed, and what a good vs a bad value looks
like. All that text lives in `docs/EXPLAIN.md` and is loaded at runtime, so it can be
edited without touching code. A glossary screen lists the same entries.

## Theme

Dark by default (near-black panel, light text, one accent colour for selection and the
`Apply` key), large fonts, generous padding, no hover-only affordances. A light theme is
a later nicety. Implemented with a custom `ttk.Style` on the `clam` base plus a matching
dark matplotlib style for the embedded plots.

## Threading

The Tk main thread owns all widgets. A single background worker thread runs recording,
feature extraction, and file analysis; results return via a `queue.Queue` drained by a
periodic `root.after()` poll. Nothing in `dsp/` or `features` is touched from two threads.
