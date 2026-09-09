#!/usr/bin/env python3
"""One-command launcher for Acoustic-Analysis.

Run with any Python - no virtual environment needs to be active:

    python main.py                     # first run: build venv + install deps, then GUI
    python main.py devices             # forward to the headless CLI
    python main.py analyze clip.wav
    python main.py analyze clips/ --export features.csv

On the first run this creates ``./venv`` and installs ``requirements.txt`` into it,
then re-executes itself inside that venv. Later runs skip straight to launching
once the ``venv/.deps-ok`` stamp is newer than ``requirements.txt``.

``python -m acoustic_analysis`` / ``python -m acoustic_analysis.cli`` still work
unchanged for anyone who manages the venv themselves.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / "venv"
REQUIREMENTS = ROOT / "requirements.txt"
DEPS_STAMP = VENV / ".deps-ok"

VENV_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _running_in_project_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == VENV_PYTHON.resolve()
    except OSError:
        return False


def _deps_current() -> bool:
    return DEPS_STAMP.is_file() and DEPS_STAMP.stat().st_mtime >= REQUIREMENTS.stat().st_mtime


def _bootstrap_venv() -> None:
    if not VENV_PYTHON.is_file():
        print(f"[main] creating virtual environment at {VENV} ...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    if not _deps_current():
        print("[main] installing dependencies from requirements.txt ...", flush=True)
        subprocess.check_call(
            [str(VENV_PYTHON), "-m", "pip", "install", "--quiet",
             "--disable-pip-version-check", "-r", str(REQUIREMENTS)]
        )
        DEPS_STAMP.write_text("ok\n", encoding="utf-8")


def main() -> int:
    if not _running_in_project_venv():
        _bootstrap_venv()
        return subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

    # Inside the project venv from here on.
    os.chdir(ROOT)
    args = sys.argv[1:]
    if args:
        from acoustic_analysis.cli import main as cli_main
        return cli_main(args)

    from acoustic_analysis.app.main_window import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
