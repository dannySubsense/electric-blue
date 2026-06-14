"""Characterization tests for the local backend dispatch (pre-refactor, Slice S1).

Both tests call the public backends.transcribe() entry point and are hermetic:
no faster-whisper model loaded, no real ffmpeg.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass as dc

from electric_blue.backends import transcribe
from electric_blue.config import Config
from electric_blue.models import Segment, TranscriptInfo

# ---------------------------------------------------------------------------
# Helpers (architecture §8.3, §8.4)
# ---------------------------------------------------------------------------


def fake_extract(cfg, src, dst, *, compressed):
    dst.write_bytes(b"x" * 100)


@dc
class FakeSegmentInfo:
    language: str = "en"
    language_probability: float = 0.99
    duration: float = 3.0


class FakeSegment:
    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class FakeWhisperModel:
    def transcribe(self, audio_path: str, **kwargs):
        segs = [FakeSegment(0.0, 2.5, " Hello world. ")]
        return iter(segs), FakeSegmentInfo()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_local_dispatch_returns_segments_and_info(monkeypatch, tmp_path):
    """Happy-path: local backend returns (list[Segment], TranscriptInfo) with backend tag."""
    monkeypatch.setattr("electric_blue.backends.local.extract", fake_extract)
    monkeypatch.setattr("electric_blue.backends.local._get_model", lambda cfg: FakeWhisperModel())
    cfg = dataclasses.replace(Config.from_env(), backend="local")
    src = tmp_path / "clip.wav"
    src.write_bytes(b"not real audio")

    segments, info = transcribe(cfg, src)

    assert isinstance(segments, list)
    assert all(isinstance(s, Segment) for s in segments)
    assert isinstance(info, TranscriptInfo)
    assert info.backend.startswith("local:")
