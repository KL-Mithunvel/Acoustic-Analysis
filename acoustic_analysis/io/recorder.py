"""Microphone input - device list, live monitoring, triggered clip capture.

Thin wrapper around ``sounddevice``. Not unit-tested (needs real hardware); the
file-import path in ``wavstore`` is its dev-machine equivalent. ``sounddevice``
is imported lazily so the rest of the package works on a machine without
PortAudio.
"""

from __future__ import annotations

import queue

import numpy as np

try:  # pragma: no cover - hardware dependent
    import sounddevice as _sd
except (OSError, ImportError):  # pragma: no cover
    _sd = None


def _require_sd():
    if _sd is None:  # pragma: no cover
        raise RuntimeError("sounddevice / PortAudio is not available on this machine")


def list_input_devices() -> list[dict]:
    """Every input-capable device: ``{index, name, channels, default_samplerate}``."""
    _require_sd()
    out = []
    for i, dev in enumerate(_sd.query_devices()):
        if dev["max_input_channels"] > 0:
            out.append(
                {
                    "index": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "default_samplerate": dev["default_samplerate"],
                }
            )
    return out


class LiveMonitor:  # pragma: no cover - hardware dependent
    """Continuous input stream. Calls ``on_block(mono_block, rms)`` per audio
    block on PortAudio's callback thread - keep the callback cheap.
    """

    def __init__(self, cfg: dict, on_block, device=None):
        _require_sd()
        audio = cfg["audio"]
        self.fs = int(audio["sample_rate"])
        self.block = int(audio.get("block_size", 1024))
        self.device = audio["device"] if device is None else device
        self.gain = float(cfg["capture"].get("input_gain", 1.0))
        self._on_block = on_block
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        mono = indata[:, 0].astype(np.float64) * self.gain
        rms = float(np.sqrt(np.mean(mono**2))) if mono.size else 0.0
        self._on_block(mono.copy(), rms)

    def start(self):
        self._stream = _sd.InputStream(
            samplerate=self.fs,
            blocksize=self.block,
            channels=1,
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


class Recorder:  # pragma: no cover - hardware dependent
    """Capture fixed-length clips, manually or on an RMS trigger, with a
    pre-trigger ring buffer so the strike's onset is not clipped.
    """

    def __init__(self, cfg: dict, device=None):
        _require_sd()
        audio, cap = cfg["audio"], cfg["capture"]
        self.fs = int(audio["sample_rate"])
        self.block = int(audio.get("block_size", 1024))
        self.device = audio["device"] if device is None else device
        self.gain = float(cap.get("input_gain", 1.0))
        self.pre_s = cap["pre_trigger_ms"] / 1000.0
        self.dur_s = cap["capture_duration_s"]
        self.threshold = cap["rms_threshold"]

    def capture(self, trigger: str = "manual", timeout_s: float = 30.0) -> tuple[np.ndarray, int]:
        """Return ``(samples, fs)``. ``trigger='manual'`` records immediately;
        ``trigger='rms'`` waits for the level to cross ``rms_threshold``.
        """
        if trigger not in ("manual", "rms"):
            raise ValueError("trigger must be 'manual' or 'rms'")
        pre_n = int(self.pre_s * self.fs)
        total_n = int(self.dur_s * self.fs)
        state = {"ring": np.zeros(pre_n), "triggered": trigger == "manual", "chunks": []}
        result: queue.Queue = queue.Queue()

        def cb(indata, frames, time_info, status):
            mono = indata[:, 0].astype(np.float64) * self.gain
            if not state["triggered"]:
                state["ring"] = np.concatenate([state["ring"], mono])[-pre_n:]
                if np.sqrt(np.mean(mono**2)) >= self.threshold:
                    state["triggered"] = True
                    state["chunks"].append(state["ring"].copy())
            else:
                state["chunks"].append(mono)
            if sum(len(c) for c in state["chunks"]) >= total_n:
                result.put(np.concatenate(state["chunks"])[:total_n])
                raise _sd.CallbackStop

        with _sd.InputStream(
            samplerate=self.fs, blocksize=self.block, channels=1,
            device=self.device, callback=cb,
        ):
            clip = result.get(timeout=timeout_s)
        return clip, self.fs
