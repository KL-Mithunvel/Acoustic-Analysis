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
