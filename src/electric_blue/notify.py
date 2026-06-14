"""Best-effort webhook notification — never raises into the pipeline."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .config import Config
from .models import TranscriptInfo

log = logging.getLogger("electric_blue")


def _base_payload(
    event: str,
    cfg: Config,
    src: Path,
    started_at: datetime,
    finished_at: datetime | None = None,
) -> dict:
    """Build shared v1 envelope. finished_at=None emits no finished_at or wall_sec."""
    p: dict = {
        "schema_version": 1,
        "event": event,
        "file": src.name,
        "backend": cfg.backend,
        "started_at": started_at.isoformat(timespec="seconds"),
    }
    if finished_at is not None:
        p["finished_at"] = finished_at.isoformat(timespec="seconds")
        p["wall_sec"] = round((finished_at - started_at).total_seconds(), 1)
    return p


def build_started_payload(cfg: Config, src: Path, started_at: datetime) -> dict:
    """v1 payload for the 'started' event. No finished_at, no wall_sec."""
    return _base_payload("started", cfg, src, started_at)


def build_done_payload(
    cfg: Config,
    src: Path,
    info: TranscriptInfo,
    output_stems: dict[str, Path],
    started_at: datetime,
    finished_at: datetime,
) -> dict:
    """v1 payload for the 'done' event. All fields including outputs dict."""
    p = _base_payload("done", cfg, src, started_at, finished_at)
    p.update(
        {
            "status": "done",
            "duration_sec": round(info.duration, 1),
            "language": info.language,
            "backend": info.backend,
            "outputs": {fmt: path.name for fmt, path in output_stems.items()},
        }
    )
    return p


def build_failed_payload(
    cfg: Config,
    src: Path,
    error: Exception,
    started_at: datetime,
    finished_at: datetime,
) -> dict:
    """v1 payload for the 'failed' event. Error message only; no traceback."""
    p = _base_payload("failed", cfg, src, started_at, finished_at)
    p.update(
        {
            "status": "failed",
            "error": str(error),
        }
    )
    return p


def notify(cfg: Config, text: str, meta: dict | None = None) -> None:
    """POST a JSON ping to cfg.notify_webhook if set. Silently ignores all errors."""
    if not cfg.notify_webhook:
        return
    try:
        import requests

        payload = {"text": text}
        if meta:
            payload.update(meta)
        requests.post(cfg.notify_webhook, json=payload, timeout=15)
    except Exception as e:
        log.warning("notify failed: %s", e)
