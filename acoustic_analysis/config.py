"""Configuration loading.

The single source of tunable parameters is ``config.yaml`` at the repo root;
nothing else in the codebase hardcodes an audio or analysis value
(Development Rule 2).
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _REPO_ROOT / "config.yaml"


def repo_root() -> Path:
    """Absolute path to the repository root (the folder holding config.yaml)."""
    return _REPO_ROOT


def load_config(path: str | Path | None = None) -> dict:
    """Read and parse ``config.yaml``.

    Parameters
    ----------
    path:
        Explicit config file. Defaults to ``config.yaml`` at the repo root.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the file does not parse to a mapping.
    """
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not cfg_path.is_file():
        raise FileNotFoundError(f"config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"config file is not a mapping: {cfg_path}")
    return data


def resolve_path(cfg: dict, key: str) -> Path:
    """Resolve ``cfg['paths'][key]`` to an absolute path.

    Relative path values are anchored at the repo root so they behave the same
    regardless of the current working directory. Absolute values pass through.
    """
    value = Path(cfg["paths"][key])
    return value if value.is_absolute() else _REPO_ROOT / value
