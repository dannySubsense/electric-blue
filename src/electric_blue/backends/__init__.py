"""Backend dispatch — transcribe(cfg, src) → (segments, info)."""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..models import Segment, TranscriptInfo
from .api import ApiBackend
from .base import Backend, Transcript
from .diarize import WhisperXBackend
from .local import LocalBackend

_REGISTRY: dict[str, Backend] = {
    "local": LocalBackend(),
    "api": ApiBackend(),
}

_FACTORIES: dict[str, type] = {"diarize": WhisperXBackend}


def get_backend(cfg: Config) -> Backend:
    """Return the backend for cfg.backend.

    Singleton backends are served from _REGISTRY. Factory backends are
    constructed on demand from _FACTORIES (each call returns a new instance).
    Raises RuntimeError (not KeyError) on unknown backend name so that callers
    see a descriptive message rather than a raw key traceback.
    """
    name = cfg.backend
    if name in _REGISTRY:
        return _REGISTRY[name]
    if name in _FACTORIES:
        return _FACTORIES[name](cfg)
    available = list(_REGISTRY) + list(_FACTORIES)
    raise RuntimeError(
        f"Unknown backend {name!r}. Available backends: {available}. "
        f"Set WHISPER_BACKEND to one of {available}."
    )


def transcribe(cfg: Config, src: Path) -> tuple[list[Segment], TranscriptInfo]:
    """Dispatch to the configured backend. Public API — signature is stable.

    The if/else block is replaced by a registry lookup. All callers (watcher,
    CLI, smoke test) continue to unpack the result as (segments, info).
    """
    result: Transcript = get_backend(cfg).transcribe(cfg, src)
    return result.segments, result.info
