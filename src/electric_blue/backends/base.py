"""Backend Protocol, Capabilities, and Transcript — the synchronous seam contract.

Import direction: base.py → models.py (never reverse).
No imports from local.py, api.py, or __init__.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import Config
from ..models import Segment, TranscriptInfo


@dataclass
class Capabilities:
    """Declarative capability record. Every Backend exposes one."""

    supports_diarization: bool
    max_upload_mb: int | None  # None = no cap (local); 24 = SI megabytes (api)
    needs_network: bool
    needs_gpu_recommended: bool
    # is_async intentionally absent — deferred to DDR-03 with AsyncBackend


@dataclass
class Transcript:
    """Typed return value of Backend.transcribe().

    Reuses existing dataclasses from models.py — no duplication.
    The public transcribe() in __init__.py unpacks this as (segments, info).
    """

    segments: list[Segment]
    info: TranscriptInfo


class Backend(Protocol):
    """Structural protocol for synchronous transcription backends.

    Implementors require no explicit inheritance — structural match suffices.
    """

    name: str
    capabilities: Capabilities

    def transcribe(self, cfg: Config, src: Path) -> Transcript: ...
