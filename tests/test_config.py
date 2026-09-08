"""Tests for acoustic_analysis.config."""

from __future__ import annotations

import textwrap

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
