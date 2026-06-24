"""Lightweight dataclasses for transcription output."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None

    def to_dict(self) -> dict:
        d = {"start": self.start, "end": self.end, "text": self.text}
        if self.speaker is not None:
            d["speaker"] = self.speaker
        return d


@dataclass
class TranscriptInfo:
    language: str
    language_probability: float | None
    duration: float
    backend: str

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "backend": self.backend,
        }
