"""Best-effort webhook notification — never raises into the pipeline."""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
from datetime import datetime
from pathlib import Path

import requests

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


def _format_ntfy(raw: dict) -> dict:
    """Translate a v1 payload dict into the ntfy JSON publish shape.

    Handles missing optional fields gracefully (failed has no outputs/duration_sec/language).
    Introduces no new fields derived from absolute paths or config secrets.
    """
    event = raw.get("event", "")
    filename = raw.get("file", "")
    backend = raw.get("backend", "")

    if event == "done":
        duration = raw.get("duration_sec", "?")
        title = f"Transcription done: {filename}"
        message = f"{duration}s audio · {backend}"
        priority = 3
        tags = ["white_check_mark"]
    elif event == "failed":
        error = raw.get("error", "unknown error")
        title = f"Transcription failed: {filename}"
        message = error
        priority = 4
        tags = ["x"]
    elif event == "started":
        title = f"Transcription started: {filename}"
        message = f"Processing with {backend}"
        priority = 2
        tags = ["hourglass_flowing_sand"]
    else:
        title = f"electric-blue: {event}: {filename}"
        message = f"backend: {backend}"
        priority = 3
        tags = []

    return {"title": title, "message": message, "priority": priority, "tags": tags}


def _format_payload(raw: dict, fmt: str) -> dict:
    """Dispatch to provider formatter. Unknown/generic: identity (return raw unchanged)."""
    if fmt == "ntfy":
        return _format_ntfy(raw)
    return raw  # "generic" or any unrecognised value — post the structured v1 dict as-is


def _sign(body_bytes: bytes, secret: str) -> str:
    """Return 'sha256=<hex>' HMAC over body_bytes. Secret never logged or returned."""
    return "sha256=" + _hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()


def _post_with_retry(
    url: str,
    body: dict,
    cfg: Config,
    headers: dict[str, str] | None = None,
) -> None:
    """POST body as JSON to url with bounded retry. Never raises.

    Retry policy (D3 locked):
    - Network errors and HTTP 5xx: retried up to cfg.notify_retries additional times.
    - HTTP 4xx: NOT retried (client error — misconfigured endpoint). Return immediately.
    - Total attempts = 1 + cfg.notify_retries.
    - No backoff between retries in v1.
    All failures logged at WARNING (never ERROR or higher).
    """
    for attempt in range(1 + cfg.notify_retries):
        try:
            r = requests.post(
                url,
                json=body,
                headers=headers or {},
                timeout=cfg.notify_timeout_sec,
            )
            if 400 <= r.status_code < 500:
                log.warning(
                    "notify attempt %d/%d: HTTP %d (4xx client error, not retried)",
                    attempt + 1,
                    1 + cfg.notify_retries,
                    r.status_code,
                )
                return  # abort — 4xx is not a transient failure
            if r.status_code >= 500:
                log.warning(
                    "notify attempt %d/%d: HTTP %d",
                    attempt + 1,
                    1 + cfg.notify_retries,
                    r.status_code,
                )
                # fall through to next iteration (retry)
            else:
                return  # 2xx/3xx success
        except Exception as e:
            log.warning(
                "notify attempt %d/%d failed: %s",
                attempt + 1,
                1 + cfg.notify_retries,
                e,
            )
    # All attempts exhausted or aborted — pipeline is unaffected


def notify(cfg: Config, payload: dict) -> None:
    """Post payload to cfg.notify_webhook. No-ops when webhook is unset. Never raises.

    Flow: guard → _format_payload → optional _sign → _post_with_retry.
    Outer try/except catches any exception from formatting or signing.
    """
    if not cfg.notify_webhook:
        return
    try:
        formatted = _format_payload(payload, cfg.notify_format)
        headers: dict[str, str] = {}
        if cfg.notify_hmac_secret:
            body_bytes = json.dumps(formatted, sort_keys=True, separators=(",", ":")).encode()
            headers["X-Electric-Blue-Signature"] = _sign(body_bytes, cfg.notify_hmac_secret)
        _post_with_retry(cfg.notify_webhook, formatted, cfg, headers)
    except Exception as e:
        log.warning("notify setup failed: %s", e)
