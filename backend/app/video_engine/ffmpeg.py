"""Thin FFmpeg wrapper. Uses system ffmpeg if on PATH, else the imageio-ffmpeg bundled binary.
Probing parses `ffmpeg -i` output so ffprobe is not required."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.errors import StudioError

log = logging.getLogger(__name__)


@lru_cache
def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # pragma: no cover
        raise StudioError("FFmpeg not found. Install ffmpeg or `pip install imageio-ffmpeg`.") from e


def run(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise StudioError(f"ffmpeg failed ({proc.returncode}): {tail}", retryable=False)
    return proc


def analyze(args: list[str], timeout: int = 900) -> str:
    """Run an analysis pass (`-f null -`) and return stderr, where filters log results."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-nostdin", *args, "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return proc.stderr


@dataclass
class ProbeResult:
    duration: float
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    fps: float | None
    has_audio: bool
    has_video: bool


def probe(path: str | Path) -> ProbeResult:
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    err = proc.stderr
    if "No such file" in err or "Invalid data" in err:
        raise StudioError(f"Cannot read media file {path}")
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    v = re.search(r"Stream #\S+.*?Video: (\w+).*?, (\d{2,5})x(\d{2,5})", err)
    a = re.search(r"Stream #\S+.*?Audio: (\w+)", err)
    fps = re.search(r"([\d.]+) fps", err)
    return ProbeResult(
        duration=duration,
        width=int(v.group(2)) if v else None,
        height=int(v.group(3)) if v else None,
        video_codec=v.group(1) if v else None,
        audio_codec=a.group(1) if a else None,
        fps=float(fps.group(1)) if fps else None,
        has_audio=a is not None,
        has_video=v is not None,
    )


def silence(path: str | Path, seconds: float) -> None:
    run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{seconds:.2f}", "-c:a", "pcm_s16le", str(path)])


def to_wav(src: str | Path, dst: str | Path) -> None:
    run(["-i", str(src), "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(dst)])
