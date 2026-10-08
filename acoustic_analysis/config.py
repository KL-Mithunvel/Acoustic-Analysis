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


# -- user settings -----------------------------------------------------------
# The Settings screen's "Basic" controls are saved here, *not* into config.yaml:
# rewriting that file from a dict would strip every explanatory comment in it.
# The overrides file is layered over config.yaml at start-up; deleting it
# restores the shipped defaults.
USER_SETTINGS_NAME = "user_settings.yaml"


def user_settings_path(cfg: dict) -> Path:
    return resolve_path(cfg, "data_dir") / USER_SETTINGS_NAME


def _deep_update(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def apply_user_settings(cfg: dict) -> dict:
    """Layer ``<data_dir>/user_settings.yaml`` over ``cfg`` in place; no-op if absent
    or unreadable. Returns ``cfg``."""
    path = user_settings_path(cfg)
    if path.is_file():
        try:
            over = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            return cfg
        if isinstance(over, dict):
            _deep_update(cfg, over)
    return cfg


def save_user_settings(cfg: dict, changes: dict) -> Path:
    """Merge ``changes`` (nested dict) into the overrides file and into ``cfg``."""
    path = user_settings_path(cfg)
    current: dict = {}
    if path.is_file():
        try:
            current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            current = {}
    _deep_update(current, changes)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(current, sort_keys=False), encoding="utf-8")
    _deep_update(cfg, changes)
    return path


def reset_user_settings(cfg: dict) -> None:
    """Delete the overrides file and reload the shipped defaults into ``cfg`` in place."""
    path = user_settings_path(cfg)
    paths = dict(cfg.get("paths", {}))
    try:
        path.unlink()
    except OSError:
        pass
    fresh = load_config()
    fresh["paths"] = paths                      # keep where this run stores its data
    cfg.clear()
    cfg.update(fresh)
