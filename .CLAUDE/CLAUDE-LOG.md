# Claude Log

## 2026-09-08 — Repo bootstrap: standalone-app docs

- Repo `Acoustic-Analysis` created by the owner as a fresh skeleton (MIT `LICENSE`,
  empty `README.md`/`TODO.md`, `VERSION` 0.1, `.CLAUDE/` template) and linked into the
  Tile Sorting project as a git submodule at `Tile_Sorting/Acoustic-Analysis/`.
- Decided scope: a Windows desktop (Tkinter) workbench to record/import impact-acoustic
  clips, run a DSP analysis suite, visualise, label by quality class, and export a
  labelled feature dataset for downstream model training. Standalone — the tile line
  consumes only the exported dataset + trained model, never this code. No cross-imports
  either direction.
- Wrote the docs (no code yet):
  - `README.md` — public open-source README (what/why, features, Windows install, GUI +
    CLI quick start, project layout, roadmap, MIT, Crystal Instruments method credit).
  - `docs/METHODS.md` — standalone acoustic-analysis method reference: the processing
    chain, every metric the app will compute, what is deliberately not implemented and
    why, labelling/classification approach, calibration, hardware notes, standards
    (IEC 61260, IEC 61672, ANSI S1.11, ISO 532/3744 noted as not implemented).
  - `.CLAUDE/CLAUDE.md` — filled from the template: Project Overview, Running,
    Architecture (planned package layout + data flow + threading), Key Modules, Data
    Files, Platform Constraints, Known Technical Debt, 6 numbered Development Rules,
    User Rules pointer. Deleted the Schema Reference / Key Conventions / Deployment
    Notes sections (not applicable — desktop app, no DB schema to document beyond the
    simple SQLite store, no hardware/remote target).
  - `TODO.md` — full build backlog (DSP core + tests → audio I/O + SQLite dataset →
    CLI → classification → Tkinter GUI → packaging).
- Left untouched: `.CLAUDE/CLAUDE-COMMON.md` (shared, do-not-edit), `.CLAUDE/PROJ_STARTER.md`
  (personal prefs, verbatim), `VERSION`, `LICENSE`.
- Committed as ec839b4.

## 2026-09-09 — Full v0.1 build

Built the whole app in phases, one or more commits per phase, tests run and green
throughout (0 -> 133).

- **Phase 0** (bb6cf5a): venv + requirements (numpy/scipy/sounddevice/soundfile/
  matplotlib/pyyaml/pytest), `config.yaml` with every tunable + provisional flags,
  `config.py`, pytest harness, `tests/synth.py` (tone / decay / impact-clip generators).
- **Phase 1** (0e1cb9b, 59af2be, 2c982cd): pure DSP - `conditioning`, `spectrum`,
  `octave_bands` (IEC 61260 FFT-integration), `decay` (rewritten mid-phase onto Schroeder
  backward integration after multi-mode interference nulls fooled the raw-envelope fit),
  `weighting` (IEC 61672 analog -> bilinear -> SOS, checked vs IEC reference values),
  `sound_level` (Leq/Lpeak/time-weighting/Ln).
- **Phase 2** (252bea7): `features.extract_features` orchestrator + `conditioned_windows`
  helper + OK/RETEST validity gate.
- **Phase 3.5** (169b451): `dsp/filters` (composable FilterChain + `frequency_response`
  for the Bode plot), `dsp/noise` (noise profile + STFT spectral subtraction / gating),
  `dsp/environment` (NC tangency rating, dominant-tone finder, environmental summary).
- **Phase 3** (fa1554f): `io/wavstore` (WAV + JSON sidecar), `io/dataset`
  (SQLite sessions/clips/features/labels + CSV/JSON export), `io/recorder` +
  `io/audio_out` (lazy-`sounddevice` hardware wrappers, smoke-tested).
- **Phase 5** (10b7ffa): `classify/reference` (ReferenceProfile z-score compare) +
  `classify/rules` (GOOD/BORDERLINE/DEFECTIVE/RETEST with reasons).
- **Phase 4** (ae7afb9): `cli.py` (devices/analyze/noise/calibrate/export) + `__main__`.
- **Phase 6**: GUI core - explain/state/service (2606546); plots + widgets + main window +
  7 screens (eacd502); Monitor/Record/Calibrate/Settings (fbac568); dark instrument-look
  restyle with a fixed status bar, persistent button rail, and per-screen soft-key bar
  (e546ae9). Tabs-first then restyle, per the owner's decision.
- **Phase 7** (this entry): docs sync - README, CLAUDE.md, TODO.md, METHODS/EXPLAIN.

Scope was expanded twice mid-build by the owner: multi-file compare + live monitor +
denoise-in-analysis-path + full filter visibility + per-chart explanations; and the
instrument-style GUI look (from a CoCo-80X screenshot, kept local as a product image).

**Not done / not trusted:** never run against a real mic; no calibration measured; no
real-tile data so grading and every `config.yaml` threshold are unvalidated; no
PyInstaller build; `dsp/loudness.py` deferred. See `.CLAUDE/CLAUDE.md` Known Technical
Debt.

## 2026-09-09 — GUI restyle: sidebar nav + Home screen

Follow-on to the Phase 6 restyle, on branch `gui-restyle` (commits `b71f6dc` one-command
`main.py` launcher, `f8dd63f` theme-palette refresh + shell styles, `d8a7c5f` tab bar ->
left sidebar nav + instrument frame), then this pass wiring the Home screen in:

- `app/screens_home.py` (new, was uncommitted): `HomeScreen` - a launcher (Record / Open
  WAVs / Analyze / Dataset quick actions) plus a session summary: clips-in-session with a
  per-grade tally, last grade, calibration state, reference-profile state, and a
  recent-clips table. `refresh()` handles the empty session.
- `app/main_window.py`: `AppContext` gained `navigate` / `open_files` callable fields,
  set to `MainWindow._goto` / `.open_files` right after the context is built (before the
  screens are constructed, since `HomeScreen.__init__` wires buttons to them).
  `HomeScreen` prepended to `_NAV_GROUPS` as a new `SESSION` group, so it is screen 0 and
  the app opens on it; the rail's existing **Home** button (`_goto("Home")`) now resolves.
- Docs synced: `README.md` (12-screen, sidebar nav, `python main.py`, layout tree),
  `.CLAUDE/CLAUDE.md` (status, entry points, architecture tree, smoke-test wording).
- Deliberately skipped: the bare-key shortcuts from `docs/UI_DESIGN.md` (`H` Home, `R`
  Record). The current bindings are modifier/function keys only, on purpose - a bare
  letter binding would fire while typing in an entry field. Revisit with per-widget
  focus handling if wanted.
- 133 tests still green; `test_app_gui_smoke.py` now also constructs and visits Home.
  `py_compile` sweep clean.

## 2026-09-20 - v0.2: the Slice screen (tap-test video -> labelled snippets)

**The problem.** The project's acoustic data exists as phone video: one continuous take
holding dozens of strikes on tiles of several grades. Nothing in the app could use that
- every path here starts from a clip containing exactly one strike. The dataset was
empty (0 clips, 0 labels) and the blocker was not analysis, it was getting from footage
to clips.

**What was built**, following the existing pure/IO/GUI split:

- `dsp/segmentation.py` (pure) - `detect_onsets` finds every strike in a whole take:
  RMS envelope, threshold at a multiple of the take's own noise floor, rising edges
  only, a refractory gap, then a loudness filter against the loudest strike. Also
  `envelope_minmax`, min/max decimation so a 10-minute waveform can actually be drawn,
  and `segments_from_onsets` for the windows.
- `segments.py` (pure) - `Segment` / `SnippetSet` plus the list rules: time-ordered
  numbering, overlap refusal, snapping a hand-drawn selection onto a detected strike,
  per-axis label application, summary counts. No numpy, no I/O.
- `io/videoaudio.py` - ffmpeg as a subprocess: audio extraction (cached under
  `data/cache/`, keyed by path+mtime+rate) and single-frame PNG grabs. System ffmpeg
  first, else the `imageio-ffmpeg` bundled binary (new dependency, chosen so a fresh
  machine needs no separate install).
- `io/snippets.py` - the `<video>.snippets.json` sidecar, written beside the footage so
  in-progress cuts survive closing the app and travel with the video.
- `io/audio_out.Player` - an `OutputStream` that reports its position. `sd.play` cannot,
  and a playhead needs one.
- `app/screens_video.py` - the screen: overview + detail waveforms, drag-to-select,
  transport with a scrub bar, a debounced video frame at the playhead, the snippet
  table, and Save to dataset.

**Two label axes, by the owner's decision.** `label` stays the defect class; a new
nullable `grade_tier` column holds the cosmetic tier (3A/3B/4/5). Merging them would
have made the exported dataset unable to answer either question - a grade-4 tile can be
intact and a 3A tile can be cracked. `Dataset` gained a `_migrate()` that adds columns
to database files written by older builds, since `CREATE TABLE IF NOT EXISTS` would
otherwise leave them without it and every insert would fail.

**Three real bugs, all caught by tests rather than by reading:**

- `segments_from_onsets` trimmed a window to `next_onset - guard_ms`, but the *next*
  window starts `pre_ms` early to collect its own lead-in. With the defaults (pre 30 ms,
  guard 20 ms) consecutive snippets overlapped by 10 ms, so the same audio would have
  been exported twice under two labels. Now trimmed by `max(pre_ms, guard_ms)`.
- The save path wrote to SQLite from its worker thread - `sqlite3` objects belong to the
  thread that made them, and every save failed with that error. Restructured: the worker
  does the slow, thread-safe half (WAV + feature extraction) and hands rows back for the
  Tk thread to insert, which is also how every other screen writes.
- The GUI test module skipped intermittently in full-suite runs (7 tests silently not
  running while the suite reported green). Cause: two `tk.Tk()` create/destroy probes at
  collection time, one per GUI module, which occasionally fails on Windows. Moved to a
  session-cached `has_display()` in `conftest.py` with a retry; four consecutive full
  runs now give 197/197 with no skips.

**Verified:** 197 tests (was 133), four consecutive clean runs, `py_compile` sweep clean.
`test_video_slicing.py` and `test_app_slice_gui.py` build a real `.mp4` with ffmpeg and
run the whole chain - open, detect the four taps at their known times, label two grades,
save, and check the database rows, the CSV header, the WAVs on disk and the sidecar
resume. Also confirmed the cache is reused rather than re-decoded, and that a video with
no audio stream fails with a sentence rather than a stack trace.

**Not verified - no real footage exists yet.** Every video tested was generated: clean
synthetic taps, no room, no handling noise, no speech, no phone AGC. `config.yaml`
`video.onsets` is provisional and the sensitivity slider is on the toolbar because the
default will be wrong on the first real recording. `audio_out.Player` has never made a
sound, and the screen has been driven programmatically but never watched - drag feel,
playhead smoothness and frame-preview latency are all unassessed.

**Docs synced:** `README.md` (v0.2, 13 screens, 197 tests, Slice feature + ffmpeg
requirement, layout tree), `.CLAUDE/CLAUDE.md` (status, entry points, architecture tree,
key modules, data files, five new debt entries), `docs/METHODS.md` (new §1a on slicing a
long take and why the noise floor is a percentile; §6.1 rewritten for two label axes),
`docs/UI_DESIGN.md` (screen table + Slice layout sketch), `docs/EXPLAIN.md` (three new
"?" panels), `TODO.md`, `config.yaml` (new `video:` block, `labels.grades`), `VERSION`
0.1 -> 0.2, `.gitignore` (footage + sidecars are never committed).
