"""Shared pytest fixtures."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def sample_rate() -> int:
    return 48000


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(12345)
