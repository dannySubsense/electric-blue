"""FFmpeg-based audio extraction."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import Config


def extract(cfg: Config, src: Path, dst: Path, *, compressed: bool) -> None:
    """Extract audio from *src* into *dst*.

    compressed=False → 16-kHz mono WAV (local backend).
    compressed=True  → low-bitrate mono MP3 (API backend, stays under size cap).
    """
    common = [cfg.ffmpeg_bin, "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000"]
    if compressed:
        cmd = common + ["-b:a", cfg.api_bitrate, str(dst)]
    else:
        cmd = common + ["-acodec", "pcm_s16le", str(dst)]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
