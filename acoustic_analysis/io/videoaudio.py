"""Getting audio and still frames out of a video file, via ffmpeg.

The tap-test recordings arrive as phone video: the sound is the measurement and
the picture identifies which tile is being struck. Both come from the same
ffmpeg binary, run as a subprocess - this module is the only place in the
package that shells out.

**Where ffmpeg comes from.** A system ffmpeg on PATH is used when present;
otherwise the one bundled in the ``imageio-ffmpeg`` wheel, which is a pip
dependency precisely so a fresh machine needs no separate install. An absent
ffmpeg raises with that instruction rather than failing obscurely inside a
subprocess call.

I/O layer, not pure: it touches the filesystem and spawns processes, so it is
smoke-tested against a generated file rather than unit-tested (see
.CLAUDE/CLAUDE.md Development Rule 1).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".3gp", ".mts", ".wmv"}
AUDIO_SUFFIXES = {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac"}

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")
_VIDEO_SIZE_RE = re.compile(r"Video:.*?(\d{2,5})x(\d{2,5})")

# Windows: keep ffmpeg from flashing a console window. Scrubbing the playhead
# grabs a frame per move, and a black box popping up each time is unusable.
_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}

_ffmpeg_cached: str | None = None


def is_video(path) -> bool:
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


def is_media(path) -> bool:
    return Path(path).suffix.lower() in (VIDEO_SUFFIXES | AUDIO_SUFFIXES)


def ffmpeg_exe() -> str:
    """Path to a usable ffmpeg, system first then the bundled one.

    Raises RuntimeError naming the pip package when neither is available.
    """
    global _ffmpeg_cached
    if _ffmpeg_cached:
        return _ffmpeg_cached

    found = shutil.which("ffmpeg")
    if not found:
        try:
            import imageio_ffmpeg

            found = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:  # noqa: BLE001 - any failure means "no ffmpeg"
            raise RuntimeError(
                "ffmpeg is not available. Install it with "
                "`pip install imageio-ffmpeg` (it ships its own binary), or put "
                f"ffmpeg on PATH. Underlying error: {exc}"
            ) from exc
    _ffmpeg_cached = found
    return found


def is_available() -> bool:
    """True when video import will work - for greying out the UI rather than
    letting the operator hit an exception."""
    try:
        ffmpeg_exe()
        return True
    except RuntimeError:
        return False


def _run(args: list[str], capture_stdout: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-nostdin", *args],
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        **_NO_WINDOW,
    )


def probe(path) -> dict:
    """What ffmpeg can see in this file: duration, and whether it has audio
    and video streams.

    Parsed from ``ffmpeg -i``'s own report rather than ffprobe, because the
    imageio-ffmpeg wheel ships ffmpeg only. ``ffmpeg -i`` with no output file
    always exits non-zero - that is expected, the information is on stderr.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    info = _run(["-i", str(path)]).stderr.decode("utf-8", "replace")

    duration_s = 0.0
    m = _DURATION_RE.search(info)
    if m:
        h, mnt, sec = m.groups()
        duration_s = int(h) * 3600 + int(mnt) * 60 + float(sec)

    size = _VIDEO_SIZE_RE.search(info)
    return {
        "duration_s": duration_s,
        "has_audio": "Audio:" in info,
        "has_video": "Video:" in info,
        "width": int(size.group(1)) if size else 0,
        "height": int(size.group(2)) if size else 0,
    }


def _cache_name(path: Path, fs: int) -> str:
    """Cache key covering path, size, mtime and rate.

    Including size and mtime means re-exporting a video to the same filename
    invalidates the cache instead of silently serving the old audio.
    """
    st = path.stat()
    digest = hashlib.sha1(
        f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{fs}".encode()
    ).hexdigest()[:16]
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in path.stem)[:40]
    return f"{stem}_{digest}.wav"


def extract_audio(
    path, sample_rate: int = 48000, cache_dir=None
) -> tuple[np.ndarray, int, Path]:
    """Decode a media file's audio to mono float at ``sample_rate``.

    Returns ``(samples, sample_rate, wav_path)``. The decoded WAV is kept in
    ``cache_dir`` and reused on the next open: re-decoding a ten-minute take
    every time the operator reopens it would make the Slice screen feel broken.

    Mono because every downstream analysis function takes one channel, and
    ffmpeg's downmix is better than averaging after the fact. Raises ValueError
    when the file carries no audio stream at all - the common case of a video
    exported picture-only, which is worth saying plainly.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    meta = probe(path)
    if not meta["has_audio"]:
        raise ValueError(f"{path.name} has no audio stream to extract")

    cache_dir = Path(cache_dir) if cache_dir else path.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    wav_path = cache_dir / _cache_name(path, sample_rate)

    if not wav_path.is_file():
        tmp = wav_path.with_suffix(".partial.wav")
        result = _run([
            "-y", "-i", str(path),
            "-vn",                    # drop video, we only want the track
            "-ac", "1",               # downmix to mono
            "-ar", str(int(sample_rate)),
            "-c:a", "pcm_f32le",      # float, so nothing is clipped or requantised
            "-f", "wav", str(tmp),
        ])
        if result.returncode != 0 or not tmp.is_file():
            tail = result.stderr.decode("utf-8", "replace").strip().splitlines()[-4:]
            raise RuntimeError(
                f"ffmpeg could not extract audio from {path.name}:\n" + "\n".join(tail)
            )
        tmp.replace(wav_path)  # atomic: a half-written cache file is never served

    data, fs = sf.read(wav_path, dtype="float64", always_2d=False)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return np.asarray(data, dtype=np.float64), int(fs), wav_path


def extract_frame_png(path, t_s: float, width: int = 480) -> bytes | None:
    """One frame at ``t_s`` as PNG bytes, or None if it cannot be read.

    PNG rather than raw pixels because Tk's ``PhotoImage(data=...)`` decodes it
    directly - no Pillow, no numpy round-trip, no extra dependency for what is
    a thumbnail.

    ``-ss`` is placed *before* ``-i`` deliberately: that seeks by index instead
    of decoding from the start of the file, which is the difference between a
    responsive scrub and a two-second wait per move. The cost is landing on the
    nearest keyframe, which for identifying a tile is immaterial.

    Returns None rather than raising: a missing thumbnail must not interrupt
    labelling, and frames are requested constantly while scrubbing.
    """
    path = Path(path)
    if not path.is_file():
        return None
    result = _run(
        [
            "-ss", f"{max(0.0, float(t_s)):.3f}",
            "-i", str(path),
            "-frames:v", "1",
            # -2 keeps the aspect ratio and an even height (some encoders
            # refuse odd dimensions).
            "-vf", f"scale={int(width)}:-2",
            "-c:v", "png",
            "-f", "image2pipe", "-",
        ],
        capture_stdout=True,
    )
    data = result.stdout
    return data if result.returncode == 0 and data else None
