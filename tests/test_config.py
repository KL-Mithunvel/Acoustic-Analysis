"""Tests for acoustic_analysis.config."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from acoustic_analysis.config import load_config, repo_root, resolve_path


def test_load_config_returns_expected_shape():
    cfg = load_config()
    assert isinstance(cfg, dict)
    assert cfg["audio"]["sample_rate"] == 48000
    assert cfg["octave"]["fraction"] in (1, 3, 6, 12)
    assert "good" in cfg["labels"]["classes"]


def test_resolve_path_is_absolute_under_repo_root():
    cfg = load_config()
    p = resolve_path(cfg, "database")
    assert p.is_absolute()
    assert repo_root() == p.parents[1]  # <root>/data/acoustic_analysis.sqlite


def test_load_config_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_load_config_not_a_mapping(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(textwrap.dedent("- just\n- a\n- list\n"), encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(bad)


def test_user_settings_layer_over_defaults_and_keep_config_yaml_untouched(tmp_path):
    from acoustic_analysis.config import (
        apply_user_settings, load_config, reset_user_settings, save_user_settings,
    )

    before = (Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8")
    cfg = load_config()
    cfg["paths"]["data_dir"] = str(tmp_path)
    default_len = cfg["capture"]["capture_duration_s"]
    default_rate = cfg["audio"]["sample_rate"]

    save_user_settings(cfg, {"capture": {"capture_duration_s": 1.25}})
    assert cfg["capture"]["capture_duration_s"] == 1.25
    assert cfg["capture"]["cooldown_s"] == load_config()["capture"]["cooldown_s"]   # siblings kept

    fresh = load_config()
    fresh["paths"]["data_dir"] = str(tmp_path)
    apply_user_settings(fresh)                                   # as on next start-up
    assert fresh["capture"]["capture_duration_s"] == 1.25

    reset_user_settings(cfg)
    assert cfg["capture"]["capture_duration_s"] == default_len and cfg["audio"]["sample_rate"] == default_rate
    assert cfg["paths"]["data_dir"] == str(tmp_path)             # this run's paths survive a reset
    assert not (tmp_path / "user_settings.yaml").exists()
    assert (Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8") == before


def test_corrupt_user_settings_are_ignored(tmp_path):
    from acoustic_analysis.config import apply_user_settings, load_config

    cfg = load_config()
    cfg["paths"]["data_dir"] = str(tmp_path)
    (tmp_path / "user_settings.yaml").write_text("{ not: [valid", encoding="utf-8")
    assert apply_user_settings(cfg)["capture"]["cooldown_s"] == load_config()["capture"]["cooldown_s"]
