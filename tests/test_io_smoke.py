"""Smoke tests for the hardware I/O wrappers - they must import and, where
possible, enumerate devices. Full capture/playback needs real hardware and is
exercised by hand.
"""

from __future__ import annotations

import pytest

from acoustic_analysis.io import audio_out, recorder


def test_list_input_devices_returns_list_or_reports_no_portaudio():
    try:
        devices = recorder.list_input_devices()
    except RuntimeError as exc:
        pytest.skip(f"PortAudio unavailable: {exc}")
    assert isinstance(devices, list)
    for d in devices:
        assert {"index", "name", "channels", "default_samplerate"} <= set(d)


def test_audio_out_is_available_is_boolean():
    assert isinstance(audio_out.is_available(), bool)
