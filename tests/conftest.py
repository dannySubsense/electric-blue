"""Shared fixtures for the electric-blue test suite."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_dirs(tmp_path: Path) -> dict:
    """Return a dict of paths mirroring the pipeline directory layout."""
    dirs = {
        "base": tmp_path,
        "input": tmp_path / "inbox",
        "output": tmp_path / "transcripts",
        "done": tmp_path / "done",
        "failed": tmp_path / "failed",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def locate_ffmpeg() -> str | None:
    """Return path to ffmpeg binary, preferring PATH then imageio-ffmpeg."""
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            return exe
    except Exception:
        pass
    return None


@pytest.fixture()
def ffmpeg_bin() -> str | None:
    return locate_ffmpeg()


@pytest.fixture()
def sine_clip(tmp_path: Path, ffmpeg_bin: str | None) -> Path | None:
    """Generate a ~3s 440Hz sine-wave WAV clip. Returns None if ffmpeg unavailable."""
    if ffmpeg_bin is None:
        return None
    out = tmp_path / "sine.wav"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(out),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return out


@pytest.fixture()
def fake_transcribe(monkeypatch):
    """Monkeypatch electric_blue.backends.transcribe with a fake that returns canned data."""
    from electric_blue.models import Segment, TranscriptInfo

    fake_segments = [Segment(start=0.0, end=2.5, text="Hello world.")]
    fake_info = TranscriptInfo(
        language="en", language_probability=0.99, duration=2.5, backend="local:tiny"
    )

    def _fake(cfg, src):
        return fake_segments, fake_info

    monkeypatch.setattr("electric_blue.watcher.transcribe", _fake)
    return fake_segments, fake_info
