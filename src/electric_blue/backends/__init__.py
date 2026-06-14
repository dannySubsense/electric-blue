"""Backend dispatch — transcribe(cfg, src) → (segments, info)."""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..models import Segment, TranscriptInfo
from .api import ApiBackend
from .base import Backend, Transcript
from .local import LocalBackend

_REGISTRY: dict[str, Backend] = {
    "local": LocalBackend(),
    "api": ApiBackend(),
}


def get_backend(cfg: Config) -> Backend:
    """Return the singleton backend for cfg.backend.

    Raises RuntimeError (not KeyError) on unknown backend name so that callers
    see a descriptive message rather than a raw key traceback.
    """
    name = cfg.backend
    if name not in _REGISTRY:
        available = list(_REGISTRY)
        raise RuntimeError(
            f"Unknown backend {name!r}. Available backends: {available}. "
            f"Set WHISPER_BACKEND to one of {available}."
        )
    return _REGISTRY[name]


def transcribe(cfg: Config, src: Path) -> tuple[list[Segment], TranscriptInfo]:
    """Dispatch to the configured backend. Public API — signature is stable.

    The if/else block is replaced by a registry lookup. All callers (watcher,
    CLI, smoke test) continue to unpack the result as (segments, info).
    """
    result: Transcript = get_backend(cfg).transcribe(cfg, src)
    return result.segments, result.info
