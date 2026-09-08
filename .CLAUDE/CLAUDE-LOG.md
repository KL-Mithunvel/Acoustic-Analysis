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
- Not committed yet in this repo. Next: scaffold `requirements.txt`, `config.yaml`, the
  `acoustic_analysis/` package skeleton, and `.gitignore`, then the first `dsp/` modules.
