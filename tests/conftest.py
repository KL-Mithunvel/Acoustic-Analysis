"""Shared pytest fixtures."""

from __future__ import annotations

import functools
import time
import tkinter as tk

import numpy as np
import pytest


@pytest.fixture
def sample_rate() -> int:
    return 48000


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(12345)


@functools.lru_cache(maxsize=1)
def has_display() -> bool:
    """Can Tk open a window on this machine?

    Cached for the whole session, and shared by every GUI test module, because
    the probe itself is the problem it guards against: creating and destroying
    a root per module during collection intermittently fails on Windows, and a
    GUI module that skips for that reason reports green while testing nothing.
    One retry covers the transient case.
    """
    for _ in range(2):
        try:
            root = tk.Tk()
            root.destroy()
            return True
        except Exception:  # noqa: BLE001 - any failure here means "no display"
            time.sleep(0.2)
    return False
