"""Backend dispatch — transcribe(cfg, src) → (segments, info)."""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..models import Segment, TranscriptInfo


def transcribe(cfg: Config, src: Path) -> tuple[list[Segment], TranscriptInfo]:
    """Dispatch to local or API backend based on cfg.backend."""
    if cfg.backend == "api":
        from .api import transcribe_api

        return transcribe_api(cfg, src)
    else:
        from .local import transcribe_local

        return transcribe_local(cfg, src)
